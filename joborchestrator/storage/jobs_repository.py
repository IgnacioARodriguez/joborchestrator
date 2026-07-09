from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import normalize_job_identity, normalize_text
from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[
    [str, sqlite3.Connection | db_connection.LibsqlConnection, list[object] | tuple[object, ...] | None],
    pd.DataFrame,
]


def add_company_source(
    connect: ConnectionFactory,
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool = True,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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
        return int(row["id"] if row else _last_insert_id(conn, cursor))
    finally:
        conn.close()


def list_company_sources(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, enabled_only: bool = False) -> pd.DataFrame:
    conn = connect()
    try:
        query = "SELECT * FROM company_sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY enabled DESC, company_name ASC"
        return read_sql_query(query, conn, None)
    finally:
        conn.close()


def update_company_source(
    connect: ConnectionFactory,
    source_id: int,
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def update_source_scan_state(connect: ConnectionFactory, source_id: int, status: str, error: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def upsert_job_posting(connect: ConnectionFactory, job: JobPosting, seen_at: str | None = None) -> str:
    now = seen_at or datetime.now().isoformat(timespec="seconds")
    raw_payload = json.dumps(job.raw_payload, ensure_ascii=False, sort_keys=True)
    data_quality_flags = json.dumps(job.data_quality_flags or [], ensure_ascii=False)
    identity_key = normalize_job_identity(job.title, job.company, job.location)
    soft_identity_key = job.soft_identity_key or identity_key
    repost_key = job.repost_key or compute_repost_key(
        job.title,
        job.company,
        job.location,
        job.apply_url or job.url,
    )
    scraped_at = job.scraped_at or now
    posted_at_raw = job.posted_at_raw or job.posted_at
    posted_at_confidence = job.posted_at_confidence or ("low" if job.source == "linkedin_scraper" else "medium")
    conn = connect()
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


def upsert_job_postings(connect: ConnectionFactory, jobs: list[JobPosting], seen_at: str | None = None) -> dict[str, list[JobPosting]]:
    buckets = {"new": [], "updated": [], "seen": []}
    for job in jobs:
        status = upsert_job_posting(connect, job, seen_at=seen_at)
        job.status = status
        buckets.setdefault(status, []).append(job)
    return buckets


def mark_jobs_inactive_for_source(
    connect: ConnectionFactory,
    source: str,
    company: str,
    active_external_ids: set[str],
) -> int:
    if not active_external_ids:
        return 0
    placeholders = ",".join("?" for _ in active_external_ids)
    conn = connect()
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


def get_recent_external_ids_for_source(
    connect: ConnectionFactory,
    source: str,
    freshness_window_seconds: int,
    now: datetime | None = None,
) -> set[str]:
    cutoff = (now or datetime.now()) - timedelta(seconds=int(freshness_window_seconds))
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT external_id
               FROM job_postings
               WHERE source = ? AND last_seen_at >= ?""",
            (source, cutoff.isoformat(timespec="seconds")),
        ).fetchall()
        return {str(row["external_id"]) for row in rows if row["external_id"]}
    finally:
        conn.close()


def mark_jobs_inactive_by_last_seen(
    connect: ConnectionFactory,
    source: str,
    freshness_window_seconds: int,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now()) - timedelta(seconds=int(freshness_window_seconds))
    conn = connect()
    try:
        cursor = conn.execute(
            """UPDATE job_postings
               SET is_active = 0
               WHERE source = ?
                 AND is_active = 1
                 AND last_seen_at < ?""",
            (source, cutoff.isoformat(timespec="seconds")),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def record_scan_event(
    connect: ConnectionFactory,
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
    conn = connect()
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
        return _last_insert_id(conn, cursor)
    finally:
        conn.close()


def count_job_postings(connect: ConnectionFactory, statuses: list[str] | None = None) -> int:
    conn = connect()
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


def get_job_postings(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    statuses: list[str] | None = None,
    limit: int | None = 200,
) -> pd.DataFrame:
    conn = connect()
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
        return read_sql_query(query, conn, params)
    finally:
        conn.close()


def get_job_posting(connect: ConnectionFactory, job_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job_status(connect: ConnectionFactory, job_id: int, status: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE job_postings SET pipeline_status = ? WHERE id = ?", (status, job_id))
        conn.commit()
    finally:
        conn.close()


def update_job_application_materials(
    connect: ConnectionFactory,
    job_id: int,
    *,
    pipeline_status: str | None = None,
    recruiter_message: str | None = None,
    cover_letter: str | None = None,
    ats_cv_text: str | None = None,
    autofill_notes: str | None = None,
) -> None:
    conn = connect()
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


def get_scanner_overview(connect: ConnectionFactory) -> dict:
    conn = connect()
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


def get_recent_scan_errors(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, limit: int = 5) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
            """SELECT company_name, provider, error, finished_at
               FROM scan_events
               WHERE status = 'error'
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            (limit,),
        )
    finally:
        conn.close()


def get_recent_scan_events(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, limit: int = 20) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
            """SELECT *
               FROM scan_events
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            (limit,),
        )
    finally:
        conn.close()


def compute_repost_key(
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


def _last_insert_id(conn: sqlite3.Connection | db_connection.LibsqlConnection, cursor: object) -> int:
    lastrowid = getattr(cursor, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    if not row:
        raise RuntimeError("Could not determine inserted row id.")
    return int(row["id"])
