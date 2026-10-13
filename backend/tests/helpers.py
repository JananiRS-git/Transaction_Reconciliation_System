"""Shared test helpers."""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, domain as d  # noqa: E402
from app.csv_parser import parse_settlement_csv  # noqa: E402
from app.main import create_app  # noqa: E402

HEADER = ("settlement_id,lifecycle_id,account_id,merchant_name,transaction_date,"
          "settlement_date,settlement_amount,settlement_type,currency\n")
SAMPLE_CSV = Path(__file__).resolve().parents[2] / "data" / "settlement_report.csv"
AS_OF = date(2025, 8, 15)


def entry(sid, kind, amount, day="2025-08-15"):
    return d.SettlementEntry(sid, kind, d.to_cents(amount), date.fromisoformat(day))


class TempDbTestCase(unittest.TestCase):
    """Each test gets a fresh seeded SQLite file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "test.db")
        db.init_db(self.db_path)
        self.conn = db.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def add_transaction(self, txn_id, lifecycle, account, merchant, day, amount, status="COMPLETED", currency="USD"):
        self.conn.execute(
            "INSERT INTO transactions (transaction_id, lifecycle_id, account_id, merchant_name, transaction_date,"
            " transaction_amount, currency, status) VALUES (?,?,?,?,?,?,?,?)",
            (txn_id, lifecycle, account, merchant, day, amount, currency, status))

    def txn(self, txn_id):
        return self.conn.execute("SELECT * FROM transactions WHERE transaction_id=?", (txn_id,)).fetchone()


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = create_app(db_path=os.path.join(self._tmp.name, "api.db"), default_as_of="2025-08-15")
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()
