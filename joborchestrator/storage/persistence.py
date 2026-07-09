"""SQLite persistence for the local job pipeline."""

import sqlite3
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import normalize_job_identity, normalize_text
from joborchestrator.ranking.schemas import RankingResult
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.paths import DB_PATH
from joborchestrator.storage import db_connection
from joborchestrator.storage import (
    jobs_repository,
    operations_repository,
    ranking_jobs_repository,
    rankings_repository,
    settings_repository,
    skill_catalog_repository,
)

BACKUP_DIR_NAME = "backups"
SPEED_RANKING_MIGRATION_COLUMNS = {
    "parse_confidence": "REAL",
    "data_quality_flags": "TEXT",
    "scraped_at": "TEXT",
    "posted_at_raw": "TEXT",
    "posted_at_estimated": "TEXT",
    "posted_at_confidence": "TEXT",
    "repost_key": "TEXT",
    "soft_identity_key": "TEXT",
    "speed_signal": "REAL",
    "role_viable": "INTEGER",
    "application_effort_signal": "REAL",
    "data_quality_signal": "REAL",
    "source_reliability_signal": "REAL",
}
APPLICATION_KIT_COLUMNS = {
    "recruiter_message": "TEXT",
    "cover_letter": "TEXT",
    "ats_cv_text": "TEXT",
    "autofill_notes": "TEXT",
}
_SCHEMA_READY = False

SCANNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_ref TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_scan_at TEXT,
    last_scan_status TEXT,
    last_scan_error TEXT,
    UNIQUE(provider, company_ref)
);

CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT,
    location TEXT,
    workplace_type TEXT,
    department TEXT,
    url TEXT,
    apply_url TEXT,
    description_html TEXT,
    description_text TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    times_seen INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    content_hash TEXT,
    raw_payload TEXT,
    status TEXT DEFAULT 'seen',
    pipeline_status TEXT,
    parse_confidence REAL,
    data_quality_flags TEXT,
    scraped_at TEXT,
    posted_at_raw TEXT,
    posted_at_estimated TEXT,
    posted_at_confidence TEXT,
    repost_key TEXT,
    soft_identity_key TEXT,
    speed_signal REAL,
    role_viable INTEGER,
    application_effort_signal REAL,
    data_quality_signal REAL,
    source_reliability_signal REAL,
    recruiter_message TEXT,
    cover_letter TEXT,
    ats_cv_text TEXT,
    autofill_notes TEXT,
    identity_key TEXT,
    UNIQUE(source, company, external_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_status ON job_postings(status);
CREATE INDEX IF NOT EXISTS idx_job_postings_last_seen ON job_postings(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_job_postings_identity ON job_postings(identity_key);

CREATE TABLE IF NOT EXISTS scan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    provider TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_ref TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    found_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    unchanged_count INTEGER DEFAULT 0,
    error TEXT,
    duration_seconds REAL DEFAULT 0,
    FOREIGN KEY(source_id) REFERENCES company_sources(id)
);

CREATE TABLE IF NOT EXISTS job_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    final_score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    scores_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    reasoning_summary TEXT,
    recommended_application_angle TEXT,
    cv_keywords_to_emphasize_json TEXT,
    cv_keywords_to_avoid_overclaiming_json TEXT,
    ranking_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, ranking_version),
    FOREIGN KEY(job_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_job_rankings_decision ON job_rankings(decision);
CREATE INDEX IF NOT EXISTS idx_job_rankings_score ON job_rankings(final_score);

CREATE TABLE IF NOT EXISTS ranking_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    ranking_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    request_batch_size INTEGER NOT NULL,
    max_concurrency INTEGER NOT NULL,
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    saved_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ranking_job_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_job_id INTEGER NOT NULL,
    job_posting_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER DEFAULT 0,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(ranking_job_id, job_posting_id),
    FOREIGN KEY(ranking_job_id) REFERENCES ranking_jobs(id),
    FOREIGN KEY(job_posting_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_ranking_jobs_status ON ranking_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ranking_job_items_job_status ON ranking_job_items(ranking_job_id, status);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_message TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0,
    claimed_by TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operation_runs_status ON operation_runs(status, created_at);

CREATE TABLE IF NOT EXISTS skill_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, name)
);

CREATE INDEX IF NOT EXISTS idx_skill_catalog_category ON skill_catalog(category, sort_order, name);
"""


def _conn():
    global _SCHEMA_READY
    conn = db_connection.connect(DB_PATH)
    if not getattr(conn, "is_cloud", False):
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
    if not getattr(conn, "is_cloud", False) or not _SCHEMA_READY:
        conn.executescript(SCANNER_SCHEMA)
        if _scanner_migration_needed(conn):
            backup_database("before_speed_ranking_migration")
        _ensure_scanner_columns(conn)
        skill_catalog_repository.seed_skill_catalog(conn)
        _backfill_speed_ranking_columns(conn)
        conn.commit()
        _SCHEMA_READY = True
    return conn


def backup_database(reason: str = "manual") -> Path | None:
    """Create a timestamped copy of the SQLite database before schema/data migrations."""
    db_path = Path(DB_PATH)
    if not db_path.exists():
        return None

    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason).strip("_") or "backup"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = db_path.parent / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}_{timestamp}_{safe_reason}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _ensure_scanner_columns(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "job_postings")
    if "pipeline_status" not in columns:
        conn.execute("ALTER TABLE job_postings ADD COLUMN pipeline_status TEXT")
        columns.add("pipeline_status")
    for column, column_type in {**SPEED_RANKING_MIGRATION_COLUMNS, **APPLICATION_KIT_COLUMNS}.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE job_postings ADD COLUMN {column} {column_type}")
            columns.add(column)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_repost_key ON job_postings(repost_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_soft_identity ON job_postings(soft_identity_key)")


def _scanner_migration_needed(conn: sqlite3.Connection) -> bool:
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "job_postings" not in tables:
        return False
    columns = _table_columns(conn, "job_postings")
    expected = {"pipeline_status", *SPEED_RANKING_MIGRATION_COLUMNS, *APPLICATION_KIT_COLUMNS}
    if not expected.issubset(columns):
        return True
    row = conn.execute(
        """SELECT 1
           FROM job_postings
           WHERE scraped_at IS NULL
              OR posted_at_raw IS NULL
              OR posted_at_confidence IS NULL
              OR repost_key IS NULL
              OR soft_identity_key IS NULL
           LIMIT 1"""
    ).fetchone()
    return row is not None


def _backfill_speed_ranking_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """SELECT id, source, title, company, location, apply_url, url, posted_at,
                  first_seen_at, identity_key, scraped_at, posted_at_raw,
                  posted_at_confidence, repost_key, soft_identity_key
           FROM job_postings
           WHERE scraped_at IS NULL
              OR posted_at_raw IS NULL
              OR posted_at_confidence IS NULL
              OR repost_key IS NULL
              OR soft_identity_key IS NULL"""
    ).fetchall()
    for row in rows:
        soft_identity_key = row["soft_identity_key"] or row["identity_key"] or normalize_job_identity(
            row["title"],
            row["company"],
            row["location"],
        )
        repost_key = row["repost_key"] or _compute_backfill_repost_key(
            row["title"],
            row["company"],
            row["location"],
            row["apply_url"] or row["url"],
        )
        posted_at_confidence = row["posted_at_confidence"]
        if not posted_at_confidence:
            posted_at_confidence = "low" if row["source"] == "linkedin_scraper" else "medium"

        conn.execute(
            """UPDATE job_postings SET
                   scraped_at = COALESCE(scraped_at, ?),
                   posted_at_raw = COALESCE(posted_at_raw, ?),
                   posted_at_confidence = COALESCE(posted_at_confidence, ?),
                   repost_key = COALESCE(repost_key, ?),
                   soft_identity_key = COALESCE(soft_identity_key, ?)
               WHERE id = ?""",
            (
                row["first_seen_at"],
                row["posted_at"],
                posted_at_confidence,
                repost_key,
                soft_identity_key,
                row["id"],
            ),
        )


def _compute_backfill_repost_key(
    title: str | None,
    company: str | None,
    location: str | None,
    apply_or_source_url: str | None,
) -> str:
    normalized = "|".join(
        [
            normalize_text(title),
            normalize_text(company),
            normalize_text(location),
            normalize_text(apply_or_source_url),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _read_sql_query(
    query: str,
    conn: sqlite3.Connection | db_connection.LibsqlConnection,
    params: list[object] | tuple[object, ...] | None = None,
) -> pd.DataFrame:
    if not getattr(conn, "is_cloud", False):
        return pd.read_sql_query(query, conn, params=params)

    cursor = conn.execute(query, params or ())
    columns = [column[0] for column in cursor.description or []]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def init_db():
    conn = _conn()
    conn.commit()
    conn.close()


def get_app_setting(key: str, fallback: object | None = None) -> object | None:
    return settings_repository.get_app_setting(_conn, key, fallback)


def set_app_setting(key: str, value: object) -> None:
    settings_repository.set_app_setting(_conn, key, value)


def get_candidate_profile_payload() -> dict | None:
    return settings_repository.get_candidate_profile_payload(_conn)


def save_candidate_profile_payload(profile: dict) -> None:
    settings_repository.save_candidate_profile_payload(_conn, profile)


def list_skill_catalog() -> list[dict[str, object]]:
    return skill_catalog_repository.list_skill_catalog(_conn)


def add_skill_catalog_item(category: str, name: str) -> dict[str, object]:
    return skill_catalog_repository.add_skill_catalog_item(_conn, category, name)


def create_operation(operation_type: str, input_payload: dict, progress_message: str | None = None) -> int:
    return operations_repository.create_operation(_conn, operation_type, input_payload, progress_message)


def get_operation(operation_id: int) -> dict | None:
    return operations_repository.get_operation(_conn, operation_id)


def _last_insert_id(conn: sqlite3.Connection | db_connection.LibsqlConnection, cursor: object) -> int:
    lastrowid = getattr(cursor, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    if not row:
        raise RuntimeError("Could not determine inserted row id.")
    return int(row["id"])


def get_latest_operation(operation_type: str | None = None) -> dict | None:
    return operations_repository.get_latest_operation(_conn, operation_type)


def list_operations(limit: int = 20) -> list[dict]:
    return operations_repository.list_operations(_conn, limit)


def claim_next_operation(worker_id: str, operation_types: list[str] | None = None) -> dict | None:
    return operations_repository.claim_next_operation(_conn, worker_id, operation_types)


def update_operation_progress(operation_id: int, message: str) -> None:
    operations_repository.update_operation_progress(_conn, operation_id, message)


def complete_operation(operation_id: int, output_payload: dict, message: str = "Completed.") -> None:
    operations_repository.complete_operation(_conn, operation_id, output_payload, message)


def fail_operation(operation_id: int, error: str, message: str = "Failed.") -> None:
    operations_repository.fail_operation(_conn, operation_id, error, message)


def parse_json_value(value: object, fallback: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback


def add_company_source(
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool = True,
) -> int:
    return jobs_repository.add_company_source(_conn, provider, company_name, company_ref, enabled)


def list_company_sources(enabled_only: bool = False) -> pd.DataFrame:
    return jobs_repository.list_company_sources(_conn, _read_sql_query, enabled_only)


def update_company_source(
    source_id: int,
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool,
) -> None:
    jobs_repository.update_company_source(_conn, source_id, provider, company_name, company_ref, enabled)


def update_source_scan_state(source_id: int, status: str, error: str | None = None) -> None:
    jobs_repository.update_source_scan_state(_conn, source_id, status, error)


def upsert_job_posting(job: JobPosting, seen_at: str | None = None) -> str:
    return jobs_repository.upsert_job_posting(_conn, job, seen_at)


def upsert_job_postings(jobs: list[JobPosting], seen_at: str | None = None) -> dict[str, list[JobPosting]]:
    return jobs_repository.upsert_job_postings(_conn, jobs, seen_at)


def mark_jobs_inactive_for_source(source: str, company: str, active_external_ids: set[str]) -> int:
    return jobs_repository.mark_jobs_inactive_for_source(_conn, source, company, active_external_ids)


def record_scan_event(
    source_id: int | None,
    provider: str,
    company_name: str,
    company_ref: str,
    started_at: str,
    finished_at: str,
    status: str,
    found_count: int,
    new_count: int,
    updated_count: int,
    unchanged_count: int,
    error: str | None,
    duration_seconds: float,
) -> int:
    return jobs_repository.record_scan_event(
        _conn,
        source_id,
        provider,
        company_name,
        company_ref,
        started_at,
        finished_at,
        status,
        found_count,
        new_count,
        updated_count,
        unchanged_count,
        error,
        duration_seconds,
    )


def count_job_postings(statuses: list[str] | None = None) -> int:
    return jobs_repository.count_job_postings(_conn, statuses)


def get_job_postings(statuses: list[str] | None = None, limit: int | None = 200) -> pd.DataFrame:
    return jobs_repository.get_job_postings(_conn, _read_sql_query, statuses, limit)


def get_job_posting(job_id: int) -> dict | None:
    return jobs_repository.get_job_posting(_conn, job_id)


def update_job_status(job_id: int, status: str) -> None:
    jobs_repository.update_job_status(_conn, job_id, status)


def update_job_application_materials(
    job_id: int,
    *,
    pipeline_status: str | None = None,
    recruiter_message: str | None = None,
    cover_letter: str | None = None,
    ats_cv_text: str | None = None,
    autofill_notes: str | None = None,
) -> None:
    jobs_repository.update_job_application_materials(
        _conn,
        job_id,
        pipeline_status=pipeline_status,
        recruiter_message=recruiter_message,
        cover_letter=cover_letter,
        ats_cv_text=ats_cv_text,
        autofill_notes=autofill_notes,
    )


def get_scanner_overview() -> dict:
    return jobs_repository.get_scanner_overview(_conn)


def get_recent_scan_errors(limit: int = 5) -> pd.DataFrame:
    return jobs_repository.get_recent_scan_errors(_conn, _read_sql_query, limit)


def get_recent_scan_events(limit: int = 20) -> pd.DataFrame:
    return jobs_repository.get_recent_scan_events(_conn, _read_sql_query, limit)


def save_job_ranking(job_id: int, ranking: RankingResult) -> int:
    return rankings_repository.save_job_ranking(_conn, job_id, ranking)


def delete_job_rankings(ranking_version: str | None = None) -> int:
    return rankings_repository.delete_job_rankings(_conn, ranking_version)


def get_ranked_jobs(
    decisions: list[str] | None = None,
    min_score: int | None = None,
    sources: list[str] | None = None,
    with_red_flags: bool | None = None,
    ranking_version: str = NVIDIA_RANKING_VERSION,
) -> pd.DataFrame:
    return rankings_repository.get_ranked_jobs(
        _conn,
        _read_sql_query,
        decisions=decisions,
        min_score=min_score,
        sources=sources,
        with_red_flags=with_red_flags,
        ranking_version=ranking_version,
    )


def get_ranking_versions() -> list[str]:
    return rankings_repository.get_ranking_versions(_conn)


def get_unranked_jobs(ranking_version: str = NVIDIA_RANKING_VERSION, limit: int = 500) -> pd.DataFrame:
    return rankings_repository.get_unranked_jobs(_conn, _read_sql_query, ranking_version, limit)


def create_ranking_job(
    *,
    provider: str,
    model: str,
    ranking_version: str,
    job_ids: list[int],
    request_batch_size: int,
    max_concurrency: int,
) -> int:
    return ranking_jobs_repository.create_ranking_job(
        _conn,
        provider=provider,
        model=model,
        ranking_version=ranking_version,
        job_ids=job_ids,
        request_batch_size=request_batch_size,
        max_concurrency=max_concurrency,
    )


def list_ranking_jobs(limit: int = 20) -> pd.DataFrame:
    return ranking_jobs_repository.list_ranking_jobs(_conn, _read_sql_query, limit)


def get_ranking_job(ranking_job_id: int) -> dict | None:
    return ranking_jobs_repository.get_ranking_job(_conn, ranking_job_id)


def get_next_ranking_job() -> dict | None:
    return ranking_jobs_repository.get_next_ranking_job(_conn)


def start_ranking_job(ranking_job_id: int) -> None:
    ranking_jobs_repository.start_ranking_job(_conn, ranking_job_id)


def cancel_ranking_job(ranking_job_id: int) -> None:
    ranking_jobs_repository.cancel_ranking_job(_conn, ranking_job_id)


def fail_ranking_job(ranking_job_id: int, error: str) -> None:
    ranking_jobs_repository.fail_ranking_job(_conn, ranking_job_id, error)


def complete_ranking_job_if_done(ranking_job_id: int) -> None:
    ranking_jobs_repository.complete_ranking_job_if_done(_conn, ranking_job_id)


def get_queued_ranking_items(ranking_job_id: int, limit: int = 100) -> pd.DataFrame:
    return ranking_jobs_repository.get_queued_ranking_items(_conn, _read_sql_query, ranking_job_id, limit)


def requeue_stale_ranking_items(ranking_job_id: int | None = None, stale_seconds: int = 60) -> int:
    return ranking_jobs_repository.requeue_stale_ranking_items(_conn, ranking_job_id, stale_seconds)


def requeue_failed_ranking_items(ranking_job_id: int) -> int:
    return ranking_jobs_repository.requeue_failed_ranking_items(_conn, ranking_job_id)


def mark_ranking_items_running(ranking_job_id: int, job_ids: list[int]) -> None:
    ranking_jobs_repository.mark_ranking_items_running(_conn, ranking_job_id, job_ids)


def sync_ranking_items_from_rankings(
    ranking_job_id: int,
    ranking_version: str,
    job_ids: list[int] | None = None,
    missing_error: str = "NVIDIA did not save a ranking for this job.",
) -> dict[str, int]:
    return ranking_jobs_repository.sync_ranking_items_from_rankings(
        _conn,
        ranking_job_id,
        ranking_version,
        job_ids,
        missing_error,
    )
