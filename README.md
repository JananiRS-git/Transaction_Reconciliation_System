# Transaction Reconciliation System

Matches settlement records (from a CSV report) to transactions stored in SQLite, updates each transaction's settlement status, flags problems, and shows everything in a dashboard for finance operations teams.

**Stack:** Python 3 + Flask (REST API) · SQLite · React + Vite (dashboard, no chart library: charts are plain SVG)

---

## Quick start

You need **Python 3.10+** and **Node.js 18+**.

### 1. Backend (terminal 1)

```bash
cd backend
python -m venv .venv
# Windows:   .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The API starts on **http://127.0.0.1:5000**. On first start it creates `database/reconciliation.db` from `database/schema.sql` and `database/seed.sql` (the 14 sample transactions). To rebuild it manually: `python scripts/init_db.py --reset`.

### 2. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The dev server forwards `/api/*` to the backend.

*Optional single-server mode:* run `npm run build` in `frontend/`, then `python run.py` and open http://127.0.0.1:5000 (Flask serves the built app).

### 3. Try it

1. Open **Reconcile** and click **Use the sample report** (or upload `data/settlement_report.csv`).
2. Look at the **Dashboard**, the **Transactions** list, and click a transaction for its history, issues and timeline.
3. Try the files in `data/samples/` (see `data/samples/README.md`), e.g. the two `scenario6_*` files to watch a transaction go `PENDING -> PARTIAL -> FULLY_SETTLED`.
4. **Reconcile -> Reset demo data** restores the original state.

> **"Viewing as of" date.** The 7-day rule needs a reference date. The sample data is from August 2025, so the UI defaults to **15 Aug 2025**; use the picker (or the *Today* link) to change it. The API defaults to today's date and accepts `?as_of=YYYY-MM-DD` on every read/reconcile endpoint (or the `RECON_AS_OF` environment variable).

### Run the tests

```bash
cd backend
python -m unittest discover -s tests -t . -v      # no extra packages needed
# or, if you installed requirements-dev.txt:  pytest
```

80 tests: unit tests for the reconciliation rules and CSV validation, and integration tests for the matching engine and every API endpoint (real SQLite file per test).

---

## Project structure

```
database/            schema.sql, seed.sql  (tables + the 14 sample transactions)
data/                settlement_report.csv (from the exercise) + samples/ (extra test CSVs)
backend/
  app/domain.py      pure business rules: status, issues, timeline (no DB, no Flask)
  app/csv_parser.py  CSV parsing + validation
  app/reconciler.py  matching (lifecycle_id -> fallback), storing, recalculating
  app/service.py     read side: transaction views, dashboard statistics
  app/api.py         REST endpoints          app/main.py   Flask app factory
  scripts/init_db.py create / reset the database
  tests/             unit + integration tests
frontend/src/        React app (pages/, components/, api.js, styles.css)
docs/API.md          endpoint documentation
```

## Architecture overview

* **Separation of concerns.** `domain.py` holds every business rule as pure functions on integer cents, so it is easy to test and has no I/O. `reconciler.py` does the database writes. `service.py` builds read models. `api.py` only translates HTTP to those calls.
* **Money is stored and computed in integer cents** to avoid floating point errors (0.10 + 0.20 is exactly 0.30).
* **Recalculate, never increment.** After new settlements are inserted, each touched transaction's status, net total and last settlement date are rebuilt from `settlement_history`. That makes every run repeatable and the data self-correcting.
* **Idempotent uploads.** `settlement_id` is the key. Re-uploading a file does not double count (identical rows are skipped; a changed row with the same id is reported as a conflict and ignored).
* **One database transaction per run.** If anything fails, nothing is half-applied.
* **Issue flags are computed when read** (they depend on the as-of date), while status and totals are stored on the `transactions` table as the exercise requires.

### Matching strategy

1. **Primary:** the row has a `lifecycle_id` -> find the transaction with that id.
2. **Fallback:** the row has *no* `lifecycle_id` -> match `account_id + merchant_name + transaction_date` (case and extra spaces ignored). Exactly one transaction must match.
3. Anything else goes to **Unmatched settlements** (stored in `unmatched_settlements`, shown on the dashboard) with the reason: unknown lifecycle_id, no matching transaction, several candidates, or currency mismatch.

---

## Status rules: PARTIAL vs REFUNDED

Both statuses mean **net settled < transaction amount**, but the cause is different:

| | **PARTIAL** | **REFUNDED** |
|---|---|---|
| What happened | We collected **less** than we should have | We collected the **full** amount, then **gave some back** |
| Cause | Settlement is incomplete / short | Deliberate refund (a `CREDIT`) |
| Is it a problem? | Yes, money is missing | No, normal business |
| Issue flag | Yellow **warning** | None |
| Counted as outstanding? | Yes (the shortfall) | No |
| Example | Shell Gas: 45.30 owed, only 35.30 debited | Best Buy: 899.99 debited, 20.00 credited back (net 879.99) |

The exercise's own scenarios agree: Scenario 2 ($80 debit only) is a **warning**, while Scenario 3 / 7 ($100 debit + a credit) are **no issues**. A refund must therefore not look like a short settlement.

**Decision order** (first match wins), where `net = debits - credits`:

1. Transaction is not `COMPLETED` (FAILED, DECLINED) -> `NOT_APPLICABLE`
2. No settlements -> `PENDING`
3. `net == amount` -> `FULLY_SETTLED`
4. `net > amount` -> `OVER_SETTLED` (red, critical)
5. `net < amount` **and** `debits >= amount` **and** at least one credit -> `REFUNDED`
6. `net < amount` otherwise -> `PARTIAL` (yellow, warning)

**Assumption (rule 5).** `REFUNDED` requires the debits to cover the full transaction amount first. The exercise does not spell this out. Example: a $100 transaction with a $50 debit and a $10 credit is still `PARTIAL`, because the shortfall is not explained by a refund; the money simply has not arrived.

**Worked examples from the sample data:**

| Transaction | Debits | Credits | Net | Status | Flag |
|---|---|---|---|---|---|
| TXN003 Shell Gas (45.30) | 35.30 | 0 | 35.30 | PARTIAL | warning |
| TXN004 Best Buy (899.99) | 899.99 | 20.00 | 879.99 | REFUNDED | none |
| TXN002 Starbucks (4.75) | 4.75 | 1.50 | 3.25 | REFUNDED | none |
| TXN006 Target (87.25) | 87.25 | 12.25 | 75.00 | REFUNDED | none |
| TXN008 Apple (1299.99) | 1299.99 | 299.99 | 1000.00 | REFUNDED | none |

These rules live in `backend/app/domain.py::derive_status` and are covered by `tests/test_domain.py` (`PartialVsRefundedTests`).

## Issue detection

| Flag | Condition |
|---|---|
| **Critical** (red) | Net settled > transaction amount |
| **Critical** (red) | No settlement and the transaction is more than 7 days old (as of the chosen date) |
| **Critical** (red) | A settlement exists for a FAILED / DECLINED transaction (added: see assumptions) |
| **Critical** (red) | Net is negative: credits exceed debits (added) |
| **Warning** (yellow) | Net settled < transaction amount and not a refund (`PARTIAL`) |

Each issue has a plain-language description and a recommended action, shown on the transaction detail page.

## Expected result for the exercise data

The 14 transactions and 19 settlement rows from the PDF produce:

| Status | Transactions |
|---|---|
| FULLY_SETTLED (5) | TXN001, TXN005, TXN009, TXN013, TXN014 |
| REFUNDED (4) | TXN002, TXN004, TXN006, TXN008 |
| PARTIAL (1) | TXN003 |
| OVER_SETTLED (1) | TXN007 |
| PENDING (1) | TXN010 |
| NOT_APPLICABLE (2) | TXN015 (but it received a settlement, so it is **critical**), TXN016 |

17 rows are matched (14 by lifecycle_id, 3 by the fallback: SET014, SET015, SET017) and 2 are unmatched (SET016: unknown lifecycle_id LC999; SET018: no such account/merchant/date). Dashboard: 3 critical (TXN007, TXN010, TXN015), 1 warning (TXN003), outstanding amount 25.99, over-settled amount 24.00.

---

## Assumptions

1. **Only the exercise data is used.** `settlement_history` starts empty; the 14 transactions and 19 CSV rows come from the PDF (the PDF's line-wrapped rows were re-joined, e.g. "Shell Gas").
2. **As-of date.** "7 days" is measured from the transaction date to the as-of date. "After 7 days" means *more than* 7 days (day 8 onward).
3. **Explicit lifecycle_id wins.** If a row has a lifecycle_id that does not exist, the fallback is **not** tried (conflicting identifiers should not be guessed at). The row is reported as unmatched.
4. **Ambiguous fallback is not guessed.** If several transactions share account + merchant + date, the row stays unmatched.
5. **Settlements on non-COMPLETED transactions** are stored and flagged critical. The transaction keeps `NOT_APPLICABLE` (it is not eligible to settle) but its `total_settled_amount` shows the money received (SET017 -> TXN015).
6. **Currency must match** the transaction; otherwise the row is not applied (listed as unmatched with reason `CURRENCY_MISMATCH`).
7. **Warnings that do not block** a row: settlement date before the transaction date; account or merchant in the CSV differs from the matched transaction.
8. **`last_settlement_date`** is the latest settlement date of any type (so Apple shows the later credit date).
9. **Settlement rate** = completed transactions with at least one debit / completed transactions. **Average days to settle** = days from transaction date to the first debit.
10. **Outstanding amount** = full amount of PENDING + the shortfall of PARTIAL transactions. Refunds are not outstanding.
11. Extra tables `unmatched_settlements` and `reconciliation_runs` were added to the provided schema; the two provided tables are unchanged.

## Data validation

Handled without crashing; bad rows are reported and good rows still process: empty or binary files, missing columns, bad dates (`15/08/2025`, `2025-02-30`), non-numeric / zero / negative amounts, more than 2 decimals, amounts above DECIMAL(10,2), invalid type (not DEBIT/CREDIT), invalid currency code, missing `settlement_id`, rows with too many/few columns, UTF-8 BOM, blank lines, whitespace or line breaks inside names, duplicates inside one file, files over 5 MB.

## Known limitations / future improvements

* No authentication or user roles.
* Settlements are matched once, at upload time. Previously unmatched rows are retried only if their file is uploaded again (a scheduled retry would be better).
* Corrections require a new `settlement_id`; there is no edit/void flow for an existing settlement.
* Multi-currency is validated (currency must match) but amounts are never converted.
* Transactions are loaded in full for the list and dashboard; for millions of rows this needs SQL aggregation and pagination.
* The 7-day rule uses calendar days with no weekend/holiday calendar.
* The frontend has no automated tests (the backend does).
* Export is CSV only (no PDF).

## Bonus features included

Settlement timeline visualisation, CSV export of the transaction list, search and sortable columns, issue-level filter, status filter from the dashboard chart, as-of date picker.

---

## Pushing to GitHub

```bash
cd transaction-reconciliation
git init
git add .
git commit -m "Transaction reconciliation system"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```
