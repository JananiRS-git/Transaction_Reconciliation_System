"""Integration tests: CSV -> matching -> database updates (real SQLite, temp file)."""
from .helpers import HEADER, SAMPLE_CSV, TempDbTestCase
from app import reconciler
from app.csv_parser import parse_settlement_csv


def run(conn, csv_text):
    return reconciler.reconcile(conn, parse_settlement_csv(csv_text), "test")


class SampleFileTests(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.report = reconciler.reconcile(self.conn, parse_settlement_csv(SAMPLE_CSV.read_bytes()), "sample")

    def test_row_counts(self):
        s = self.report.summary()
        self.assertEqual((s["rows_total"], s["matched"], s["unmatched"], s["invalid"], s["duplicates"]),
                         (19, 17, 2, 0, 0))
        self.assertEqual((s["matched_by_lifecycle_id"], s["matched_by_fallback"]), (14, 3))

    def test_final_statuses_and_totals(self):
        expected = {
            "TXN001": ("FULLY_SETTLED", 125.99, "2025-08-15"),
            "TXN002": ("REFUNDED", 3.25, "2025-08-15"),
            "TXN003": ("PARTIAL", 35.30, "2025-08-15"),
            "TXN004": ("REFUNDED", 879.99, "2025-08-15"),
            "TXN005": ("FULLY_SETTLED", 234.50, "2025-08-15"),
            "TXN006": ("REFUNDED", 75.00, "2025-08-15"),
            "TXN007": ("OVER_SETTLED", 180.78, "2025-08-15"),
            "TXN008": ("REFUNDED", 1000.00, "2025-08-08"),   # last settlement is the later CREDIT
            "TXN009": ("FULLY_SETTLED", 189.95, "2025-08-15"),
            "TXN010": ("PENDING", 0.0, None),
            "TXN013": ("FULLY_SETTLED", 32.45, "2025-08-15"),
            "TXN014": ("FULLY_SETTLED", 28.90, "2025-08-15"),
            "TXN015": ("NOT_APPLICABLE", 199.99, "2025-08-15"),
            "TXN016": ("NOT_APPLICABLE", 0.0, None),
        }
        for txn_id, (status, total, last) in expected.items():
            with self.subTest(txn=txn_id):
                row = self.txn(txn_id)
                self.assertEqual(row["settlement_status"], status)
                self.assertAlmostEqual(row["total_settled_amount"], total, places=2)
                self.assertEqual(row["last_settlement_date"], last)

    def test_fallback_matching_for_rows_without_lifecycle_id(self):
        by_id = {o.settlement_id: o for o in self.report.outcomes}
        self.assertEqual(by_id["SET014"].transaction_id, "TXN013")
        self.assertEqual(by_id["SET015"].transaction_id, "TXN014")
        self.assertEqual(by_id["SET017"].transaction_id, "TXN015")
        self.assertIn("FAILED", " ".join(by_id["SET017"].warnings))

    def test_unknown_lifecycle_and_unknown_account_are_unmatched(self):
        by_id = {o.settlement_id: o for o in self.report.outcomes}
        self.assertEqual(by_id["SET016"].reason_code, "LIFECYCLE_NOT_FOUND")
        self.assertEqual(by_id["SET018"].reason_code, "NO_MATCH")
        rows = self.conn.execute("SELECT settlement_id FROM unmatched_settlements ORDER BY 1").fetchall()
        self.assertEqual([r[0] for r in rows], ["SET016", "SET018"])

    def test_only_matched_rows_are_in_settlement_history(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM settlement_history").fetchone()[0], 17)

    def test_run_is_recorded(self):
        run_row = self.conn.execute("SELECT * FROM reconciliation_runs").fetchone()
        self.assertEqual((run_row["rows_total"], run_row["matched"], run_row["unmatched"]), (19, 17, 2))


class IdempotencyTests(TempDbTestCase):
    def test_uploading_the_same_file_twice_changes_nothing(self):
        data = SAMPLE_CSV.read_bytes()
        reconciler.reconcile(self.conn, parse_settlement_csv(data), "1st")
        before = [tuple(r) for r in self.conn.execute(
            "SELECT transaction_id, settlement_status, total_settled_amount FROM transactions ORDER BY 1")]
        second = reconciler.reconcile(self.conn, parse_settlement_csv(data), "2nd")
        after = [tuple(r) for r in self.conn.execute(
            "SELECT transaction_id, settlement_status, total_settled_amount FROM transactions ORDER BY 1")]
        self.assertEqual(before, after)
        self.assertEqual(second.summary()["duplicates"], 17)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM settlement_history").fetchone()[0], 17)

    def test_duplicate_id_inside_one_file_is_counted_once(self):
        line = "S1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n"
        report = run(self.conn, HEADER + line + line)
        self.assertEqual((report.summary()["matched"], report.summary()["duplicates"]), (1, 1))
        self.assertEqual(self.txn("TXN001")["total_settled_amount"], 125.99)

    def test_same_id_with_different_amount_is_a_conflict_and_ignored(self):
        run(self.conn, HEADER + "S1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,100.00,DEBIT,USD\n")
        report = run(self.conn, HEADER + "S1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n")
        self.assertEqual(report.summary()["conflicts"], 1)
        self.assertEqual(self.txn("TXN001")["total_settled_amount"], 100.00)


class ScenarioTests(TempDbTestCase):
    def test_scenario_5_missing_lifecycle_id_uses_fallback(self):
        report = run(self.conn, HEADER + "S1,,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n")
        self.assertEqual(report.outcomes[0].outcome, reconciler.MATCHED_FALLBACK)
        self.assertEqual(self.txn("TXN001")["settlement_status"], "FULLY_SETTLED")

    def test_fallback_ignores_case_and_extra_spaces(self):
        run(self.conn, HEADER + 'S1,,acc123,"  amazon.COM ",2025-08-14,2025-08-15,125.99,DEBIT,USD\n')
        self.assertEqual(self.txn("TXN001")["settlement_status"], "FULLY_SETTLED")

    def test_scenario_6_status_transitions_across_uploads(self):
        self.add_transaction("T100", "L100", "AX", "Shop", "2025-08-14", 100.00)
        run(self.conn, HEADER + "A1,L100,AX,Shop,2025-08-14,2025-08-15,50.00,DEBIT,USD\n")
        self.assertEqual(self.txn("T100")["settlement_status"], "PARTIAL")
        self.assertEqual(self.txn("T100")["total_settled_amount"], 50.00)
        run(self.conn, HEADER + "A2,L100,AX,Shop,2025-08-14,2025-08-16,50.00,DEBIT,USD\n")
        self.assertEqual(self.txn("T100")["settlement_status"], "FULLY_SETTLED")
        self.assertEqual(self.txn("T100")["total_settled_amount"], 100.00)
        self.assertEqual(self.txn("T100")["last_settlement_date"], "2025-08-16")

    def test_scenario_7_complex_refund(self):
        self.add_transaction("T101", "L101", "AX", "Shop", "2025-08-14", 100.00)
        run(self.conn, HEADER + "B1,L101,AX,Shop,2025-08-14,2025-08-15,100.00,DEBIT,USD\n"
                                "B2,L101,AX,Shop,2025-08-14,2025-08-16,30.00,CREDIT,USD\n")
        row = self.txn("T101")
        self.assertEqual((row["settlement_status"], row["total_settled_amount"]), ("REFUNDED", 70.00))

    def test_float_precision_does_not_cause_false_over_settlement(self):
        self.add_transaction("T102", "L102", "AX", "Shop", "2025-08-14", 0.30)
        run(self.conn, HEADER + "C1,L102,AX,Shop,2025-08-14,2025-08-15,0.10,DEBIT,USD\n"
                                "C2,L102,AX,Shop,2025-08-14,2025-08-15,0.20,DEBIT,USD\n")
        self.assertEqual(self.txn("T102")["settlement_status"], "FULLY_SETTLED")

    def test_currency_mismatch_is_not_applied(self):
        report = run(self.conn, HEADER + "D1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,EUR\n")
        self.assertEqual(report.outcomes[0].reason_code, "CURRENCY_MISMATCH")
        self.assertEqual(self.txn("TXN001")["settlement_status"], "PENDING")

    def test_ambiguous_fallback_is_not_guessed(self):
        self.add_transaction("T200", "L200", "AX", "Cafe", "2025-08-14", 5.00)
        self.add_transaction("T201", "L201", "AX", "Cafe", "2025-08-14", 5.00)
        report = run(self.conn, HEADER + "E1,,AX,Cafe,2025-08-14,2025-08-15,5.00,DEBIT,USD\n")
        self.assertEqual(report.outcomes[0].reason_code, "AMBIGUOUS")
        self.assertEqual(self.txn("T200")["settlement_status"], "PENDING")

    def test_previously_unmatched_row_is_matched_when_transaction_appears(self):
        csv_text = HEADER + "F1,L300,AX,Late Shop,2025-08-14,2025-08-15,20.00,DEBIT,USD\n"
        self.assertEqual(run(self.conn, csv_text).outcomes[0].outcome, reconciler.UNMATCHED)
        self.add_transaction("T300", "L300", "AX", "Late Shop", "2025-08-14", 20.00)
        self.assertEqual(run(self.conn, csv_text).outcomes[0].outcome, reconciler.MATCHED_LIFECYCLE)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM unmatched_settlements").fetchone()[0], 0)
        self.assertEqual(self.txn("T300")["settlement_status"], "FULLY_SETTLED")

    def test_settlement_before_transaction_date_is_warned_but_applied(self):
        report = run(self.conn, HEADER + "G1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-10,125.99,DEBIT,USD\n")
        self.assertIn("before the transaction date", report.outcomes[0].warnings[0])
        self.assertEqual(self.txn("TXN001")["settlement_status"], "FULLY_SETTLED")

    def test_account_mismatch_on_lifecycle_match_is_warned(self):
        report = run(self.conn, HEADER + "H1,LC001,ACC999,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n")
        self.assertIn("account_id", report.outcomes[0].warnings[0])

    def test_invalid_rows_are_reported_and_good_rows_still_processed(self):
        report = run(self.conn, HEADER
                     + "I1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n"
                     + "I2,LC002,ACC124,Starbucks,2025-08-14,2025-08-15,-4.75,DEBIT,USD\n")
        s = report.summary()
        self.assertEqual((s["matched"], s["invalid"]), (1, 1))
        self.assertEqual(self.txn("TXN002")["settlement_status"], "PENDING")


if __name__ == "__main__":
    import unittest
    unittest.main()
