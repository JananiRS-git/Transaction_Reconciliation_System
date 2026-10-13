"""
Reconciliation engine: match CSV rows to transactions, store the settlements and
recompute every touched transaction from scratch (so re-running is always safe).

Matching strategy
-----------------
1. PRIMARY  - row has a lifecycle_id  -> look the transaction up by lifecycle_id.
              If it is unknown we do NOT guess with the fallback: an explicit id that
              points nowhere is a red flag, so the row goes to "unmatched".
2. FALLBACK - row has no lifecycle_id -> account_id + merchant_name + transaction_date.
              Exactly one transaction must match; zero or several -> "unmatched".
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import domain as d
from .csv_parser import ParseResult, SettlementRow, normalize_text

MATCHED_LIFECYCLE = "matched_lifecycle"
MATCHED_FALLBACK = "matched_fallback"
UNMATCHED = "unmatched"
DUPLICATE = "duplicate"
CONFLICT = "conflict"
INVALID = "invalid"


@dataclass
class RowOutcome:
    line: int
    settlement_id: Optional[str]
    outcome: str
    message: str = ""
    transaction_id: Optional[str] = None
    reason_code: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "line": self.line, "settlement_id": self.settlement_id, "outcome": self.outcome,
            "message": self.message, "transaction_id": self.transaction_id,
            "reason_code": self.reason_code, "warnings": self.warnings,
        }


@dataclass
class ReconcileReport:
    rows_total: int
    outcomes: list[RowOutcome]
    touched_transaction_ids: list[str]

    def count(self, *kinds: str) -> int:
        return sum(1 for o in self.outcomes if o.outcome in kinds)

    def summary(self) -> dict:
        return {
            "rows_total": self.rows_total,
            "matched": self.count(MATCHED_LIFECYCLE, MATCHED_FALLBACK),
            "matched_by_lifecycle_id": self.count(MATCHED_LIFECYCLE),
            "matched_by_fallback": self.count(MATCHED_FALLBACK),
            "unmatched": self.count(UNMATCHED),
            "duplicates": self.count(DUPLICATE),
            "conflicts": self.count(CONFLICT),
            "invalid": self.count(INVALID),
            "transactions_updated": len(self.touched_transaction_ids),
        }


# --- matching ----------------------------------------------------------------
def _find_by_lifecycle(conn, lifecycle_id):
    return conn.execute("SELECT * FROM transactions WHERE lifecycle_id = ?", (lifecycle_id,)).fetchall()


def _find_by_fallback(conn, row: SettlementRow):
    candidates = conn.execute(
        "SELECT * FROM transactions WHERE transaction_date = ?", (row.transaction_date.isoformat(),)
    ).fetchall()
    acct = normalize_text(row.account_id).casefold()
    merchant = normalize_text(row.merchant_name).casefold()
    return [t for t in candidates
            if normalize_text(t["account_id"]).casefold() == acct
            and normalize_text(t["merchant_name"]).casefold() == merchant]


def match_transaction(conn, row: SettlementRow):
    """Return (strategy, transaction_row | None, reason_code, message)."""
    if row.lifecycle_id:
        found = _find_by_lifecycle(conn, row.lifecycle_id)
        if len(found) == 1:
            return "lifecycle", found[0], None, ""
        if len(found) > 1:
            return None, None, "AMBIGUOUS", (
                f"lifecycle_id {row.lifecycle_id} belongs to {len(found)} transactions")
        return None, None, "LIFECYCLE_NOT_FOUND", (
            f"lifecycle_id {row.lifecycle_id} does not exist; fallback matching is not "
            f"used when an explicit lifecycle_id is supplied")
    found = _find_by_fallback(conn, row)
    if len(found) == 1:
        return "fallback", found[0], None, ""
    if len(found) > 1:
        return None, None, "AMBIGUOUS", (
            f"{len(found)} transactions share account {row.account_id}, merchant "
            f"'{row.merchant_name}' and date {row.transaction_date}")
    return None, None, "NO_MATCH", (
        f"no transaction for account {row.account_id}, merchant '{row.merchant_name}' "
        f"on {row.transaction_date}")


# --- persistence helpers -----------------------------------------------------
def _store_unmatched(conn, row: SettlementRow, code: str, reason: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO unmatched_settlements
           (settlement_id, lifecycle_id, account_id, merchant_name, transaction_date,
            settlement_date, settlement_amount, settlement_type, currency, reason_code, reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (row.settlement_id, row.lifecycle_id, row.account_id, row.merchant_name,
         row.transaction_date.isoformat() if row.transaction_date else None,
         row.settlement_date.isoformat(), d.from_cents(row.amount_cents),
         row.settlement_type, row.currency, code, reason),
    )


def _same_settlement(existing, row: SettlementRow) -> bool:
    return (d.to_cents(existing["settlement_amount"]) == row.amount_cents
            and existing["settlement_type"] == row.settlement_type
            and existing["settlement_date"] == row.settlement_date.isoformat()
            and existing["currency"] == row.currency)


def recompute_transaction(conn: sqlite3.Connection, transaction_id: str) -> None:
    """Rebuild status, net total and last settlement date from settlement_history."""
    txn = conn.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)).fetchone()
    rows = conn.execute(
        "SELECT settlement_id, settlement_type, settlement_amount, settlement_date "
        "FROM settlement_history WHERE transaction_id = ?", (transaction_id,)).fetchall()
    entries = [d.SettlementEntry(r["settlement_id"], r["settlement_type"],
                                 d.to_cents(r["settlement_amount"]), d.parse_iso_date(r["settlement_date"]))
               for r in rows]
    totals = d.summarize(entries)
    status = d.derive_status(txn["status"], d.to_cents(txn["transaction_amount"]), totals)
    conn.execute(
        "UPDATE transactions SET settlement_status=?, total_settled_amount=?, last_settlement_date=? "
        "WHERE transaction_id=?",
        (status, d.from_cents(totals.net), totals.last_date.isoformat() if totals.last_date else None,
         transaction_id),
    )


# --- main entry point --------------------------------------------------------
def reconcile(conn: sqlite3.Connection, parsed: ParseResult, source_name: str = "upload") -> ReconcileReport:
    outcomes: list[RowOutcome] = []
    touched: list[str] = []

    for err in parsed.errors:
        outcomes.append(RowOutcome(err.line, err.settlement_id, INVALID, "; ".join(err.errors)))

    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in parsed.rows:
            outcomes.append(_process_row(conn, row, touched))

        for txn_id in touched:
            recompute_transaction(conn, txn_id)

        outcomes.sort(key=lambda o: o.line)
        report = ReconcileReport(len(outcomes), outcomes, touched)
        s = report.summary()
        conn.execute(
            "INSERT INTO reconciliation_runs (source_name, rows_total, matched, unmatched, duplicates, invalid) "
            "VALUES (?,?,?,?,?,?)",
            (source_name, s["rows_total"], s["matched"], s["unmatched"],
             s["duplicates"] + s["conflicts"], s["invalid"]),
        )
        conn.execute("COMMIT")
        return report
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _process_row(conn, row: SettlementRow, touched: list[str]) -> RowOutcome:
    # 1. Already stored? -> idempotent re-upload.
    existing = conn.execute("SELECT * FROM settlement_history WHERE settlement_id = ?",
                            (row.settlement_id,)).fetchone()
    if existing:
        if _same_settlement(existing, row):
            return RowOutcome(row.line, row.settlement_id, DUPLICATE,
                              "Already processed earlier; skipped so nothing is counted twice.",
                              existing["transaction_id"])
        return RowOutcome(row.line, row.settlement_id, CONFLICT,
                          "settlement_id already exists with different amount/type/date/currency; "
                          "row ignored. Use a new settlement_id for corrections.",
                          existing["transaction_id"])

    # 2. Find the transaction.
    strategy, txn, code, reason = match_transaction(conn, row)
    if txn is None:
        _store_unmatched(conn, row, code, reason)
        return RowOutcome(row.line, row.settlement_id, UNMATCHED, reason, reason_code=code)

    # 3. Currency must agree with the transaction.
    if txn["currency"] != row.currency:
        reason = (f"currency {row.currency} differs from transaction {txn['transaction_id']} "
                  f"currency {txn['currency']}")
        _store_unmatched(conn, row, "CURRENCY_MISMATCH", reason)
        return RowOutcome(row.line, row.settlement_id, UNMATCHED, reason,
                          txn["transaction_id"], "CURRENCY_MISMATCH")

    # 4. Soft warnings (row is still applied).
    warnings: list[str] = []
    if row.account_id and normalize_text(row.account_id).casefold() != normalize_text(txn["account_id"]).casefold():
        warnings.append(f"account_id {row.account_id} differs from the transaction's {txn['account_id']}")
    if row.merchant_name and normalize_text(row.merchant_name).casefold() != normalize_text(txn["merchant_name"]).casefold():
        warnings.append(f"merchant '{row.merchant_name}' differs from the transaction's '{txn['merchant_name']}'")
    if row.settlement_date < d.parse_iso_date(txn["transaction_date"]):
        warnings.append("settlement_date is before the transaction date")
    if txn["status"] != d.TXN_COMPLETED:
        warnings.append(f"transaction is {txn['status']}; it should not have a settlement")

    # 5. Store it (and clear any earlier 'unmatched' record for the same id).
    conn.execute("DELETE FROM unmatched_settlements WHERE settlement_id = ?", (row.settlement_id,))
    conn.execute(
        "INSERT INTO settlement_history (settlement_id, transaction_id, lifecycle_id, settlement_date, "
        "settlement_amount, settlement_type, currency) VALUES (?,?,?,?,?,?,?)",
        (row.settlement_id, txn["transaction_id"], row.lifecycle_id or txn["lifecycle_id"],
         row.settlement_date.isoformat(), d.from_cents(row.amount_cents), row.settlement_type, row.currency),
    )
    if txn["transaction_id"] not in touched:
        touched.append(txn["transaction_id"])

    how = "lifecycle_id" if strategy == "lifecycle" else "account + merchant + date (fallback)"
    return RowOutcome(
        row.line, row.settlement_id,
        MATCHED_LIFECYCLE if strategy == "lifecycle" else MATCHED_FALLBACK,
        f"Matched to {txn['transaction_id']} by {how}.", txn["transaction_id"], warnings=warnings)
