"""CSV validation tests."""
import unittest

from .helpers import HEADER, SAMPLE_CSV
from app.csv_parser import CsvFormatError, parse_settlement_csv


def one(line):
    return parse_settlement_csv(HEADER + line + "\n")


class ParserTests(unittest.TestCase):
    def test_bundled_sample_parses_all_19_rows(self):
        result = parse_settlement_csv(SAMPLE_CSV.read_bytes())
        self.assertEqual((len(result.rows), len(result.errors)), (19, 0))

    def test_missing_lifecycle_id_is_allowed(self):
        row = one("S1,,ACC1,Cafe,2025-08-14,2025-08-15,5.00,DEBIT,USD").rows[0]
        self.assertIsNone(row.lifecycle_id)

    def test_missing_lifecycle_id_requires_fallback_fields(self):
        err = one("S1,,,,,2025-08-15,5.00,DEBIT,USD").errors[0]
        self.assertTrue(any("account_id is required" in e for e in err.errors))
        self.assertTrue(any("merchant_name is required" in e for e in err.errors))
        self.assertTrue(any("transaction_date is required" in e for e in err.errors))

    def test_negative_zero_and_text_amounts_rejected(self):
        for bad in ("-5.00", "0", "0.00", "abc", "", "NaN", "Infinity", "$5.00", "1,000.00"):
            with self.subTest(amount=bad):
                result = one(f'S1,LC1,A,M,2025-08-14,2025-08-15,"{bad}",DEBIT,USD')
                self.assertEqual(len(result.errors), 1)

    def test_more_than_two_decimals_rejected(self):
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14,2025-08-15,1.234,DEBIT,USD").errors), 1)

    def test_amount_too_large_rejected(self):
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14,2025-08-15,1000000000.00,DEBIT,USD").errors), 1)

    def test_bad_dates_rejected(self):
        for bad in ("14/08/2025", "2025-13-01", "2025-02-30", "yesterday"):
            with self.subTest(date=bad):
                self.assertEqual(len(one(f"S1,LC1,A,M,{bad},2025-08-15,1.00,DEBIT,USD").errors), 1)

    def test_bad_type_and_currency_rejected(self):
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14,2025-08-15,1.00,REFUND,USD").errors), 1)
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,US").errors), 1)
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,12$").errors), 1)

    def test_type_and_currency_are_normalised(self):
        row = one("S1,LC1,A,M,2025-08-14,2025-08-15,1.00,debit,usd").rows[0]
        self.assertEqual((row.settlement_type, row.currency), ("DEBIT", "USD"))

    def test_bad_row_does_not_stop_good_rows(self):
        result = parse_settlement_csv(HEADER
                                      + "S1,LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,USD\n"
                                      + "S2,LC1,A,M,2025-08-14,2025-08-15,-1,DEBIT,USD\n"
                                      + "S3,LC1,A,M,2025-08-14,2025-08-15,3.00,DEBIT,USD\n")
        self.assertEqual([r.settlement_id for r in result.rows], ["S1", "S3"])
        self.assertEqual(result.errors[0].settlement_id, "S2")
        self.assertEqual(result.errors[0].line, 3)

    def test_missing_settlement_id_rejected(self):
        self.assertEqual(len(one(",LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,USD").errors), 1)

    def test_too_many_and_too_few_columns_rejected(self):
        self.assertEqual(len(one("S1,LC1,A,Shell, Gas,2025-08-14,2025-08-15,1.00,DEBIT,USD").errors), 1)
        self.assertEqual(len(one("S1,LC1,A,M,2025-08-14").errors), 1)

    def test_merchant_whitespace_and_line_breaks_are_collapsed(self):
        row = parse_settlement_csv(HEADER + 'S1,LC1,A,"Shell\n  Gas",2025-08-14,2025-08-15,1.00,DEBIT,USD\n').rows[0]
        self.assertEqual(row.merchant_name, "Shell Gas")

    def test_header_case_spaces_and_bom_are_tolerated(self):
        text = "\ufeff" + HEADER.upper() + "S1,LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,USD\n"
        self.assertEqual(len(parse_settlement_csv(text.encode("utf-8")).rows), 1)

    def test_blank_lines_are_ignored(self):
        text = HEADER + "\nS1,LC1,A,M,2025-08-14,2025-08-15,1.00,DEBIT,USD\n\n\n"
        self.assertEqual(parse_settlement_csv(text).total_rows, 1)

    def test_file_level_errors(self):
        for data in (b"", b"   \n", HEADER, b"\x00\x01\x02binary", b"\xff\xfe\xfa not utf8"):
            with self.subTest(data=data[:12]):
                with self.assertRaises(CsvFormatError):
                    parse_settlement_csv(data)

    def test_missing_column_named_in_error(self):
        with self.assertRaises(CsvFormatError) as ctx:
            parse_settlement_csv("settlement_id,currency\nS1,USD\n")
        self.assertIn("settlement_amount", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
