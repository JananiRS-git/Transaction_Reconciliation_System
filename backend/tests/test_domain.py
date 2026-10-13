"""Unit tests for the pure business rules (the PDF's 7 sample scenarios + edge cases)."""
import unittest
from datetime import date

from .helpers import entry
from app import domain as d

TXN_DATE = date(2025, 8, 14)


def evaluate(amount, entries, txn_status="COMPLETED", as_of=date(2025, 8, 15)):
    cents = d.to_cents(amount)
    totals = d.summarize(entries)
    status = d.derive_status(txn_status, cents, totals)
    issues = d.detect_issues(txn_status, TXN_DATE, cents, "USD", status, totals, as_of)
    return status, d.issue_flag(issues), totals, issues


class PdfScenarioTests(unittest.TestCase):
    def test_1_perfect_match(self):
        status, flag, *_ = evaluate(100, [entry("S1", "DEBIT", 100)])
        self.assertEqual((status, flag), (d.FULLY_SETTLED, d.NO_ISSUE))

    def test_2_partial_settlement_is_warning(self):
        status, flag, *_ = evaluate(100, [entry("S1", "DEBIT", 80)])
        self.assertEqual((status, flag), (d.PARTIAL, d.WARNING))

    def test_3_debit_plus_credit_refund_is_no_issue(self):
        status, flag, totals, _ = evaluate(100, [entry("S1", "DEBIT", 100), entry("S2", "CREDIT", 20)])
        self.assertEqual(totals.net, 8000)
        self.assertEqual((status, flag), (d.REFUNDED, d.NO_ISSUE))

    def test_4_over_settlement_is_critical(self):
        status, flag, *_ = evaluate(100, [entry("S1", "DEBIT", 120)])
        self.assertEqual((status, flag), (d.OVER_SETTLED, d.CRITICAL))

    def test_6_status_transitions(self):
        s1, f1, *_ = evaluate(100, [])
        s2, f2, *_ = evaluate(100, [entry("S1", "DEBIT", 50)])
        s3, f3, totals, _ = evaluate(100, [entry("S1", "DEBIT", 50), entry("S2", "DEBIT", 50)])
        self.assertEqual([s1, s2, s3], [d.PENDING, d.PARTIAL, d.FULLY_SETTLED])
        self.assertEqual([f1, f2, f3], [d.NO_ISSUE, d.WARNING, d.NO_ISSUE])
        self.assertEqual(totals.net, 10000)

    def test_7_complex_refund(self):
        status, flag, totals, _ = evaluate(100, [entry("S1", "DEBIT", 100), entry("S2", "CREDIT", 30)])
        self.assertEqual(totals.net, 7000)
        self.assertEqual((status, flag), (d.REFUNDED, d.NO_ISSUE))


class PartialVsRefundedTests(unittest.TestCase):
    """The README explains this rule: REFUNDED needs debits >= amount AND a credit."""

    def test_short_debit_with_a_credit_is_still_partial(self):
        status, flag, *_ = evaluate(100, [entry("S1", "DEBIT", 50), entry("S2", "CREDIT", 10)])
        self.assertEqual((status, flag), (d.PARTIAL, d.WARNING))

    def test_full_debit_then_credit_is_refunded(self):
        status, *_ = evaluate(100, [entry("S1", "DEBIT", 100), entry("S2", "CREDIT", 1)])
        self.assertEqual(status, d.REFUNDED)

    def test_debit_only_shortfall_is_partial_not_refunded(self):
        status, *_ = evaluate(45.30, [entry("S1", "DEBIT", 35.30)])
        self.assertEqual(status, d.PARTIAL)

    def test_over_debit_then_credit_back_to_exact_amount_is_fully_settled(self):
        status, flag, *_ = evaluate(100, [entry("S1", "DEBIT", 120), entry("S2", "CREDIT", 20)])
        self.assertEqual((status, flag), (d.FULLY_SETTLED, d.NO_ISSUE))

    def test_fully_reversed_transaction_is_refunded(self):
        status, flag, totals, _ = evaluate(100, [entry("S1", "DEBIT", 100), entry("S2", "CREDIT", 100)])
        self.assertEqual((status, flag, totals.net), (d.REFUNDED, d.NO_ISSUE, 0))

    def test_refunded_money_is_not_outstanding_but_partial_is(self):
        refunded_totals = d.summarize([entry("S1", "DEBIT", 100), entry("S2", "CREDIT", 30)])
        partial_totals = d.summarize([entry("S1", "DEBIT", 80)])
        self.assertEqual(d.outstanding_cents(d.REFUNDED, 10000, refunded_totals), 0)
        self.assertEqual(d.outstanding_cents(d.PARTIAL, 10000, partial_totals), 2000)


class IssueDetectionTests(unittest.TestCase):
    def test_pending_within_seven_days_is_fine(self):
        _, flag, *_ = evaluate(100, [], as_of=date(2025, 8, 21))   # 7 days old
        self.assertEqual(flag, d.NO_ISSUE)

    def test_pending_after_seven_days_is_critical(self):
        _, flag, _, issues = evaluate(100, [], as_of=date(2025, 8, 22))  # 8 days old
        self.assertEqual(flag, d.CRITICAL)
        self.assertEqual(issues[0].code, "NO_SETTLEMENT_OVERDUE")

    def test_future_as_of_before_transaction_date_is_fine(self):
        _, flag, *_ = evaluate(100, [], as_of=date(2025, 8, 1))
        self.assertEqual(flag, d.NO_ISSUE)

    def test_failed_transaction_without_settlement_is_fine(self):
        status, flag, *_ = evaluate(100, [], txn_status="DECLINED", as_of=date(2026, 1, 1))
        self.assertEqual((status, flag), (d.NOT_APPLICABLE, d.NO_ISSUE))

    def test_failed_transaction_with_settlement_is_critical(self):
        status, flag, _, issues = evaluate(100, [entry("S1", "DEBIT", 100)], txn_status="FAILED")
        self.assertEqual((status, flag), (d.NOT_APPLICABLE, d.CRITICAL))
        self.assertEqual(issues[0].code, "SETTLED_NON_COMPLETED")

    def test_credit_without_debit_is_critical_negative_net(self):
        _, flag, _, issues = evaluate(100, [entry("S1", "CREDIT", 10)])
        self.assertEqual(flag, d.CRITICAL)
        self.assertEqual(issues[0].code, "NEGATIVE_NET")

    def test_every_issue_has_a_recommendation(self):
        _, _, _, issues = evaluate(100, [entry("S1", "DEBIT", 120)])
        self.assertTrue(all(i.recommendation for i in issues))


class MoneyTests(unittest.TestCase):
    def test_cents_avoid_float_errors(self):
        total = d.summarize([entry("A", "DEBIT", 0.1), entry("B", "DEBIT", 0.2)]).net
        self.assertEqual(total, d.to_cents(0.3))

    def test_to_cents_rounds_half_up(self):
        self.assertEqual(d.to_cents("1.005"), 101)
        self.assertEqual(d.to_cents(899.99), 89999)

    def test_to_cents_rejects_garbage(self):
        with self.assertRaises(ValueError):
            d.to_cents("abc")


class TimelineTests(unittest.TestCase):
    def test_running_net_and_order(self):
        events = d.build_timeline(TXN_DATE, 10000, "USD",
                                  [entry("S2", "CREDIT", 30, "2025-08-16"), entry("S1", "DEBIT", 100, "2025-08-15")],
                                  d.REFUNDED, date(2025, 8, 20))
        self.assertEqual([e["kind"] for e in events], ["transaction", "debit", "credit"])
        self.assertEqual(events[-1]["running_net"], 70.0)

    def test_pending_transaction_gets_deadline_marker(self):
        events = d.build_timeline(TXN_DATE, 10000, "USD", [], d.PENDING, date(2025, 8, 30))
        self.assertEqual(events[-1]["kind"], "deadline")
        self.assertTrue(events[-1]["overdue"])


if __name__ == "__main__":
    unittest.main()
