"""Integration tests for the REST API (Flask test client + real SQLite file)."""
import io

from .helpers import HEADER, SAMPLE_CSV, ApiTestCase


class ApiTests(ApiTestCase):
    def reconcile_sample(self):
        return self.client.post("/reconcile", data={"file": (io.BytesIO(SAMPLE_CSV.read_bytes()), "report.csv")},
                                content_type="multipart/form-data")

    # --- POST /reconcile -------------------------------------------------
    def test_reconcile_multipart_upload(self):
        r = self.reconcile_sample()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["summary"]["matched"], 17)
        self.assertEqual(body["summary"]["unmatched"], 2)
        self.assertEqual(body["source"], "report.csv")
        self.assertEqual(len(body["results"]), 19)

    def test_reconcile_raw_csv_body(self):
        r = self.client.post("/reconcile", data=HEADER + "S1,LC001,ACC123,Amazon.com,2025-08-14,2025-08-15,125.99,DEBIT,USD\n",
                             content_type="text/csv")
        self.assertEqual(r.get_json()["summary"]["matched"], 1)

    def test_reconcile_use_sample(self):
        r = self.client.post("/reconcile?use_sample=true")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["summary"]["rows_total"], 19)

    def test_reconcile_without_input_is_400(self):
        r = self.client.post("/reconcile")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["code"], "NO_FILE")

    def test_reconcile_bad_files_are_400_with_clear_message(self):
        for payload, expected in ((b"", "empty"), (b"a,b\n1,2\n", "Missing required column"),
                                  (b"\x00\x01binary", "binary")):
            with self.subTest(expected=expected):
                r = self.client.post("/reconcile", data={"file": (io.BytesIO(payload), "x.csv")},
                                     content_type="multipart/form-data")
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.get_json()["error"]["code"], "INVALID_CSV")
                self.assertIn(expected.lower(), r.get_json()["error"]["message"].lower())

    def test_reconcile_file_too_large_is_413(self):
        big = b"x" * (5 * 1024 * 1024 + 10)
        r = self.client.post("/reconcile", data={"file": (io.BytesIO(big), "big.csv")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()["error"]["code"], "FILE_TOO_LARGE")

    def test_reconcile_twice_is_idempotent(self):
        self.reconcile_sample()
        second = self.reconcile_sample().get_json()["summary"]
        self.assertEqual(second["duplicates"], 17)
        summary = self.client.get("/dashboard/summary").get_json()
        self.assertEqual(summary["totals"]["settlements_matched"], 17)

    # --- GET /transactions ----------------------------------------------
    def test_list_before_reconcile_everything_is_pending_or_not_applicable(self):
        body = self.client.get("/transactions").get_json()
        self.assertEqual(body["count"], 14)
        statuses = {t["settlement_status"] for t in body["transactions"]}
        self.assertEqual(statuses, {"PENDING", "NOT_APPLICABLE"})

    def test_list_after_reconcile_has_issue_flags(self):
        self.reconcile_sample()
        txns = {t["transaction_id"]: t for t in self.client.get("/transactions").get_json()["transactions"]}
        self.assertEqual(txns["TXN007"]["issue_flag"], "critical")   # over settled
        self.assertEqual(txns["TXN010"]["issue_flag"], "critical")   # no settlement > 7 days
        self.assertEqual(txns["TXN015"]["issue_flag"], "critical")   # failed txn settled
        self.assertEqual(txns["TXN003"]["issue_flag"], "warning")    # partial
        self.assertEqual(txns["TXN004"]["issue_flag"], "none")       # refunded
        self.assertEqual(txns["TXN016"]["issue_flag"], "none")       # declined, correctly unsettled

    def test_filters(self):
        self.reconcile_sample()
        refunded = self.client.get("/transactions?status=refunded").get_json()
        self.assertEqual(sorted(t["transaction_id"] for t in refunded["transactions"]),
                         ["TXN002", "TXN004", "TXN006", "TXN008"])
        critical = self.client.get("/transactions?issue=critical").get_json()
        self.assertEqual(critical["count"], 3)
        search = self.client.get("/transactions?q=shell").get_json()
        self.assertEqual(sorted(t["transaction_id"] for t in search["transactions"]), ["TXN003", "TXN014"])

    def test_invalid_filters_are_400(self):
        self.assertEqual(self.client.get("/transactions?status=NOPE").status_code, 400)
        self.assertEqual(self.client.get("/transactions?issue=red").status_code, 400)
        self.assertEqual(self.client.get("/transactions?as_of=15-08-2025").status_code, 400)

    def test_as_of_changes_overdue_flag(self):
        early = self.client.get("/transactions/TXN001?as_of=2025-08-16").get_json()
        late = self.client.get("/transactions/TXN001?as_of=2025-08-30").get_json()
        self.assertEqual(early["issue_flag"], "none")
        self.assertEqual(late["issue_flag"], "critical")

    # --- GET /transactions/{id} -----------------------------------------
    def test_detail_has_history_issues_and_timeline(self):
        self.reconcile_sample()
        body = self.client.get("/transactions/TXN004").get_json()
        self.assertEqual(body["settlement_status"], "REFUNDED")
        self.assertEqual([s["settlement_id"] for s in body["settlements"]], ["SET004", "SET005"])
        self.assertEqual(body["total_debits"], 899.99)
        self.assertEqual(body["total_credits"], 20.0)
        self.assertEqual([e["kind"] for e in body["timeline"]], ["transaction", "debit", "credit"])
        walmart = self.client.get("/transactions/TXN007").get_json()
        self.assertEqual(walmart["issues"][0]["code"], "OVER_SETTLED")
        self.assertTrue(walmart["issues"][0]["recommendation"])
        self.assertEqual(walmart["over_settled_amount"], 24.0)

    def test_detail_unknown_id_is_404(self):
        r = self.client.get("/transactions/NOPE")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "NOT_FOUND")

    # --- GET /dashboard/summary -----------------------------------------
    def test_summary_numbers(self):
        self.reconcile_sample()
        s = self.client.get("/dashboard/summary").get_json()
        self.assertEqual(s["totals"], {"transactions": 14, "completed_transactions": 12, "settlements_processed": 19,
                                       "settlements_matched": 17, "settlements_unmatched": 2})
        self.assertEqual(s["status_breakdown"], {"PENDING": 1, "PARTIAL": 1, "FULLY_SETTLED": 5, "OVER_SETTLED": 1,
                                                 "REFUNDED": 4, "NOT_APPLICABLE": 2})
        self.assertEqual(s["issues"], {"critical": 3, "warning": 1, "none": 10})
        self.assertEqual(s["amounts"]["outstanding_amount"], 25.99)     # Netflix 15.99 + Shell shortfall 10.00
        self.assertEqual(s["amounts"]["over_settled_amount"], 24.0)
        self.assertEqual(s["performance"]["avg_days_to_settle"], 1.0)
        self.assertEqual(s["performance"]["settlement_rate"], round(11 / 12, 4))
        self.assertEqual([u["settlement_id"] for u in s["unmatched_settlements"]], ["SET016", "SET018"])
        self.assertEqual(s["last_run"]["rows_total"], 19)

    def test_summary_on_fresh_database(self):
        s = self.client.get("/dashboard/summary").get_json()
        self.assertEqual(s["totals"]["settlements_processed"], 0)
        self.assertIsNone(s["performance"]["avg_days_to_settle"])
        self.assertIsNone(s["last_run"])

    # --- misc -------------------------------------------------------------
    def test_api_prefix_works_too(self):
        self.assertEqual(self.client.get("/api/transactions").status_code, 200)
        self.assertEqual(self.client.get("/api/health").get_json(), {"status": "ok"})

    def test_reset_restores_seed_data(self):
        self.reconcile_sample()
        self.assertEqual(self.client.post("/reset").status_code, 200)
        s = self.client.get("/dashboard/summary").get_json()
        self.assertEqual(s["totals"]["settlements_processed"], 0)
        self.assertEqual(s["totals"]["transactions"], 14)

    def test_unknown_route_returns_json_404(self):
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())


if __name__ == "__main__":
    import unittest
    unittest.main()
