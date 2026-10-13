# API reference

Base URL (local): `http://127.0.0.1:5000`. Every endpoint is also available under the `/api` prefix (used by the React app), e.g. `/api/transactions`.

All responses are JSON. Errors have one shape:

```json
{ "error": { "code": "INVALID_CSV", "message": "Missing required column(s): settlement_amount" } }
```

Read endpoints and `POST /reconcile` accept an optional `as_of=YYYY-MM-DD` query parameter (default: `RECON_AS_OF` env var, else today). It only affects issue flags, because of the "no settlement after 7 days" rule.

---

## POST /reconcile

Process a settlement CSV, store the settlements and update the transactions.

Send the CSV in one of three ways:

| Way | Example |
|---|---|
| Multipart upload (field `file`) | `curl -F file=@data/settlement_report.csv http://127.0.0.1:5000/reconcile` |
| Raw body | `curl -H "Content-Type: text/csv" --data-binary @data/settlement_report.csv http://127.0.0.1:5000/reconcile` |
| Bundled sample | `curl -X POST "http://127.0.0.1:5000/reconcile?use_sample=true"` |

**200 response**

```json
{
  "source": "settlement_report.csv",
  "as_of": "2025-08-15",
  "summary": {
    "rows_total": 19, "matched": 17, "matched_by_lifecycle_id": 14, "matched_by_fallback": 3,
    "unmatched": 2, "duplicates": 0, "conflicts": 0, "invalid": 0, "transactions_updated": 12
  },
  "results": [
    { "line": 2, "settlement_id": "SET001", "outcome": "matched_lifecycle",
      "message": "Matched to TXN001 by lifecycle_id.", "transaction_id": "TXN001",
      "reason_code": null, "warnings": [] }
  ],
  "transactions": [ "...the transactions touched by this run, same shape as GET /transactions items..." ]
}
```

`outcome` is one of `matched_lifecycle`, `matched_fallback`, `unmatched`, `duplicate`, `conflict`, `invalid`.
`reason_code` (for unmatched): `LIFECYCLE_NOT_FOUND`, `NO_MATCH`, `AMBIGUOUS`, `CURRENCY_MISMATCH`.

| Status | Code | When |
|---|---|---|
| 400 | `NO_FILE` | No CSV supplied |
| 400 | `INVALID_CSV` | Empty, binary, no header, missing columns, no data rows |
| 400 | `INVALID_AS_OF` | Bad date |
| 413 | `FILE_TOO_LARGE` | Over 5 MB |

Bad individual rows never cause an error status; they appear in `results` as `invalid`.

---

## GET /transactions

List all transactions with issue flags.

Query parameters (all optional): `status` (`PENDING`, `PARTIAL`, `FULLY_SETTLED`, `OVER_SETTLED`, `REFUNDED`, `NOT_APPLICABLE`), `issue` (`critical`, `warning`, `none`), `q` (search in id, merchant, account, lifecycle id), `as_of`.

```json
{
  "as_of": "2025-08-15", "count": 1,
  "transactions": [{
    "transaction_id": "TXN004", "lifecycle_id": "LC004", "account_id": "ACC126",
    "merchant_name": "Best Buy", "transaction_date": "2025-08-14",
    "transaction_amount": 899.99, "currency": "USD", "status": "COMPLETED",
    "settlement_status": "REFUNDED",
    "total_settled_amount": 879.99, "total_debits": 899.99, "total_credits": 20.0,
    "settlement_count": 2, "last_settlement_date": "2025-08-15",
    "outstanding_amount": 0.0, "over_settled_amount": 0.0, "days_to_settle": 1,
    "issue_flag": "none", "issues": []
  }]
}
```

`issue_flag` is `critical`, `warning` or `none`. Each entry in `issues` has `severity`, `code`, `title`, `detail`, `recommendation`. Invalid `status` / `issue` -> 400.

## GET /transactions/{id}

Everything above plus:

* `settlements`: the settlement history rows (`settlement_id`, `settlement_date`, `settlement_amount`, `settlement_type`, `currency`, `processed_at`, ...)
* `timeline`: chronological events `{date, kind: transaction|debit|credit|deadline, label, amount, running_net}`; `deadline` is added for PENDING transactions with `overdue: true|false`

Unknown id -> 404 `NOT_FOUND`.

## GET /dashboard/summary

```json
{
  "as_of": "2025-08-15",
  "totals": { "transactions": 14, "completed_transactions": 12, "settlements_processed": 19,
              "settlements_matched": 17, "settlements_unmatched": 2 },
  "status_breakdown": { "PENDING": 1, "PARTIAL": 1, "FULLY_SETTLED": 5, "OVER_SETTLED": 1,
                        "REFUNDED": 4, "NOT_APPLICABLE": 2 },
  "issues": { "critical": 3, "warning": 1, "none": 10 },
  "amounts": { "total_transaction_amount": 3121.84, "total_net_settled": 2986.1,
               "outstanding_amount": 25.99, "over_settled_amount": 24.0, "currency": "USD" },
  "performance": { "avg_days_to_settle": 1.0, "settlement_rate": 0.9167, "settled_transactions": 11 },
  "daily_settlements": [ { "date": "2025-08-15", "debits": 2019.85, "credits": 33.75 } ],
  "unmatched_settlements": [ { "settlement_id": "SET016", "reason_code": "LIFECYCLE_NOT_FOUND", "...": "..." } ],
  "last_run": { "run_id": 1, "run_at": "2026-10-12 09:33:35", "source_name": "settlement_report.csv",
                "rows_total": 19, "matched": 17, "unmatched": 2, "duplicates": 0, "invalid": 0 }
}
```

## Helpers

* `GET /health` -> `{"status": "ok"}`
* `POST /reset` -> drops all data and reloads the 14 seed transactions (demo helper).
