from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.env import load_local_env
from joborchestrator.storage import db_connection


CORE_TABLES = [
    "job_postings",
    "job_rankings",
    "applications",
    "app_settings",
]

OPTIONAL_TABLES = [
    "operation_runs",
    "ranking_jobs",
    "ranking_job_items",
    "scan_events",
    "company_sources",
    "linkedin_scan_runs",
    "linkedin_scan_pages",
    "llm_eval_runs",
]


def run_turso_db_smoke(
    *,
    min_jobs: int = 1,
    min_rankings: int = 1,
    require_profile: bool = True,
) -> dict[str, Any]:
    load_local_env()
    if db_connection.connection_mode() != "turso":
        raise RuntimeError("TURSO_DATABASE_URL is not configured; refusing to run this smoke against SQLite.")

    conn = db_connection.connect(":memory:")
    try:
        summary = inspect_turso_connection(conn)
    finally:
        conn.close()

    checks = evaluate_turso_summary(
        summary,
        min_jobs=min_jobs,
        min_rankings=min_rankings,
        require_profile=require_profile,
    )
    return {
        "passed": checks["passed"],
        "mode": "turso_readonly",
        "database": _safe_database_identity(),
        "checks": checks,
        "summary": summary,
    }


def inspect_turso_connection(conn: Any) -> dict[str, Any]:
    tables = _tables(conn)
    checked_tables = CORE_TABLES + [table for table in OPTIONAL_TABLES if table in tables]
    counts = {table: _count_rows(conn, table) for table in checked_tables if table in tables}

    ranking_versions: list[Any] = []
    if "job_rankings" in tables:
        ranking_versions = [
            row["ranking_version"]
            for row in conn.execute(
                "SELECT DISTINCT ranking_version FROM job_rankings ORDER BY ranking_version DESC LIMIT 10"
            ).fetchall()
        ]

    ranking_decisions: list[dict[str, Any]] = []
    if "job_rankings" in tables:
        ranking_decisions = [
            {"decision": row["decision"], "count": row["count"]}
            for row in conn.execute(
                "SELECT decision, COUNT(*) AS count FROM job_rankings GROUP BY decision ORDER BY count DESC"
            ).fetchall()
        ]

    ranking_jobs_by_provider: list[dict[str, Any]] = []
    if "ranking_jobs" in tables:
        ranking_jobs_by_provider = [
            {"provider": row["provider"], "model": row["model"], "count": row["count"]}
            for row in conn.execute(
                """SELECT provider, model, COUNT(*) AS count
                   FROM ranking_jobs
                   GROUP BY provider, model
                   ORDER BY count DESC, provider, model"""
            ).fetchall()
        ]

    source_counts: list[dict[str, Any]] = []
    if "job_postings" in tables:
        source_counts = [
            {"source": row["source"], "count": row["count"]}
            for row in conn.execute(
                "SELECT source, COUNT(*) AS count FROM job_postings GROUP BY source ORDER BY count DESC, source"
            ).fetchall()
        ]

    profile_present = False
    if "app_settings" in tables:
        row = conn.execute("SELECT value_json FROM app_settings WHERE key = ?", ("candidate_profile",)).fetchone()
        profile_present = bool(row and row["value_json"])

    latest_job = None
    if "job_postings" in tables and counts.get("job_postings", 0) > 0:
        row = conn.execute(
            """SELECT id, title, company, source, last_seen_at
               FROM job_postings
               ORDER BY COALESCE(last_seen_at, first_seen_at, '') DESC, id DESC
               LIMIT 1"""
        ).fetchone()
        latest_job = _row_dict(row) if row else None

    return {
        "tables_present": sorted(tables),
        "tables_checked": sorted(counts),
        "counts": counts,
        "profile_present": profile_present,
        "ranking_versions": ranking_versions,
        "ranking_decisions": ranking_decisions,
        "ranking_jobs_by_provider": ranking_jobs_by_provider,
        "source_counts": source_counts,
        "latest_job": latest_job,
    }


def evaluate_turso_summary(
    summary: dict[str, Any],
    *,
    min_jobs: int = 1,
    min_rankings: int = 1,
    require_profile: bool = True,
) -> dict[str, Any]:
    counts = summary.get("counts") or {}
    missing_core_tables = [table for table in CORE_TABLES if table not in counts]
    failures: list[str] = []
    warnings: list[str] = []

    if missing_core_tables:
        failures.append(f"Missing core tables: {', '.join(missing_core_tables)}")
    if int(counts.get("job_postings") or 0) < min_jobs:
        failures.append(f"Expected at least {min_jobs} job_postings rows.")
    if int(counts.get("job_rankings") or 0) < min_rankings:
        failures.append(f"Expected at least {min_rankings} job_rankings rows.")
    if require_profile and not summary.get("profile_present"):
        failures.append("Candidate profile is missing from app_settings.")
    if not summary.get("ranking_versions"):
        warnings.append("No ranking versions found.")
    if not summary.get("source_counts"):
        warnings.append("No job source distribution found.")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "thresholds": {
            "min_jobs": min_jobs,
            "min_rankings": min_rankings,
            "require_profile": require_profile,
        },
    }


def _tables(conn: Any) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _count_rows(conn: Any, table: str) -> int:
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Unsafe table name: {table}")
    return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _safe_database_identity() -> dict[str, str | None]:
    url = os.getenv("TURSO_DATABASE_URL")
    if not url:
        return {"host": None, "database": None}
    parsed = urllib.parse.urlparse(url)
    database = parsed.path.strip("/") or None
    return {"host": parsed.hostname, "database": database}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only smoke against the configured Turso database.")
    parser.add_argument("--min-jobs", type=int, default=1, help="Minimum expected job_postings rows.")
    parser.add_argument("--min-rankings", type=int, default=1, help="Minimum expected job_rankings rows.")
    parser.add_argument(
        "--allow-missing-profile",
        action="store_true",
        help="Do not fail if candidate_profile is absent from app_settings.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_turso_db_smoke(
            min_jobs=args.min_jobs,
            min_rankings=args.min_rankings,
            require_profile=not args.allow_missing_profile,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
