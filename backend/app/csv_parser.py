"""
Parse and validate a settlement CSV.

* File-level problems (empty file, missing columns, not text) raise CsvFormatError.
* Row-level problems never stop the run: the bad row is reported in `errors`
  and every other row is still processed.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from .domain import SETTLEMENT_TYPES, to_cents

REQUIRED_COLUMNS = (
    "settlement_id", "lifecycle_id", "account_id", "merchant_name",
    "transaction_date", "settlement_date", "settlement_amount",
    "settlement_type", "currency",
)
MAX_AMOUNT = Decimal("99999999.99")  # DECIMAL(10,2)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class CsvFormatError(ValueError):
    """The whole file is unusable."""


@dataclass(frozen=True)
class SettlementRow:
    line: int
    settlement_id: str
    lifecycle_id: Optional[str]
    account_id: Optional[str]
    merchant_name: Optional[str]
    transaction_date: Optional[date]
    settlement_date: date
    amount_cents: int
    settlement_type: str
    currency: str


@dataclass(frozen=True)
class RowError:
    line: int
    settlement_id: Optional[str]
    errors: list[str]


@dataclass
class ParseResult:
    rows: list[SettlementRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.rows) + len(self.errors)


def normalize_text(value: Optional[str]) -> str:
    """Trim and collapse any whitespace (including line breaks) to single spaces."""
    return " ".join((value or "").split())


def _parse_date(raw: str, field_name: str, errors: list[str]) -> Optional[date]:
    if not _DATE_RE.match(raw):
        errors.append(f"{field_name} '{raw}' is not a valid date (expected YYYY-MM-DD)")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.append(f"{field_name} '{raw}' is not a real calendar date")
        return None


def _parse_amount(raw: str, errors: list[str]) -> Optional[int]:
    if raw == "":
        errors.append("settlement_amount is missing")
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        errors.append(f"settlement_amount '{raw}' is not a number")
        return None
    if not amount.is_finite():
        errors.append(f"settlement_amount '{raw}' is not a finite number")
        return None
    if amount <= 0:
        errors.append(f"settlement_amount must be positive (got {raw})")
        return None
    if amount.as_tuple().exponent < -2:
        errors.append(f"settlement_amount '{raw}' has more than 2 decimal places")
        return None
    if amount > MAX_AMOUNT:
        errors.append(f"settlement_amount '{raw}' is too large")
        return None
    return to_cents(amount)


def parse_settlement_csv(data) -> ParseResult:
    """`data` may be bytes or str."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CsvFormatError("File is not valid UTF-8 text. Please upload a CSV file.") from exc
    else:
        text = data.lstrip("\ufeff")

    if "\x00" in text:
        raise CsvFormatError("File looks like a binary file, not a CSV.")
    if not text.strip():
        raise CsvFormatError("The CSV file is empty.")

    reader = csv.DictReader(io.StringIO(text, newline=""), skipinitialspace=True)
    if not reader.fieldnames:
        raise CsvFormatError("The CSV file has no header row.")
    reader.fieldnames = [normalize_text(h).lower() for h in reader.fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise CsvFormatError(f"Missing required column(s): {', '.join(missing)}")

    result = ParseResult()
    try:
        for raw in reader:
            line = reader.line_num
            row = {k: normalize_text(v) if isinstance(v, str) else v
                   for k, v in raw.items() if k is not None}
            errors: list[str] = []

            if None in raw:  # more values than headers
                errors.append("row has more columns than the header (unquoted comma?)")
            if any(v is None for v in row.values()):
                errors.append("row has fewer columns than the header")
                row = {k: (v or "") for k, v in row.items()}

            settlement_id = row.get("settlement_id", "")
            if not settlement_id:
                errors.append("settlement_id is missing")
            elif len(settlement_id) > 50:
                errors.append("settlement_id is longer than 50 characters")

            lifecycle_id = row.get("lifecycle_id", "") or None
            account_id = row.get("account_id", "") or None
            merchant = row.get("merchant_name", "") or None
            txn_date_raw = row.get("transaction_date", "")

            txn_date = None
            if txn_date_raw:
                txn_date = _parse_date(txn_date_raw, "transaction_date", errors)

            # The fallback strategy needs these three fields when there is no lifecycle_id.
            if lifecycle_id is None:
                for name, value in (("account_id", account_id), ("merchant_name", merchant),
                                    ("transaction_date", txn_date_raw)):
                    if not value:
                        errors.append(f"{name} is required when lifecycle_id is empty")

            settle_date = None
            if not row.get("settlement_date"):
                errors.append("settlement_date is missing")
            else:
                settle_date = _parse_date(row["settlement_date"], "settlement_date", errors)

            amount_cents = _parse_amount(row.get("settlement_amount", ""), errors)

            stype = row.get("settlement_type", "").upper()
            if stype not in SETTLEMENT_TYPES:
                errors.append(f"settlement_type '{row.get('settlement_type', '')}' must be DEBIT or CREDIT")

            currency = row.get("currency", "").upper()
            if not _CURRENCY_RE.match(currency):
                errors.append(f"currency '{row.get('currency', '')}' must be a 3-letter code such as USD")

            if errors:
                result.errors.append(RowError(line, settlement_id or None, errors))
                continue

            result.rows.append(SettlementRow(
                line=line, settlement_id=settlement_id, lifecycle_id=lifecycle_id,
                account_id=account_id, merchant_name=merchant, transaction_date=txn_date,
                settlement_date=settle_date, amount_cents=amount_cents,
                settlement_type=stype, currency=currency,
            ))
    except csv.Error as exc:
        raise CsvFormatError(f"The file is not a well-formed CSV: {exc}") from exc

    if result.total_rows == 0:
        raise CsvFormatError("The CSV has a header but no data rows.")
    return result
