-- =============================================================================
-- Transaction Reconciliation System - database schema (SQLite)
-- The first two tables are exactly as specified in the exercise PDF.
-- The last two tables (unmatched_settlements, reconciliation_runs) are small
-- additions that let the dashboard show settlements that could not be matched
-- and the history of reconciliation runs.
-- =============================================================================

CREATE TABLE transactions (
    transaction_id       VARCHAR(50) PRIMARY KEY,
    lifecycle_id         VARCHAR(50),
    account_id           VARCHAR(50) NOT NULL,
    merchant_name        VARCHAR(100) NOT NULL,
    transaction_date     DATE NOT NULL,
    transaction_amount   DECIMAL(10,2) NOT NULL,
    currency             VARCHAR(3) NOT NULL,
    status               VARCHAR(20) NOT NULL,
    settlement_status    VARCHAR(20) DEFAULT 'PENDING',
    total_settled_amount DECIMAL(10,2) DEFAULT 0.00,
    last_settlement_date DATE,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE settlement_history (
    settlement_id     VARCHAR(50) PRIMARY KEY,
    transaction_id    VARCHAR(50),
    lifecycle_id      VARCHAR(50),
    settlement_date   DATE NOT NULL,
    settlement_amount DECIMAL(10,2) NOT NULL,
    settlement_type   VARCHAR(10) NOT NULL,   -- 'DEBIT' or 'CREDIT'
    currency          VARCHAR(3) NOT NULL,
    processed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

-- Settlement rows from a CSV that could not be tied to exactly one transaction.
CREATE TABLE unmatched_settlements (
    settlement_id     VARCHAR(50) PRIMARY KEY,
    lifecycle_id      VARCHAR(50),
    account_id        VARCHAR(50),
    merchant_name     VARCHAR(100),
    transaction_date  DATE,
    settlement_date   DATE NOT NULL,
    settlement_amount DECIMAL(10,2) NOT NULL,
    settlement_type   VARCHAR(10) NOT NULL,
    currency          VARCHAR(3) NOT NULL,
    reason_code       VARCHAR(30) NOT NULL,
    reason            TEXT NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per call to POST /reconcile.
CREATE TABLE reconciliation_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_name   VARCHAR(255),
    rows_total    INTEGER NOT NULL,
    matched       INTEGER NOT NULL,
    unmatched     INTEGER NOT NULL,
    duplicates    INTEGER NOT NULL,
    invalid       INTEGER NOT NULL
);

CREATE INDEX idx_txn_lifecycle ON transactions(lifecycle_id);
CREATE INDEX idx_txn_fallback  ON transactions(transaction_date, account_id);
CREATE INDEX idx_settle_txn    ON settlement_history(transaction_id);
