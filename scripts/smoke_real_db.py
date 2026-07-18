from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smoke_ui import _free_port, _server_env, _start_process, _stop_process_tree, _wait_for_url

DEFAULT_DB_PATH = PROJECT_ROOT / "job_tracker.db"


def run_real_db_smoke(*, db_path: Path | None = None, keep_api: bool = False) -> dict[str, Any]:
    source_db = (db_path or _default_db_path()).resolve()
    if not source_db.exists():
        raise FileNotFoundError(f"Database not found: {source_db}")

    before = _file_fingerprint(source_db)
    readonly_summary = inspect_database_readonly(source_db)
    with tempfile.TemporaryDirectory(prefix="joborchestrator-real-db-smoke-") as tmp_dir:
        copy_path = Path(tmp_dir) / "real_data_copy.db"
        copy_database_readonly(source_db, copy_path)
        api_result = run_api_copy_smoke(copy_path, keep_api=keep_api)

    after = _file_fingerprint(source_db)
    unchanged = before == after
    return {
        "passed": unchanged and api_result["passed"],
        "mode": "real_db_readonly_copy_api",
        "source_database": str(source_db),
        "source_unchanged": unchanged,
        "source_fingerprint": after,
        "readonly_summary": readonly_summary,
        "api_copy": api_result,
    }


def inspect_database_readonly(db_path: Path) -> dict[str, Any]:
    conn = _connect_readonly(db_path)
    try:
        tables = _tables(conn)
        counts = {
            table: _count_rows(conn, table)
            for table in [
                "job_postings",
                "job_rankings",
                "applications",
                "operation_runs",
                "ranking_jobs",
                "scan_events",
                "company_sources",
                "app_settings",
            ]
            if table in tables
        }
        ranking_versions = []
        if "job_rankings" in tables:
            rows = conn.execute(
                "SELECT DISTINCT ranking_version FROM job_rankings ORDER BY ranking_version DESC LIMIT 10"
            ).fetchall()
            ranking_versions = [row["ranking_version"] for row in rows]
        profile_present = False
        if "app_settings" in tables:
            row = conn.execute("SELECT value_json FROM app_settings WHERE key = 'candidate_profile'").fetchone()
            profile_present = bool(row and row["value_json"])
        latest_job = None
        if "job_postings" in tables and counts.get("job_postings", 0) > 0:
            row = conn.execute(
                """SELECT id, title, company, source, last_seen_at
                   FROM job_postings
                   ORDER BY COALESCE(last_seen_at, first_seen_at, '') DESC, id DESC
                   LIMIT 1"""
            ).fetchone()
            latest_job = dict(row) if row else None
        return {
            "tables_checked": sorted(counts),
            "counts": counts,
            "ranking_versions": ranking_versions,
            "profile_present": profile_present,
            "latest_job": latest_job,
        }
    finally:
        conn.close()


def copy_database_readonly(source_db: Path, target_db: Path) -> None:
    source = _connect_readonly(source_db)
    target = sqlite3.connect(target_db)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def run_api_copy_smoke(db_copy_path: Path, *, keep_api: bool = False) -> dict[str, Any]:
    api_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    with tempfile.TemporaryDirectory(prefix="joborchestrator-real-db-api-") as tmp_dir:
        log_path = Path(tmp_dir) / "api.log"
        env = _server_env(db_copy_path, api_url)
        proc = _start_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "joborchestrator.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            env=env,
            log_path=log_path,
        )
        try:
            _wait_for_url(f"{api_url}/api/health", proc, log_path, label="api")
            endpoints = {
                "health": "/api/health",
                "profile": "/api/profile",
                "jobs": "/api/jobs?limit=10",
                "apply_queue": "/api/apply-queue?limit=10&freshness=all",
                "applications": "/api/applications",
                "ranking_jobs": "/api/ranking/jobs",
                "ops_status": "/api/ops/status",
                "worker_status": "/api/workers/status",
                "sources": "/api/sources",
                "scan_overview": "/api/scans/overview",
            }
            responses = {name: _get_json(api_url + path) for name, path in endpoints.items()}
            return {
                "passed": True,
                "api_url": api_url,
                "endpoints_checked": sorted(responses),
                "jobs_returned": len((responses["jobs"].get("jobs") or [])),
                "apply_queue_returned": len((responses["apply_queue"].get("jobs") or [])),
                "applications_returned": len((responses["applications"].get("applications") or [])),
                "ranking_jobs_returned": len((responses["ranking_jobs"].get("jobs") or [])),
                "sources_returned": len((responses["sources"].get("sources") or [])),
                "ops_summary": responses["ops_status"].get("summary"),
                "db_mode": ((responses["jobs"].get("meta") or {}).get("db_mode")),
            }
        finally:
            if not keep_api:
                _stop_process_tree(proc)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri_path = urllib.parse.quote(db_path.resolve().as_posix(), safe="/:")
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Unsafe table name: {table}")
    return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def _get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8")
            if not (200 <= response.status < 300):
                raise RuntimeError(f"{url} returned HTTP {response.status}: {payload[:500]}")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {body[:500]}") from exc


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def _default_db_path() -> Path:
    configured = os.getenv("JOB_ORCHESTRATOR_DB_PATH")
    return Path(configured) if configured else DEFAULT_DB_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only smoke against the local real database.")
    parser.add_argument("--db-path", type=Path, help="Real SQLite DB path. Defaults to JOB_ORCHESTRATOR_DB_PATH or job_tracker.db.")
    parser.add_argument("--keep-api", action="store_true", help="Leave the API process running against the temporary copy.")
    args = parser.parse_args(argv)

    try:
        result = run_real_db_smoke(db_path=args.db_path, keep_api=args.keep_api)
    except Exception as exc:  # noqa: BLE001 - CLI should print a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
