"""SQLite persistence for the local job pipeline."""

import sqlite3
import json
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import normalize_job_identity, normalize_text
from joborchestrator.ranking.schemas import RankingResult
from joborchestrator.ranking.serialization import result_to_dict
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.paths import DB_PATH
from joborchestrator.storage import db_connection
from joborchestrator.storage import operations_repository, settings_repository, skill_catalog_repository

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
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        cursor = conn.execute(
            """INSERT INTO company_sources
               (provider, company_name, company_ref, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, company_ref) DO UPDATE SET
                   company_name = excluded.company_name,
                   enabled = excluded.enabled,
                   updated_at = excluded.updated_at""",
            (provider, company_name, company_ref, int(enabled), now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM company_sources WHERE provider = ? AND company_ref = ?",
            (provider, company_ref),
        ).fetchone()
        return int(row["id"] if row else cursor.lastrowid)
    finally:
        conn.close()


def list_company_sources(enabled_only: bool = False) -> pd.DataFrame:
    conn = _conn()
    try:
        query = "SELECT * FROM company_sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY enabled DESC, company_name ASC"
        return _read_sql_query(query, conn)
    finally:
        conn.close()


def update_company_source(
    source_id: int,
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE company_sources
               SET provider = ?, company_name = ?, company_ref = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (provider, company_name, company_ref, int(enabled), now, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_source_scan_state(source_id: int, status: str, error: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE company_sources
               SET last_scan_at = ?, last_scan_status = ?, last_scan_error = ?, updated_at = ?
               WHERE id = ?""",
            (now, status, error, now, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_job_posting(job: JobPosting, seen_at: str | None = None) -> str:
    now = seen_at or datetime.now().isoformat(timespec="seconds")
    raw_payload = json.dumps(job.raw_payload, ensure_ascii=False, sort_keys=True)
    data_quality_flags = json.dumps(job.data_quality_flags or [], ensure_ascii=False)
    identity_key = normalize_job_identity(job.title, job.company, job.location)
    soft_identity_key = job.soft_identity_key or identity_key
    repost_key = job.repost_key or _compute_backfill_repost_key(
        job.title,
        job.company,
        job.location,
        job.apply_url or job.url,
    )
    scraped_at = job.scraped_at or now
    posted_at_raw = job.posted_at_raw or job.posted_at
    posted_at_confidence = job.posted_at_confidence or ("low" if job.source == "linkedin_scraper" else "medium")
    conn = _conn()
    try:
        existing = conn.execute(
            """SELECT id, first_seen_at, times_seen, content_hash, status
               FROM job_postings
               WHERE source = ? AND company = ? AND external_id = ?""",
            (job.source, job.company, job.external_id),
        ).fetchone()

        if existing is None:
            status = "new"
            conn.execute(
                """INSERT INTO job_postings (
                       external_id, source, company, title, location, workplace_type, department,
                       url, apply_url, description_html, description_text, salary_min, salary_max,
                       salary_currency, posted_at, first_seen_at, last_seen_at, times_seen,
                       is_active, content_hash, raw_payload, status, pipeline_status,
                       parse_confidence, data_quality_flags, scraped_at, posted_at_raw,
                       posted_at_estimated, posted_at_confidence, repost_key, soft_identity_key,
                       identity_key
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.external_id,
                    job.source,
                    job.company,
                    job.title,
                    job.location,
                    job.workplace_type,
                    job.department,
                    job.url,
                    job.apply_url,
                    job.description_html,
                    job.description_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.posted_at,
                    now,
                    now,
                    job.content_hash,
                    raw_payload,
                    status,
                    None,
                    job.parse_confidence,
                    data_quality_flags,
                    scraped_at,
                    posted_at_raw,
                    job.posted_at_estimated,
                    posted_at_confidence,
                    repost_key,
                    soft_identity_key,
                    identity_key,
                ),
            )
        else:
            status = "updated" if existing["content_hash"] != job.content_hash else "seen"
            conn.execute(
                """UPDATE job_postings SET
                       title = ?, location = ?, workplace_type = ?, department = ?,
                       url = ?, apply_url = ?, description_html = ?, description_text = ?,
                       salary_min = ?, salary_max = ?, salary_currency = ?, posted_at = ?,
                       last_seen_at = ?, times_seen = times_seen + 1, is_active = 1,
                       content_hash = ?, raw_payload = ?, status = ?, parse_confidence = ?,
                       data_quality_flags = ?, scraped_at = COALESCE(scraped_at, ?),
                       posted_at_raw = ?, posted_at_estimated = ?, posted_at_confidence = ?,
                       repost_key = ?, soft_identity_key = ?, identity_key = ?
                   WHERE source = ? AND company = ? AND external_id = ?""",
                (
                    job.title,
                    job.location,
                    job.workplace_type,
                    job.department,
                    job.url,
                    job.apply_url,
                    job.description_html,
                    job.description_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.posted_at,
                    now,
                    job.content_hash,
                    raw_payload,
                    status,
                    job.parse_confidence,
                    data_quality_flags,
                    scraped_at,
                    posted_at_raw,
                    job.posted_at_estimated,
                    posted_at_confidence,
                    repost_key,
                    soft_identity_key,
                    identity_key,
                    job.source,
                    job.company,
                    job.external_id,
                ),
            )
        conn.commit()
        return status
    finally:
        conn.close()


def upsert_job_postings(jobs: list[JobPosting], seen_at: str | None = None) -> dict[str, list[JobPosting]]:
    buckets = {"new": [], "updated": [], "seen": []}
    for job in jobs:
        status = upsert_job_posting(job, seen_at=seen_at)
        job.status = status
        buckets.setdefault(status, []).append(job)
    return buckets


def mark_jobs_inactive_for_source(source: str, company: str, active_external_ids: set[str]) -> int:
    if not active_external_ids:
        return 0
    placeholders = ",".join("?" for _ in active_external_ids)
    conn = _conn()
    try:
        cursor = conn.execute(
            f"""UPDATE job_postings
                SET is_active = 0
                WHERE source = ? AND company = ? AND external_id NOT IN ({placeholders})""",
            [source, company, *active_external_ids],
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


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
    conn = _conn()
    try:
        cursor = conn.execute(
            """INSERT INTO scan_events (
                   source_id, provider, company_name, company_ref, started_at, finished_at,
                   status, found_count, new_count, updated_count, unchanged_count, error, duration_seconds
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
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
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def count_job_postings(statuses: list[str] | None = None) -> int:
    conn = _conn()
    try:
        params: list[object] = []
        query = "SELECT COUNT(*) AS count FROM job_postings"
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        row = conn.execute(query, params).fetchone()
        return int(row["count"] if row else 0)
    finally:
        conn.close()


def get_job_postings(statuses: list[str] | None = None, limit: int | None = 200) -> pd.DataFrame:
    conn = _conn()
    try:
        params: list[object] = []
        query = "SELECT * FROM job_postings"
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY last_seen_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return _read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_job_posting(job_id: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job_status(job_id: int, status: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE job_postings SET pipeline_status = ? WHERE id = ?", (status, job_id))
        conn.commit()
    finally:
        conn.close()


def update_job_application_materials(
    job_id: int,
    *,
    pipeline_status: str | None = None,
    recruiter_message: str | None = None,
    cover_letter: str | None = None,
    ats_cv_text: str | None = None,
    autofill_notes: str | None = None,
) -> None:
    conn = _conn()
    try:
        conn.execute(
            """UPDATE job_postings SET
                   pipeline_status = COALESCE(?, pipeline_status),
                   recruiter_message = COALESCE(?, recruiter_message),
                   cover_letter = COALESCE(?, cover_letter),
                   ats_cv_text = COALESCE(?, ats_cv_text),
                   autofill_notes = COALESCE(?, autofill_notes)
               WHERE id = ?""",
            (
                pipeline_status,
                recruiter_message,
                cover_letter,
                ats_cv_text,
                autofill_notes,
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_scanner_overview() -> dict:
    conn = _conn()
    try:
        total_jobs = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        new_jobs = conn.execute("SELECT COUNT(*) FROM job_postings WHERE status = 'new'").fetchone()[0]
        updated_jobs = conn.execute("SELECT COUNT(*) FROM job_postings WHERE status = 'updated'").fetchone()[0]
        source_count = conn.execute("SELECT COUNT(*) FROM company_sources WHERE enabled = 1").fetchone()[0]
        recent_errors = conn.execute(
            "SELECT COUNT(*) FROM scan_events WHERE status = 'error' AND started_at >= datetime('now', '-7 day')"
        ).fetchone()[0]
        last_scan = conn.execute("SELECT MAX(finished_at) FROM scan_events").fetchone()[0]
        last_event = conn.execute(
            """SELECT new_count, updated_count, status
               FROM scan_events
               ORDER BY finished_at DESC
               LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    return {
        "total_jobs": total_jobs,
        "new_jobs": new_jobs,
        "updated_jobs": updated_jobs,
        "source_count": source_count,
        "recent_errors": recent_errors,
        "last_scan": last_scan,
        "last_scan_new": int(last_event["new_count"]) if last_event else 0,
        "last_scan_updated": int(last_event["updated_count"]) if last_event else 0,
        "last_scan_status": last_event["status"] if last_event else None,
    }


def get_recent_scan_errors(limit: int = 5) -> pd.DataFrame:
    conn = _conn()
    try:
        return _read_sql_query(
            """SELECT company_name, provider, error, finished_at
               FROM scan_events
               WHERE status = 'error'
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def get_recent_scan_events(limit: int = 20) -> pd.DataFrame:
    conn = _conn()
    try:
        return _read_sql_query(
            """SELECT *
               FROM scan_events
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def save_job_ranking(job_id: int, ranking: RankingResult) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    payload = result_to_dict(ranking)
    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT id, created_at FROM job_rankings WHERE job_id = ? AND ranking_version = ?",
            (job_id, ranking.ranking_version),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE job_rankings SET
                       final_score = ?, decision = ?, confidence = ?, scores_json = ?,
                       evidence_json = ?, reasoning_summary = ?, recommended_application_angle = ?,
                       cv_keywords_to_emphasize_json = ?, cv_keywords_to_avoid_overclaiming_json = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    ranking.final_score,
                    ranking.decision,
                    ranking.confidence,
                    json.dumps(payload["scores"], ensure_ascii=False),
                    json.dumps(payload["evidence"], ensure_ascii=False),
                    ranking.reasoning_summary,
                    ranking.recommended_application_angle,
                    json.dumps(ranking.cv_keywords_to_emphasize, ensure_ascii=False),
                    json.dumps(ranking.cv_keywords_to_avoid_overclaiming, ensure_ascii=False),
                    now,
                    existing["id"],
                ),
            )
            ranking_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """INSERT INTO job_rankings (
                       job_id, final_score, decision, confidence, scores_json, evidence_json,
                       reasoning_summary, recommended_application_angle,
                       cv_keywords_to_emphasize_json, cv_keywords_to_avoid_overclaiming_json,
                       ranking_version, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    ranking.final_score,
                    ranking.decision,
                    ranking.confidence,
                    json.dumps(payload["scores"], ensure_ascii=False),
                    json.dumps(payload["evidence"], ensure_ascii=False),
                    ranking.reasoning_summary,
                    ranking.recommended_application_angle,
                    json.dumps(ranking.cv_keywords_to_emphasize, ensure_ascii=False),
                    json.dumps(ranking.cv_keywords_to_avoid_overclaiming, ensure_ascii=False),
                    ranking.ranking_version,
                    now,
                    now,
                ),
            )
            ranking_id = int(cursor.lastrowid)
        _update_job_posting_ranking_signals(conn, job_id, ranking)
        conn.commit()
        return ranking_id
    finally:
        conn.close()


def delete_job_rankings(ranking_version: str | None = None) -> int:
    conn = _conn()
    try:
        if ranking_version:
            cursor = conn.execute("DELETE FROM job_rankings WHERE ranking_version = ?", (ranking_version,))
        else:
            cursor = conn.execute("DELETE FROM job_rankings")
        deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_postings)").fetchall()}
        reset_columns = [
            "speed_signal",
            "role_viable",
            "duplicate_of_job_id",
            "application_effort_signal",
            "data_quality_signal",
            "source_reliability_signal",
        ]
        assignments = [f"{column} = NULL" for column in reset_columns if column in columns]
        if assignments:
            conn.execute(f"UPDATE job_postings SET {', '.join(assignments)}")
        conn.commit()
        return deleted
    finally:
        conn.close()


def _update_job_posting_ranking_signals(
    conn: sqlite3.Connection,
    job_id: int,
    ranking: RankingResult,
) -> None:
    role_fit = float(ranking.scores.role_fit)
    requires_llm_review = bool(ranking.evidence.requires_llm_review)
    role_viable = role_fit >= 55 and ranking.decision not in {"SKIP", "AVOID"} and not requires_llm_review
    conn.execute(
        """UPDATE job_postings SET
               speed_signal = ?,
               role_viable = ?,
               application_effort_signal = ?,
               data_quality_signal = ?,
               source_reliability_signal = ?
           WHERE id = ?""",
        (
            ranking.scores.speed_signal,
            int(role_viable),
            ranking.scores.application_effort_signal,
            ranking.scores.data_quality_signal,
            ranking.scores.source_reliability_signal,
            job_id,
        ),
    )


def get_ranked_jobs(
    decisions: list[str] | None = None,
    min_score: int | None = None,
    sources: list[str] | None = None,
    with_red_flags: bool | None = None,
    ranking_version: str = NVIDIA_RANKING_VERSION,
) -> pd.DataFrame:
    conn = _conn()
    try:
        params: list[object] = [ranking_version]
        query = """
            SELECT
                jp.id AS job_id, jp.title, jp.company, jp.location, jp.source, jp.url,
                jp.apply_url, jp.description_text, jp.department, jp.workplace_type,
                jp.first_seen_at, jp.last_seen_at, jp.status AS scan_status, jp.pipeline_status,
                jp.recruiter_message, jp.cover_letter, jp.ats_cv_text, jp.autofill_notes,
                jp.parse_confidence, jp.data_quality_flags,
                jr.final_score, jr.decision, jr.confidence, jr.scores_json, jr.evidence_json,
                jr.reasoning_summary, jr.recommended_application_angle,
                jr.cv_keywords_to_emphasize_json, jr.cv_keywords_to_avoid_overclaiming_json,
                jr.ranking_version, jr.updated_at AS ranked_at
            FROM job_rankings jr
            JOIN job_postings jp ON jp.id = jr.job_id
            WHERE jr.ranking_version = ?
        """
        if decisions:
            placeholders = ",".join("?" for _ in decisions)
            query += f" AND jr.decision IN ({placeholders})"
            params.extend(decisions)
        if min_score is not None:
            query += " AND jr.final_score >= ?"
            params.append(min_score)
        if sources:
            placeholders = ",".join("?" for _ in sources)
            query += f" AND jp.source IN ({placeholders})"
            params.extend(sources)
        if with_red_flags is True:
            query += " AND jr.evidence_json LIKE '%red_flags%' AND jr.evidence_json NOT LIKE '%\"red_flags\": []%'"
        elif with_red_flags is False:
            query += " AND (jr.evidence_json LIKE '%\"red_flags\": []%' OR jr.evidence_json NOT LIKE '%red_flags%')"
        query += """
            ORDER BY
              CASE jr.decision
                WHEN 'APPLY_NOW' THEN 1
                WHEN 'APPLY_WITH_TAILORED_CV' THEN 2
                WHEN 'MAYBE' THEN 3
                WHEN 'SKIP' THEN 4
                WHEN 'AVOID' THEN 5
                ELSE 6
              END,
              jr.final_score DESC
        """
        return _read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_ranking_versions() -> list[str]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT ranking_version FROM job_rankings ORDER BY ranking_version DESC"
        ).fetchall()
        return [row["ranking_version"] for row in rows]
    finally:
        conn.close()


def get_unranked_jobs(ranking_version: str = NVIDIA_RANKING_VERSION, limit: int = 500) -> pd.DataFrame:
    conn = _conn()
    try:
        return _read_sql_query(
            """SELECT jp.*
               FROM job_postings jp
               LEFT JOIN job_rankings jr
                 ON jr.job_id = jp.id AND jr.ranking_version = ?
               WHERE jr.id IS NULL
               ORDER BY jp.last_seen_at DESC
               LIMIT ?""",
            conn,
            params=(ranking_version, limit),
        )
    finally:
        conn.close()


def create_ranking_job(
    *,
    provider: str,
    model: str,
    ranking_version: str,
    job_ids: list[int],
    request_batch_size: int,
    max_concurrency: int,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    unique_job_ids = list(dict.fromkeys(int(job_id) for job_id in job_ids))
    conn = _conn()
    try:
        cursor = conn.execute(
            """INSERT INTO ranking_jobs (
                   provider, model, ranking_version, status, request_batch_size,
                   max_concurrency, total_items, processed_items, saved_items,
                   failed_items, created_at, updated_at
               ) VALUES (?, ?, ?, 'queued', ?, ?, ?, 0, 0, 0, ?, ?)""",
            (
                provider,
                model,
                ranking_version,
                int(request_batch_size),
                int(max_concurrency),
                len(unique_job_ids),
                now,
                now,
            ),
        )
        ranking_job_id = int(cursor.lastrowid)
        conn.executemany(
            """INSERT OR IGNORE INTO ranking_job_items (
                   ranking_job_id, job_posting_id, status, attempts, created_at, updated_at
               ) VALUES (?, ?, 'queued', 0, ?, ?)""",
            [(ranking_job_id, job_id, now, now) for job_id in unique_job_ids],
        )
        conn.commit()
        return ranking_job_id
    finally:
        conn.close()


def list_ranking_jobs(limit: int = 20) -> pd.DataFrame:
    conn = _conn()
    try:
        return _read_sql_query(
            """SELECT *
               FROM ranking_jobs
               ORDER BY created_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def get_ranking_job(ranking_job_id: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM ranking_jobs WHERE id = ?", (ranking_job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_next_ranking_job() -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            """SELECT *
               FROM ranking_jobs
               WHERE status IN ('queued', 'running')
               ORDER BY
                   CASE status WHEN 'running' THEN 1 ELSE 2 END,
                   created_at ASC
               LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def start_ranking_job(ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE ranking_jobs
               SET status = 'running',
                   started_at = COALESCE(started_at, ?),
                   updated_at = ?,
                   error = NULL
               WHERE id = ? AND status IN ('queued', 'running')""",
            (now, now, ranking_job_id),
        )
        conn.commit()
    finally:
        conn.close()


def cancel_ranking_job(ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE ranking_jobs
               SET status = 'cancelled',
                   finished_at = COALESCE(finished_at, ?),
                   updated_at = ?
               WHERE id = ? AND status IN ('queued', 'running')""",
            (now, now, ranking_job_id),
        )
        conn.execute(
            """UPDATE ranking_job_items
               SET status = 'cancelled', updated_at = ?
               WHERE ranking_job_id = ? AND status IN ('queued', 'running')""",
            (now, ranking_job_id),
        )
        conn.commit()
    finally:
        conn.close()


def fail_ranking_job(ranking_job_id: int, error: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE ranking_jobs
               SET status = 'failed',
                   error = ?,
                   finished_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (error[:2000], now, now, ranking_job_id),
        )
        conn.execute(
            """UPDATE ranking_job_items
               SET status = 'failed',
                   error = COALESCE(error, ?),
                   finished_at = COALESCE(finished_at, ?),
                   updated_at = ?
               WHERE ranking_job_id = ? AND status = 'running'""",
            (error[:2000], now, now, ranking_job_id),
        )
        conn.commit()
    finally:
        conn.close()


def complete_ranking_job_if_done(ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        pending = conn.execute(
            """SELECT COUNT(*)
               FROM ranking_job_items
               WHERE ranking_job_id = ? AND status IN ('queued', 'running')""",
            (ranking_job_id,),
        ).fetchone()[0]
        job = conn.execute("SELECT status FROM ranking_jobs WHERE id = ?", (ranking_job_id,)).fetchone()
        if pending == 0 and job is not None and job["status"] == "running":
            conn.execute(
                """UPDATE ranking_jobs
                   SET status = 'completed', finished_at = ?, updated_at = ?
                   WHERE id = ?""",
                (now, now, ranking_job_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_queued_ranking_items(ranking_job_id: int, limit: int = 100) -> pd.DataFrame:
    conn = _conn()
    try:
        return _read_sql_query(
            """SELECT
                   rji.id AS ranking_job_item_id,
                   jp.*
               FROM ranking_job_items rji
               JOIN job_postings jp ON jp.id = rji.job_posting_id
               WHERE rji.ranking_job_id = ? AND rji.status = 'queued'
               ORDER BY rji.id ASC
               LIMIT ?""",
            conn,
            params=(ranking_job_id, limit),
        )
    finally:
        conn.close()


def mark_ranking_items_running(ranking_job_id: int, job_ids: list[int]) -> None:
    if not job_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in job_ids)
    params: list[object] = [now, now, ranking_job_id, *[int(job_id) for job_id in job_ids]]
    conn = _conn()
    try:
        conn.execute(
            f"""UPDATE ranking_job_items
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE ranking_job_id = ?
                  AND job_posting_id IN ({placeholders})
                  AND status = 'queued'""",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def sync_ranking_items_from_rankings(
    ranking_job_id: int,
    ranking_version: str,
    job_ids: list[int] | None = None,
) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        job_filter = ""
        params: list[object] = [ranking_job_id]
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            job_filter = f" AND job_posting_id IN ({placeholders})"
            params.extend(int(job_id) for job_id in job_ids)

        items = conn.execute(
            f"""SELECT job_posting_id
                FROM ranking_job_items
                WHERE ranking_job_id = ?{job_filter}""",
            params,
        ).fetchall()
        item_job_ids = [int(row["job_posting_id"]) for row in items]
        ranked_job_ids: set[int] = set()
        if item_job_ids:
            placeholders = ",".join("?" for _ in item_job_ids)
            ranked_rows = conn.execute(
                f"""SELECT job_id
                    FROM job_rankings
                    WHERE ranking_version = ? AND job_id IN ({placeholders})""",
                [ranking_version, *item_job_ids],
            ).fetchall()
            ranked_job_ids = {int(row["job_id"]) for row in ranked_rows}

        completed_ids = [job_id for job_id in item_job_ids if job_id in ranked_job_ids]
        failed_ids = [job_id for job_id in item_job_ids if job_id not in ranked_job_ids]

        if completed_ids:
            placeholders = ",".join("?" for _ in completed_ids)
            conn.execute(
                f"""UPDATE ranking_job_items
                    SET status = 'completed',
                        error = NULL,
                        finished_at = COALESCE(finished_at, ?),
                        updated_at = ?
                    WHERE ranking_job_id = ? AND job_posting_id IN ({placeholders})""",
                [now, now, ranking_job_id, *completed_ids],
            )
        if failed_ids:
            placeholders = ",".join("?" for _ in failed_ids)
            conn.execute(
                f"""UPDATE ranking_job_items
                    SET status = 'failed',
                        error = COALESCE(error, 'NVIDIA did not save a ranking for this job.'),
                        finished_at = COALESCE(finished_at, ?),
                        updated_at = ?
                    WHERE ranking_job_id = ? AND job_posting_id IN ({placeholders})""",
                [now, now, ranking_job_id, *failed_ids],
            )

        counts = _ranking_job_item_counts(conn, ranking_job_id)
        conn.execute(
            """UPDATE ranking_jobs
               SET processed_items = ?,
                   saved_items = ?,
                   failed_items = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                counts["completed"] + counts["failed"],
                counts["completed"],
                counts["failed"],
                now,
                ranking_job_id,
            ),
        )
        conn.commit()
        return counts
    finally:
        conn.close()


def _ranking_job_item_counts(conn: sqlite3.Connection, ranking_job_id: int) -> dict[str, int]:
    rows = conn.execute(
        """SELECT status, COUNT(*) AS count
           FROM ranking_job_items
           WHERE ranking_job_id = ?
           GROUP BY status""",
        (ranking_job_id,),
    ).fetchall()
    counts = {row["status"]: int(row["count"]) for row in rows}
    return {
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
    }
