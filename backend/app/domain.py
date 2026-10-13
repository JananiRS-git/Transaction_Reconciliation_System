"""
Pure business rules for reconciliation (no database, no Flask).

All money is handled as integer cents to avoid floating point errors
(e.g. 0.1 + 0.2 != 0.3 with floats).

PARTIAL vs REFUNDED  (see README for the full explanation)
----------------------------------------------------------
Both mean "net settled < transaction amount", but the cause differs:
  * PARTIAL  - we collected LESS than we should have (settlement is short).
  * REFUNDED - we collected the FULL amount (debits >= amount) and then
               returned part of it through at least one CREDIT.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Optional

# --- constants ---------------------------------------------------------------
OVERDUE_DAYS = 7  # "no settlement after 7 days from transaction date"

PENDING = "PENDING"
PARTIAL = "PARTIAL"
FULLY_SETTLED = "FULLY_SETTLED"
OVER_SETTLED = "OVER_SETTLED"
REFUNDED = "REFUNDED"
NOT_APPLICABLE = "NOT_APPLICABLE"
ALL_STATUSES = (PENDING, PARTIAL, FULLY_SETTLED, OVER_SETTLED, REFUNDED, NOT_APPLICABLE)

DEBIT = "DEBIT"
CREDIT = "CREDIT"
SETTLEMENT_TYPES = (DEBIT, CREDIT)

TXN_COMPLETED = "COMPLETED"

CRITICAL = "critical"
WARNING = "warning"
NO_ISSUE = "none"


# --- money helpers -----------------------------------------------------------
def to_cents(value) -> int:
    """Convert a number / numeric string to integer cents (rounded half-up)."""
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a valid amount: {value!r}") from exc


def from_cents(cents: int) -> float:
    return round(cents / 100, 2)


def money(cents: int, currency: str = "") -> str:
    sign = "-" if cents < 0 else ""
    text = f"{sign}{abs(cents) / 100:,.2f}"
    return f"{text} {currency}".strip()


def parse_iso_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# --- data classes ------------------------------------------------------------
@dataclass(frozen=True)
class SettlementEntry:
    settlement_id: str
    type: str          # DEBIT / CREDIT
    amount_cents: int  # always positive
    date: date


@dataclass(frozen=True)
class Totals:
    count: int
    debits: int
    credits: int
    first_debit_date: Optional[date]
    last_date: Optional[date]

    @property
    def net(self) -> int:
        return self.debits - self.credits


@dataclass(frozen=True)
class Issue:
    severity: str        # CRITICAL / WARNING
    code: str
    title: str
    detail: str
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


# --- core rules --------------------------------------------------------------
def summarize(entries: Iterable[SettlementEntry]) -> Totals:
    """Total debits, credits and dates for a transaction's settlements."""
    count = debits = credits = 0
    first_debit: Optional[date] = None
    last: Optional[date] = None
    for e in entries:
        count += 1
        if e.type == DEBIT:
            debits += e.amount_cents
            if first_debit is None or e.date < first_debit:
                first_debit = e.date
        else:
            credits += e.amount_cents
        if last is None or e.date > last:
            last = e.date
    return Totals(count, debits, credits, first_debit, last)


def derive_status(txn_status: str, amount_cents: int, totals: Totals) -> str:
    """
    Decision order (first match wins):
      0. transaction is not COMPLETED (FAILED / DECLINED ...)  -> NOT_APPLICABLE
      1. no settlements at all                                  -> PENDING
      2. net == amount                                          -> FULLY_SETTLED
      3. net  > amount                                          -> OVER_SETTLED
      4. net  < amount, debits >= amount, at least one credit   -> REFUNDED
      5. net  < amount (anything else)                          -> PARTIAL
    """
    if txn_status != TXN_COMPLETED:
        return NOT_APPLICABLE
    if totals.count == 0:
        return PENDING
    net = totals.net
    if net == amount_cents:
        return FULLY_SETTLED
    if net > amount_cents:
        return OVER_SETTLED
    if totals.credits > 0 and totals.debits >= amount_cents:
        return REFUNDED
    return PARTIAL


def outstanding_cents(status: str, amount_cents: int, totals: Totals) -> int:
    """Money still expected from settlement (PENDING and PARTIAL only).
    Refunded money is NOT outstanding - it was returned on purpose."""
    if status == PENDING:
        return amount_cents
    if status == PARTIAL:
        return amount_cents - max(totals.net, 0)
    return 0


def over_settled_cents(status: str, amount_cents: int, totals: Totals) -> int:
    return totals.net - amount_cents if status == OVER_SETTLED else 0


def detect_issues(
    txn_status: str,
    txn_date: date,
    amount_cents: int,
    currency: str,
    status: str,
    totals: Totals,
    as_of: date,
) -> list[Issue]:
    """Return the issues for one transaction (critical first)."""
    issues: list[Issue] = []

    # A settlement exists for a transaction that should never settle.
    if txn_status != TXN_COMPLETED:
        if totals.count > 0:
            issues.append(Issue(
                CRITICAL, "SETTLED_NON_COMPLETED",
                f"Settlement received for a {txn_status} transaction",
                f"{money(totals.net, currency)} was settled, but a {txn_status} transaction "
                f"should never settle.",
                "Reverse the settlement and confirm with the acquirer why it was sent.",
            ))
        return issues

    if status == PENDING:
        days = (as_of - txn_date).days
        if days > OVERDUE_DAYS:
            issues.append(Issue(
                CRITICAL, "NO_SETTLEMENT_OVERDUE",
                f"No settlement after {OVERDUE_DAYS} days",
                f"Transaction is {days} days old and has no settlement "
                f"({money(amount_cents, currency)} outstanding).",
                "Contact the acquirer / processor to find out why the settlement is missing, "
                "and check whether it was sent under a different identifier.",
            ))
        return issues

    if totals.net < 0:
        issues.append(Issue(
            CRITICAL, "NEGATIVE_NET",
            "Credits exceed debits",
            f"Net settlement is {money(totals.net, currency)}: more money was returned than collected.",
            "Check for a missing DEBIT settlement or a credit applied to the wrong transaction.",
        ))
    elif status == OVER_SETTLED:
        over = totals.net - amount_cents
        issues.append(Issue(
            CRITICAL, "OVER_SETTLED",
            "Settled more than the transaction amount",
            f"Net settled {money(totals.net, currency)} against a "
            f"{money(amount_cents, currency)} transaction ({money(over, currency)} too much).",
            f"Raise a dispute with the acquirer and recover the {money(over, currency)} overpayment "
            f"(or check for a duplicate debit).",
        ))
    elif status == PARTIAL:
        short = amount_cents - totals.net
        issues.append(Issue(
            WARNING, "PARTIAL_SETTLEMENT",
            "Settled less than the transaction amount",
            f"Net settled {money(totals.net, currency)} of {money(amount_cents, currency)} "
            f"({money(short, currency)} still missing).",
            f"Wait for a follow-up settlement; if none arrives, claim the missing "
            f"{money(short, currency)} from the acquirer.",
        ))
    return sorted(issues, key=lambda i: 0 if i.severity == CRITICAL else 1)


def issue_flag(issues: list[Issue]) -> str:
    if any(i.severity == CRITICAL for i in issues):
        return CRITICAL
    if any(i.severity == WARNING for i in issues):
        return WARNING
    return NO_ISSUE


def build_timeline(
    txn_date: date,
    amount_cents: int,
    currency: str,
    entries: list[SettlementEntry],
    status: str,
    as_of: date,
) -> list[dict]:
    """Chronological events with a running net balance (for the timeline chart)."""
    events = [{
        "date": txn_date.isoformat(), "kind": "transaction",
        "label": "Transaction completed", "amount": from_cents(amount_cents),
        "running_net": 0.0, "currency": currency,
    }]
    running = 0
    for e in sorted(entries, key=lambda x: (x.date, x.settlement_id)):
        running += e.amount_cents if e.type == DEBIT else -e.amount_cents
        events.append({
            "date": e.date.isoformat(),
            "kind": "debit" if e.type == DEBIT else "credit",
            "label": f"{e.settlement_id} ({'debit' if e.type == DEBIT else 'credit'})",
            "amount": from_cents(e.amount_cents),
            "running_net": from_cents(running), "currency": currency,
        })
    if status == PENDING:
        deadline = txn_date + timedelta(days=OVERDUE_DAYS)
        events.append({
            "date": deadline.isoformat(), "kind": "deadline",
            "label": "Settlement window ends", "amount": 0.0,
            "running_net": 0.0, "currency": currency, "overdue": as_of > deadline,
        })
    return events
