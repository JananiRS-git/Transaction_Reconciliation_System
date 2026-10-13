"""Create (or recreate) reconciliation.db from database/schema.sql + database/seed.sql.

    python scripts/init_db.py           # create only if missing
    python scripts/init_db.py --reset   # drop everything and start over
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, db  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all tables and reload seed data")
    parser.add_argument("--db", default=str(config.DB_PATH), help="path of the SQLite file")
    args = parser.parse_args()
    db.init_db(args.db, reset=args.reset)
    print(f"Database ready: {args.db}")
