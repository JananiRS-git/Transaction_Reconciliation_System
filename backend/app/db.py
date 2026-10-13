"""SQLite helpers: connection, schema creation, seeding."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

_TABLES = ("reconciliation_runs", "unmatched_settlements", "settlement_history", "transactions")


def connect(db_path: Path | str) -> sqlite3.Connection:
    # isolation_level=None -> autocommit; transactions are managed explicitly (BEGIN/COMMIT).
    conn = sqlite3.connect(str(db_path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def init_db(db_path: Path | str, reset: bool = False) -> None:
    """Create the schema and seed data. With reset=True everything is dropped first."""
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        if reset:
            for table in _TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
        if not _table_exists(conn, "transactions"):
            conn.executescript(config.SCHEMA_SQL.read_text(encoding="utf-8"))
            conn.executescript(config.SEED_SQL.read_text(encoding="utf-8"))
    finally:
        conn.close()
