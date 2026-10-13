"""Read-side logic: build transaction views, issue flags and dashboard statistics."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from typing import Optional

from . import domain as d


class NotFound(LookupError):
    pass


# --- loading -----------------------------------------------------------------
def _entries_by_transaction(conn) -> dict[str, list[d.SettlementEntry]]:
    result: dict[str, list[d.SettlementEntry]] = defaultdict(list)
    for r in conn.execute(
        "SELECT settlement_id, transaction_id, settlement_type, settlement_amount, settlement_date "
        "FROM settlement_history WHERE transaction_id IS NOT NULL"
    ):
        result[r["transaction_id"]].append(d.SettlementEntry(
            r["settlement_id"], r["settlement_type"], d.to_cents(r["settlement_amount"]),
            d.parse_iso_date(r["settlement_date"])))
    return result


def build_view(txn: sqlite3.Row, entries: list[d.SettlementEntry], as_of: date) -> dict:
    """Combine one transaction with its settlements into the JSON shape used by the API."""
    amount = d.to_cents(txn["transaction_amount"])
    txn_date = d.parse_iso_date(txn["transaction_date"])
    totals = d.summarize(entries)
    status = d.derive_status(txn["status"], amount, totals)
    issues = d.detect_issues(txn["status"], txn_date, amount, txn["currency"], status, totals, as_of)
    return {
        "transaction_id": txn["transaction_id"],
        "lifecycle_id": txn["lifecycle_id"],
        "account_id": txn["account_id"],
        "merchant_name": txn["merchant_name"],
        "transaction_date": txn["transaction_date"],
        "transaction_amount": d.from_cents(amount),
        "currency": txn["currency"],
        "status": txn["status"],
        "settlement_status": status,
        "total_settled_amount": d.from_cents(totals.net),
        "total_debits": d.from_cents(totals.debits),
        "total_credits": d.from_cents(totals.credits),
        "settlement_count": totals.count,
        "last_settlement_date": totals.last_date.isoformat() if totals.last_date else None,
        "outstanding_amount": d.from_cents(d.outstanding_cents(status, amount, totals)),
        "over_settled_amount": d.from_cents(d.over_settled_cents(status, amount, totals)),
        "days_to_settle": ((max((totals.first_debit_date - txn_date).days, 0))
                           if totals.first_debit_date else None),
        "issue_flag": d.issue_flag(issues),
        "issues": [i.to_dict() for i in issues],
        # internal helpers (stripped before sending where not needed)
        "_entries": entries, "_totals": totals,
    }


def _public(view: dict) -> dict:
    return {k: v for k, v in view.items() if not k.startswith("_")}


# --- public queries ----------------------------------------------------------
def list_transactions(conn, as_of: date, status: Optional[str] = None, issue: Optional[str] = None,
                      search: Optional[str] = None) -> list[dict]:
    entries = _entries_by_transaction(conn)
    views = [build_view(t, entries.get(t["transaction_id"], []), as_of)
             for t in conn.execute("SELECT * FROM transactions ORDER BY transaction_date, transaction_id")]
    if status:
        views = [v for v in views if v["settlement_status"] == status]
    if issue:
        views = [v for v in views if v["issue_flag"] == issue]
    if search:
        needle = search.strip().casefold()
        views = [v for v in views if needle in " ".join(
            str(v[k]) for k in ("transaction_id", "merchant_name", "account_id", "lifecycle_id")
        ).casefold()]
    return views


def get_transaction_detail(conn, transaction_id: str, as_of: date) -> dict:
    txn = conn.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)).fetchone()
    if txn is None:
        raise NotFound(f"Transaction {transaction_id} not found")
    rows = conn.execute(
        "SELECT * FROM settlement_history WHERE transaction_id = ? ORDER BY settlement_date, settlement_id",
        (transaction_id,)).fetchall()
    entries = [d.SettlementEntry(r["settlement_id"], r["settlement_type"], d.to_cents(r["settlement_amount"]),
                                 d.parse_iso_date(r["settlement_date"])) for r in rows]
    view = build_view(txn, entries, as_of)
    view["settlements"] = [{
        "settlement_id": r["settlement_id"], "transaction_id": r["transaction_id"],
        "lifecycle_id": r["lifecycle_id"], "settlement_date": r["settlement_date"],
        "settlement_amount": r["settlement_amount"], "settlement_type": r["settlement_type"],
        "currency": r["currency"], "processed_at": r["processed_at"],
    } for r in rows]
    view["timeline"] = d.build_timeline(
        d.parse_iso_date(txn["transaction_date"]), d.to_cents(txn["transaction_amount"]),
        txn["currency"], entries, view["settlement_status"], as_of)
    view["created_at"] = txn["created_at"]
    return _public(view)


def public_list(views: list[dict]) -> list[dict]:
    return [_public(v) for v in views]


def dashboard_summary(conn, as_of: date) -> dict:
    views = list_transactions(conn, as_of)
    status_counts = {s: 0 for s in d.ALL_STATUSES}
    critical = warning = clean = 0
    outstanding = over = completed_total = net_total = 0
    completed = with_debit = 0
    days: list[int] = []
    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"debits": 0, "credits": 0})

    for v in views:
        status_counts[v["settlement_status"]] += 1
        flag = v["issue_flag"]
        critical += flag == d.CRITICAL
        warning += flag == d.WARNING
        clean += flag == d.NO_ISSUE
        outstanding += d.to_cents(v["outstanding_amount"])
        over += d.to_cents(v["over_settled_amount"])
        net_total += d.to_cents(v["total_settled_amount"])
        if v["status"] == d.TXN_COMPLETED:
            completed += 1
            completed_total += d.to_cents(v["transaction_amount"])
            if v["days_to_settle"] is not None:
                with_debit += 1
                days.append(v["days_to_settle"])
        for e in v["_entries"]:
            bucket = daily[e.date.isoformat()]
            bucket["debits" if e.type == d.DEBIT else "credits"] += e.amount_cents

    unmatched = [dict(r) for r in conn.execute(
        "SELECT * FROM unmatched_settlements ORDER BY settlement_id")]
    matched_count = conn.execute("SELECT COUNT(*) FROM settlement_history").fetchone()[0]
    last_run = conn.execute("SELECT * FROM reconciliation_runs ORDER BY run_id DESC LIMIT 1").fetchone()

    return {
        "as_of": as_of.isoformat(),
        "totals": {
            "transactions": len(views),
            "completed_transactions": completed,
            "settlements_processed": matched_count + len(unmatched),
            "settlements_matched": matched_count,
            "settlements_unmatched": len(unmatched),
        },
        "status_breakdown": status_counts,
        "issues": {"critical": critical, "warning": warning, "none": clean},
        "amounts": {
            "total_transaction_amount": d.from_cents(completed_total),
            "total_net_settled": d.from_cents(net_total),
            "outstanding_amount": d.from_cents(outstanding),
            "over_settled_amount": d.from_cents(over),
            "currency": views[0]["currency"] if views else "USD",
        },
        "performance": {
            "avg_days_to_settle": round(sum(days) / len(days), 1) if days else None,
            "settlement_rate": round(with_debit / completed, 4) if completed else None,
            "settled_transactions": with_debit,
        },
        "daily_settlements": [
            {"date": k, "debits": d.from_cents(v["debits"]), "credits": d.from_cents(v["credits"])}
            for k, v in sorted(daily.items())],
        "unmatched_settlements": unmatched,
        "last_run": dict(last_run) if last_run else None,
    }
