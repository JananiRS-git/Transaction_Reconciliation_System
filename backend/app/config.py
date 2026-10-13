"""Central configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = Path(os.environ.get("RECON_DB_PATH", PROJECT_ROOT / "database" / "reconciliation.db"))
SCHEMA_SQL = PROJECT_ROOT / "database" / "schema.sql"
SEED_SQL = PROJECT_ROOT / "database" / "seed.sql"
SAMPLE_CSV = PROJECT_ROOT / "data" / "settlement_report.csv"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# Optional fixed "as-of" date (YYYY-MM-DD) used when a request does not pass ?as_of=
DEFAULT_AS_OF = os.environ.get("RECON_AS_OF") or None

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
