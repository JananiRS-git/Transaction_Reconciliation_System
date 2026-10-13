# Sample CSV files

Upload these on the **Reconcile** page (or `POST /reconcile`). All of them use only transactions from the exercise data.

| File | What it shows |
|---|---|
| `../settlement_report.csv` | The full report from the exercise PDF (19 rows). |
| `scenario6_part1_partial.csv` then `scenario6_part2_complete.csv` | PDF scenario 6: TXN010 (Netflix, 15.99) goes `PENDING` -> `PARTIAL` (10.00) -> `FULLY_SETTLED` (+5.99). Upload part 1, look at the transaction, then upload part 2. |
| `invalid_rows.csv` | 1 valid row + 6 problem rows: 5 are rejected as invalid (negative amount, bad date, bad type, missing fields, non-numeric amount) and 1 has a currency mismatch (kept in the unmatched list). Shows that bad rows are reported without stopping the run. |
