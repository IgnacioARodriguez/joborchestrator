"""SQLite persistence for the local job pipeline."""

import sqlite3
import hashlib
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.hiring_contacts import LEGACY_RECRUITER_SOURCE, normalize_linkedin_profile_url
from joborchestrator.scanning.normalization import normalize_job_identity, normalize_text
from joborchestrator.ranking.schemas import RankingResult
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.paths import DB_PATH
from joborchestrator.storage import db_connection
from joborchestrator.storage import (
    jobs_repository,
    applications_repository,
    operations_repository,
    evals_repository,
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
    "materials_provider": "TEXT",
    "materials_model": "TEXT",
    "materials_prompt_versions_json": "TEXT",
    "materials_generated_at": "TEXT",
}
LINKEDIN_ENRICHMENT_COLUMNS = {
    "applicant_count": "INTEGER",
    "applicant_count_raw": "TEXT",
    "recruiter_name": "TEXT",
    "recruiter_profile_url": "TEXT",
    "apply_type": "TEXT",
    "external_apply_url": "TEXT",
}
LLM_EVAL_RUN_COLUMNS = {
    "judge_provider": "TEXT",
    "judge_model": "TEXT",
    "judge_result_json": "TEXT",
}
_SCHEMA_READY = False
_SCHEMA_READY_PATH: str | None = None

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
    applicant_count INTEGER,
    applicant_count_raw TEXT,
    recruiter_name TEXT,
    recruiter_profile_url TEXT,
    apply_type TEXT,
    external_apply_url TEXT,
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

CREATE TABLE IF NOT EXISTS job_hiring_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_posting_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    headline TEXT,
    role TEXT,
    source TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,
    position INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_posting_id, profile_url),
    FOREIGN KEY(job_posting_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_job_hiring_contacts_job ON job_hiring_contacts(job_posting_id, position);
CREATE INDEX IF NOT EXISTS idx_job_hiring_contacts_profile_url ON job_hiring_contacts(profile_url);

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

CREATE TABLE IF NOT EXISTS linkedin_scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    limit_count INTEGER DEFAULT 0,
    resume_from_checkpoint INTEGER DEFAULT 1,
    profile_name TEXT,
    checkpoint_loaded_count INTEGER DEFAULT 0,
    db_seen_ids_count INTEGER DEFAULT 0,
    total_searches INTEGER DEFAULT 0,
    searches_run INTEGER DEFAULT 0,
    pages_checked INTEGER DEFAULT 0,
    visible_jobs INTEGER DEFAULT 0,
    duplicate_visible_jobs INTEGER DEFAULT 0,
    added_jobs INTEGER DEFAULT 0,
    exported_jobs INTEGER DEFAULT 0,
    imported_total INTEGER DEFAULT 0,
    imported_new INTEGER DEFAULT 0,
    imported_updated INTEGER DEFAULT 0,
    imported_seen INTEGER DEFAULT 0,
    inactive_count INTEGER DEFAULT 0,
    stop_reason TEXT,
    error TEXT,
    duration_seconds REAL DEFAULT 0,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(operation_id) REFERENCES operation_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_scan_runs_operation ON linkedin_scan_runs(operation_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_scan_runs_started ON linkedin_scan_runs(started_at);

CREATE TABLE IF NOT EXISTS linkedin_scan_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    keywords TEXT NOT NULL,
    location TEXT NOT NULL,
    role_priority TEXT,
    freshness_window_seconds INTEGER DEFAULT 0,
    page_index INTEGER DEFAULT 0,
    page_start INTEGER DEFAULT 0,
    url TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    visible_count INTEGER DEFAULT 0,
    new_visible_count INTEGER DEFAULT 0,
    duplicate_visible_count INTEGER DEFAULT 0,
    added_count INTEGER DEFAULT 0,
    stop_reason TEXT,
    error TEXT,
    duration_seconds REAL DEFAULT 0,
    visible_jobs_json TEXT,
    added_jobs_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES linkedin_scan_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_scan_pages_run ON linkedin_scan_pages(run_id, page_index);

CREATE TABLE IF NOT EXISTS linkedin_job_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER,
    job_posting_id INTEGER NOT NULL,
    linkedin_external_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    apply_type TEXT,
    external_apply_url TEXT,
    easy_apply_available INTEGER DEFAULT 0,
    applicant_count INTEGER,
    applicant_count_raw TEXT,
    recruiter_name TEXT,
    recruiter_profile_url TEXT,
    hiring_contacts_json TEXT,
    error TEXT,
    duration_seconds REAL DEFAULT 0,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_posting_id),
    FOREIGN KEY(operation_id) REFERENCES operation_runs(id),
    FOREIGN KEY(job_posting_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_job_enrichments_operation ON linkedin_job_enrichments(operation_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_job_enrichments_status ON linkedin_job_enrichments(status, updated_at);

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

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    ats_type TEXT,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    resume_variant_id INTEGER,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES job_postings(id),
    FOREIGN KEY(resume_variant_id) REFERENCES resume_variants(id)
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_application_events_application ON application_events(application_id, event_at);

CREATE TABLE IF NOT EXISTS application_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    application_id INTEGER,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    state TEXT NOT NULL,
    current_step TEXT,
    idempotency_key TEXT NOT NULL,
    browser_session_ref TEXT,
    form_schema_json TEXT,
    mapped_answers_json TEXT,
    unknown_fields_json TEXT,
    validation_errors_json TEXT,
    artifacts_json TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    manual_seconds INTEGER DEFAULT 0,
    total_seconds INTEGER DEFAULT 0,
    user_clicks INTEGER DEFAULT 0,
    fields_detected INTEGER DEFAULT 0,
    fields_autofilled INTEGER DEFAULT 0,
    requires_review INTEGER DEFAULT 1,
    last_error TEXT,
    UNIQUE(job_id, provider, mode, idempotency_key),
    FOREIGN KEY(job_id) REFERENCES job_postings(id),
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_application_sessions_job ON application_sessions(job_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_application_sessions_state ON application_sessions(state, updated_at);

CREATE TABLE IF NOT EXISTS application_session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    event_at TEXT NOT NULL,
    note TEXT,
    payload_json TEXT,
    FOREIGN KEY(session_id) REFERENCES application_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_application_session_events_session ON application_session_events(session_id, event_at);

CREATE TABLE IF NOT EXISTS automation_site_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    username TEXT,
    password_ref TEXT,
    browser_profile_ref TEXT,
    last_login_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, domain, username)
);

CREATE INDEX IF NOT EXISTS idx_automation_site_accounts_domain ON automation_site_accounts(domain, provider);

CREATE TABLE IF NOT EXISTS resume_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    file_ref TEXT,
    base_version TEXT,
    created_at TEXT NOT NULL,
    diff_summary TEXT
);

CREATE TABLE IF NOT EXISTS answer_definitions (
    canonical_key TEXT PRIMARY KEY,
    question_patterns TEXT NOT NULL,
    answer_type TEXT,
    value TEXT,
    source TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    requires_confirmation INTEGER DEFAULT 0,
    last_confirmed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    company TEXT,
    name TEXT,
    role TEXT,
    linkedin_url TEXT,
    source TEXT NOT NULL,
    contacted_at TEXT,
    last_reply_at TEXT,
    FOREIGN KEY(job_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_job_contacts_job ON job_contacts(job_id);
CREATE INDEX IF NOT EXISTS idx_job_contacts_company ON job_contacts(company);

CREATE TABLE IF NOT EXISTS follow_ups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    note TEXT,
    done_at TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_follow_ups_due ON follow_ups(done_at, due_at);

CREATE TABLE IF NOT EXISTS llm_eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    job_id INTEGER,
    ranking_version TEXT,
    provider TEXT,
    model TEXT,
    passed INTEGER NOT NULL,
    score INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    judge_payload_json TEXT,
    judge_provider TEXT,
    judge_model TEXT,
    judge_result_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_llm_eval_runs_case ON llm_eval_runs(case_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_llm_eval_runs_created ON llm_eval_runs(created_at);
"""


def _conn():
    global _SCHEMA_READY, _SCHEMA_READY_PATH
    conn = db_connection.connect(DB_PATH)
    is_cloud = getattr(conn, "is_cloud", False)
    if not is_cloud:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
    current_path = str(DB_PATH)
    if _SCHEMA_READY_PATH != current_path:
        _SCHEMA_READY = False

    if is_cloud and not _SCHEMA_READY and _cloud_schema_ready(conn):
        _SCHEMA_READY = True
        _SCHEMA_READY_PATH = current_path

    if not is_cloud or not _SCHEMA_READY:
        conn.executescript(SCANNER_SCHEMA)
        if not is_cloud and _scanner_migration_needed(conn):
            backup_database("before_speed_ranking_migration")
        _ensure_scanner_columns(conn)
        _ensure_hiring_contacts_schema(conn)
        _ensure_llm_eval_schema(conn)
        skill_catalog_repository.seed_skill_catalog(conn)
        _backfill_speed_ranking_columns(conn)
        _backfill_legacy_hiring_contacts(conn)
        _migrate_pipeline_applications(conn)
        conn.commit()
        _SCHEMA_READY = True
        _SCHEMA_READY_PATH = current_path
    return conn


def _cloud_schema_ready(conn: db_connection.LibsqlConnection) -> bool:
    required_tables = {
        "job_postings",
        "job_rankings",
        "ranking_jobs",
        "operation_runs",
        "applications",
        "application_sessions",
        "application_session_events",
        "linkedin_scan_runs",
        "linkedin_scan_pages",
        "linkedin_job_enrichments",
        "llm_eval_runs",
    }
    placeholders = ",".join("?" for _ in required_tables)
    rows = conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
        tuple(sorted(required_tables)),
    ).fetchall()
    existing = {row["name"] for row in rows}
    if not required_tables.issubset(existing):
        return False
    eval_columns = _table_columns(conn, "llm_eval_runs")
    return set(LLM_EVAL_RUN_COLUMNS).issubset(eval_columns)


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
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup_path


def _ensure_scanner_columns(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "job_postings")
    if "pipeline_status" not in columns:
        conn.execute("ALTER TABLE job_postings ADD COLUMN pipeline_status TEXT")
        columns.add("pipeline_status")
    for column, column_type in {
        **SPEED_RANKING_MIGRATION_COLUMNS,
        **APPLICATION_KIT_COLUMNS,
        **LINKEDIN_ENRICHMENT_COLUMNS,
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE job_postings ADD COLUMN {column} {column_type}")
            columns.add(column)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_repost_key ON job_postings(repost_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_soft_identity ON job_postings(soft_identity_key)")


def _ensure_hiring_contacts_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS job_hiring_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_posting_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            profile_url TEXT NOT NULL,
            headline TEXT,
            role TEXT,
            source TEXT NOT NULL,
            is_primary INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(job_posting_id, profile_url),
            FOREIGN KEY(job_posting_id) REFERENCES job_postings(id)
        )"""
    )
    columns = _table_columns(conn, "job_hiring_contacts")
    for column, column_type in {
        "headline": "TEXT",
        "role": "TEXT",
        "source": "TEXT",
        "is_primary": "INTEGER DEFAULT 0",
        "position": "INTEGER DEFAULT 0",
        "is_active": "INTEGER DEFAULT 1",
        "first_seen_at": "TEXT",
        "last_seen_at": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE job_hiring_contacts ADD COLUMN {column} {column_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_hiring_contacts_job ON job_hiring_contacts(job_posting_id, position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_hiring_contacts_profile_url ON job_hiring_contacts(profile_url)")


def _ensure_llm_eval_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "llm_eval_runs")
    for column, column_type in LLM_EVAL_RUN_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE llm_eval_runs ADD COLUMN {column} {column_type}")
            columns.add(column)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_eval_runs_case ON llm_eval_runs(case_id, artifact_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_eval_runs_created ON llm_eval_runs(created_at)")


def _scanner_migration_needed(conn: sqlite3.Connection) -> bool:
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "job_postings" not in tables:
        return False
    columns = _table_columns(conn, "job_postings")
    expected = {
        "pipeline_status",
        *SPEED_RANKING_MIGRATION_COLUMNS,
        *APPLICATION_KIT_COLUMNS,
        *LINKEDIN_ENRICHMENT_COLUMNS,
    }
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


def _backfill_legacy_hiring_contacts(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT id, recruiter_name, recruiter_profile_url, first_seen_at, last_seen_at
           FROM job_postings
           WHERE recruiter_profile_url IS NOT NULL
             AND TRIM(recruiter_profile_url) != ''"""
    ).fetchall()
    for row in rows:
        profile_url = normalize_linkedin_profile_url(row["recruiter_profile_url"])
        name = (row["recruiter_name"] or "").strip()
        if not profile_url or not name:
            continue
        conn.execute(
            """INSERT INTO job_hiring_contacts (
                   job_posting_id, name, profile_url, headline, role, source,
                   is_primary, position, is_active, first_seen_at, last_seen_at,
                   created_at, updated_at
               ) VALUES (?, ?, ?, NULL, NULL, ?, 1, 0, 1, ?, ?, ?, ?)
               ON CONFLICT(job_posting_id, profile_url) DO UPDATE SET
                   name = excluded.name,
                   is_primary = 1,
                   position = 0,
                   is_active = 1,
                   last_seen_at = excluded.last_seen_at,
                   updated_at = excluded.updated_at""",
            (
                row["id"],
                name,
                profile_url,
                LEGACY_RECRUITER_SOURCE,
                row["first_seen_at"] or now,
                row["last_seen_at"] or now,
                now,
                now,
            ),
        )


def _migrate_pipeline_applications(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "job_postings")
    if "pipeline_status" not in columns:
        return
    rows = conn.execute(
        """SELECT id, pipeline_status, first_seen_at, last_seen_at
           FROM job_postings
           WHERE pipeline_status IN ('applied', 'opened')"""
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            "SELECT id FROM applications WHERE job_id = ? ORDER BY id LIMIT 1",
            (row["id"],),
        ).fetchone()
        if existing:
            application_id = existing["id"]
        else:
            status = "submitted" if row["pipeline_status"] == "applied" else "preparing"
            submitted_at = row["last_seen_at"] if row["pipeline_status"] == "applied" else None
            cursor = conn.execute(
                """INSERT INTO applications (
                       job_id, ats_type, status, channel, resume_variant_id,
                       created_at, submitted_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    None,
                    status,
                    "portal",
                    None,
                    row["first_seen_at"] or row["last_seen_at"] or datetime.now().isoformat(timespec="seconds"),
                    submitted_at,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            application_id = _last_insert_id(conn, cursor)
        event_type = "submitted" if row["pipeline_status"] == "applied" else "opened"
        event_exists = conn.execute(
            "SELECT 1 FROM application_events WHERE application_id = ? AND event_type = ? LIMIT 1",
            (application_id, event_type),
        ).fetchone()
        if not event_exists:
            conn.execute(
                """INSERT INTO application_events (application_id, event_type, event_at, note)
                   VALUES (?, ?, ?, ?)""",
                (
                    application_id,
                    event_type,
                    row["last_seen_at"] or row["first_seen_at"] or datetime.now().isoformat(timespec="seconds"),
                    "Migrated from job_postings.pipeline_status.",
                ),
            )
        replacement = "ready_to_apply" if row["pipeline_status"] == "applied" else "new"
        conn.execute("UPDATE job_postings SET pipeline_status = ? WHERE id = ?", (replacement, row["id"]))


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


def get_active_operation(operation_type: str) -> dict | None:
    return operations_repository.get_active_operation(_conn, operation_type)


def list_operations(limit: int = 20) -> list[dict]:
    return operations_repository.list_operations(_conn, limit)


def claim_next_operation(worker_id: str, operation_types: list[str] | None = None) -> dict | None:
    return operations_repository.claim_next_operation(_conn, worker_id, operation_types)


def requeue_stale_operations(operation_types: list[str] | None = None, stale_seconds: int = 3600) -> int:
    return operations_repository.requeue_stale_operations(_conn, operation_types, stale_seconds)


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


def get_recent_external_ids_for_source(source: str, freshness_window_seconds: int) -> set[str]:
    return jobs_repository.get_recent_external_ids_for_source(_conn, source, freshness_window_seconds)


def mark_jobs_inactive_by_last_seen(source: str, freshness_window_seconds: int) -> int:
    return jobs_repository.mark_jobs_inactive_by_last_seen(_conn, source, freshness_window_seconds)


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


def create_linkedin_scan_run(
    *,
    operation_id: int | None,
    started_at: str,
    limit_count: int,
    resume_from_checkpoint: bool,
    profile_name: str | None,
    checkpoint_loaded_count: int,
    db_seen_ids_count: int,
    total_searches: int,
    summary: dict,
) -> int:
    return jobs_repository.create_linkedin_scan_run(
        _conn,
        operation_id=operation_id,
        started_at=started_at,
        limit_count=limit_count,
        resume_from_checkpoint=resume_from_checkpoint,
        profile_name=profile_name,
        checkpoint_loaded_count=checkpoint_loaded_count,
        db_seen_ids_count=db_seen_ids_count,
        total_searches=total_searches,
        summary=summary,
    )


def update_linkedin_scan_run(run_id: int, **kwargs) -> None:
    jobs_repository.update_linkedin_scan_run(_conn, run_id, **kwargs)


def record_linkedin_scan_page(**kwargs) -> int:
    return jobs_repository.record_linkedin_scan_page(_conn, **kwargs)


def count_job_postings(statuses: list[str] | None = None) -> int:
    return jobs_repository.count_job_postings(_conn, statuses)


def get_job_postings(statuses: list[str] | None = None, limit: int | None = 200) -> pd.DataFrame:
    return jobs_repository.get_job_postings(_conn, _read_sql_query, statuses, limit)


def get_apply_queue_job_postings(
    ranking_version: str | None,
    freshness: str,
    limit: int,
    offset: int,
) -> pd.DataFrame:
    return jobs_repository.get_apply_queue_job_postings(_conn, _read_sql_query, ranking_version, freshness, limit, offset)


def count_apply_queue_job_postings(freshness: str) -> int:
    return jobs_repository.count_apply_queue_job_postings(_conn, freshness)


def count_job_freshness_buckets() -> dict[str, int]:
    return jobs_repository.count_job_freshness_buckets(_conn)


def get_job_posting(job_id: int) -> dict | None:
    return jobs_repository.get_job_posting(_conn, job_id)


def get_linkedin_enrichment_candidates(
    *,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    decisions: list[str] | None = None,
    limit: int = 25,
    job_ids: list[int] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    return jobs_repository.get_linkedin_enrichment_candidates(
        _conn,
        _read_sql_query,
        ranking_version=ranking_version,
        decisions=decisions or ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"],
        limit=limit,
        job_ids=job_ids,
        force=force,
    )


def upsert_linkedin_job_enrichment(**kwargs) -> None:
    jobs_repository.upsert_linkedin_job_enrichment(_conn, **kwargs)


def get_recent_linkedin_job_enrichments(limit: int = 50) -> pd.DataFrame:
    return jobs_repository.get_recent_linkedin_job_enrichments(_conn, _read_sql_query, limit)


def list_job_hiring_contacts(job_id: int | None = None) -> list[dict]:
    return jobs_repository.list_job_hiring_contacts(_conn, job_id)


def update_job_status(job_id: int, status: str) -> None:
    jobs_repository.update_job_status(_conn, job_id, status)


def create_application(payload: dict) -> dict:
    return applications_repository.create_application(_conn, payload)


def list_applications() -> list[dict]:
    return applications_repository.list_applications(_conn, _read_sql_query)


def get_application(application_id: int) -> dict | None:
    return applications_repository.get_application(_conn, application_id)


def update_application(application_id: int, payload: dict) -> dict | None:
    return applications_repository.update_application(_conn, application_id, payload)


def create_application_event(application_id: int, payload: dict) -> dict:
    return applications_repository.create_application_event(_conn, application_id, payload)


def record_job_opened(job_id: int) -> dict:
    return applications_repository.record_job_opened(_conn, job_id)


def create_resume_variant(payload: dict) -> dict:
    return applications_repository.create_resume_variant(_conn, payload)


def list_resume_variants() -> list[dict]:
    return applications_repository.list_resume_variants(_conn, _read_sql_query)


def register_generated_resume_variant(job_id: int, label: str, ats_cv_text: str) -> dict:
    return applications_repository.register_generated_resume_variant(_conn, job_id, label, ats_cv_text)


def upsert_answer_definition(payload: dict) -> dict:
    return applications_repository.upsert_answer_definition(_conn, payload)


def list_answer_definitions() -> list[dict]:
    return applications_repository.list_answer_definitions(_conn, _read_sql_query)


def create_contact(payload: dict) -> dict:
    return applications_repository.create_contact(_conn, payload)


def list_contacts() -> list[dict]:
    return applications_repository.list_contacts(_conn, _read_sql_query)


def create_follow_up(payload: dict) -> dict:
    return applications_repository.create_follow_up(_conn, payload)


def list_follow_ups() -> list[dict]:
    return applications_repository.list_follow_ups(_conn, _read_sql_query)


def create_application_session(payload: dict) -> dict:
    return applications_repository.create_application_session(_conn, payload)


def get_application_session(session_id: int) -> dict | None:
    return applications_repository.get_application_session(_conn, session_id)


def get_latest_application_session_for_job(job_id: int) -> dict | None:
    return applications_repository.get_latest_application_session_for_job(_conn, job_id)


def transition_application_session(session_id: int, state: str, payload: dict | None = None) -> dict:
    return applications_repository.transition_application_session(_conn, session_id, state, payload or {})


def list_application_sessions(job_id: int | None = None, limit: int = 100) -> list[dict]:
    return applications_repository.list_application_sessions(_conn, _read_sql_query, job_id, limit)


def upsert_automation_site_account(payload: dict) -> dict:
    return applications_repository.upsert_automation_site_account(_conn, payload)


def get_automation_site_account(provider: str, domain: str, username: str | None = None) -> dict | None:
    return applications_repository.get_automation_site_account(_conn, provider, domain, username)


def list_automation_site_accounts() -> list[dict]:
    return applications_repository.list_automation_site_accounts(_conn, _read_sql_query)


def update_job_application_materials(
    job_id: int,
    *,
    pipeline_status: str | None = None,
    recruiter_message: str | None = None,
    cover_letter: str | None = None,
    ats_cv_text: str | None = None,
    autofill_notes: str | None = None,
    materials_provider: str | None = None,
    materials_model: str | None = None,
    materials_prompt_versions: dict | None = None,
) -> None:
    jobs_repository.update_job_application_materials(
        _conn,
        job_id,
        pipeline_status=pipeline_status,
        recruiter_message=recruiter_message,
        cover_letter=cover_letter,
        ats_cv_text=ats_cv_text,
        autofill_notes=autofill_notes,
        materials_provider=materials_provider,
        materials_model=materials_model,
        materials_prompt_versions=materials_prompt_versions,
    )


def get_scanner_overview() -> dict:
    return jobs_repository.get_scanner_overview(_conn)


def get_recent_scan_errors(limit: int = 5) -> pd.DataFrame:
    return jobs_repository.get_recent_scan_errors(_conn, _read_sql_query, limit)


def get_recent_scan_events(limit: int = 20) -> pd.DataFrame:
    return jobs_repository.get_recent_scan_events(_conn, _read_sql_query, limit)


def get_recent_linkedin_scan_runs(limit: int = 20) -> pd.DataFrame:
    return jobs_repository.get_recent_linkedin_scan_runs(_conn, _read_sql_query, limit)


def get_linkedin_scan_pages(run_id: int, limit: int = 500) -> pd.DataFrame:
    return jobs_repository.get_linkedin_scan_pages(_conn, _read_sql_query, run_id, limit)


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


def get_rankings_for_job_ids(ranking_version: str, job_ids: list[int]) -> pd.DataFrame:
    return rankings_repository.get_rankings_for_job_ids(_conn, _read_sql_query, ranking_version, job_ids)


def get_unranked_jobs(ranking_version: str = NVIDIA_RANKING_VERSION, limit: int = 500) -> pd.DataFrame:
    return rankings_repository.get_unranked_jobs(_conn, _read_sql_query, ranking_version, limit)


def get_jobs_for_post_scan_ranking(
    seen_since: str,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    limit: int = 500,
) -> pd.DataFrame:
    return rankings_repository.get_jobs_for_post_scan_ranking(
        _conn,
        _read_sql_query,
        seen_since=seen_since,
        ranking_version=ranking_version,
        limit=limit,
    )


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


def save_llm_eval_run(payload: dict) -> dict:
    return evals_repository.save_llm_eval_run(_conn, payload)


def list_llm_eval_runs(
    *,
    limit: int = 50,
    case_id: str | None = None,
    artifact_type: str | None = None,
) -> pd.DataFrame:
    return evals_repository.list_llm_eval_runs(
        _conn,
        _read_sql_query,
        limit=limit,
        case_id=case_id,
        artifact_type=artifact_type,
    )
