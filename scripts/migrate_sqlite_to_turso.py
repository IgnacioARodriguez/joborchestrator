from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.storage import db_connection
from joborchestrator.storage import persistence as db

TABLES = [
    "company_sources",
    "job_postings",
    "scan_events",
    "job_rankings",
    "ranking_jobs",
    "ranking_job_items",
    "app_settings",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy local SQLite data to Turso/libSQL.")
    parser.add_argument("--source", default="job_tracker.db", help="Path to local SQLite database.")
    parser.add_argument("--replace", action="store_true", help="Delete destination rows before copying.")
    args = parser.parse_args()

    if not os.getenv("TURSO_DATABASE_URL"):
        raise SystemExit("TURSO_DATABASE_URL is required.")

    source_path = Path(args.source)
    if not source_path.exists():
        raise SystemExit(f"Source database not found: {source_path}")

    db.init_db()
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = db_connection.connect(source_path)
    try:
        if args.replace:
            for table in reversed(TABLES):
                target.execute(f"DELETE FROM {table}")
            target.commit()

        copied = {}
        for table in TABLES:
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                copied[table] = 0
                continue
            columns = rows[0].keys()
            column_sql = ", ".join(columns)
            placeholders = ", ".join("?" for _ in columns)
            sql = f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})"
            target.executemany(sql, [[row[column] for column in columns] for row in rows])
            copied[table] = len(rows)
        target.commit()
    finally:
        source.close()
        target.close()

    for table, count in copied.items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
