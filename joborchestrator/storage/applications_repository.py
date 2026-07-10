from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Callable

import pandas as pd

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[
    [str, sqlite3.Connection | db_connection.LibsqlConnection, list[object] | tuple[object, ...] | None],
    pd.DataFrame,
]

APPLICATION_STATUSES = {
    "preparing",
    "submitted",
    "recruiter_screen",
    "interview",
    "technical",
    "offer",
    "rejected",
    "withdrawn",
}
APPLICATION_CHANNELS = {"portal", "easy_apply", "referral", "direct_contact"}
APPLICATION_EVENTS = {
    "opened",
    "answer_saved",
    "submitted",
    "recruiter_reply",
    "rejection",
    "interview_scheduled",
    "ghosted",
}
ANSWER_SOURCES = {"approved", "generated"}
ANSWER_SENSITIVITIES = {"public", "preference", "sensitive"}
CONTACT_SOURCES = {"linkedin_scraper", "manual"}


def create_application(connect: ConnectionFactory, payload: dict) -> dict:
    now = _now()
    status = _validated(payload.get("status") or "preparing", APPLICATION_STATUSES, "status")
    channel = _validated(payload.get("channel") or "portal", APPLICATION_CHANNELS, "channel")
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO applications (
                   job_id, ats_type, status, channel, resume_variant_id,
                   created_at, submitted_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["job_id"],
                payload.get("ats_type"),
                status,
                channel,
                payload.get("resume_variant_id"),
                payload.get("created_at") or now,
                payload.get("submitted_at"),
                now,
            ),
        )
        app_id = _last_insert_id(conn, cursor)
        conn.commit()
        return get_application(connect, app_id) or {"id": app_id}
    finally:
        conn.close()


def list_applications(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    conn = connect()
    try:
        frame = read_sql_query(
            """SELECT a.*, jp.title AS job_title, jp.company AS company, jp.url AS job_url,
                      jp.first_seen_at AS job_first_seen_at
               FROM applications a
               LEFT JOIN job_postings jp ON jp.id = a.job_id
               ORDER BY COALESCE(a.submitted_at, a.created_at) DESC""",
            conn,
            None,
        )
        return frame.to_dict("records")
    finally:
        conn.close()


def get_application(connect: ConnectionFactory, application_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """SELECT a.*, jp.title AS job_title, jp.company AS company, jp.url AS job_url,
                      jp.first_seen_at AS job_first_seen_at
               FROM applications a
               LEFT JOIN job_postings jp ON jp.id = a.job_id
               WHERE a.id = ?""",
            (application_id,),
        ).fetchone()
        if not row:
            return None
        app = dict(row)
        app["events"] = [
            dict(event)
            for event in conn.execute(
                "SELECT * FROM application_events WHERE application_id = ? ORDER BY event_at ASC, id ASC",
                (application_id,),
            ).fetchall()
        ]
        return app
    finally:
        conn.close()


def update_application(connect: ConnectionFactory, application_id: int, payload: dict) -> dict | None:
    allowed = ["ats_type", "status", "channel", "resume_variant_id", "submitted_at"]
    updates = []
    values: list[object] = []
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if key == "status":
            value = _validated(value, APPLICATION_STATUSES, "status")
        if key == "channel":
            value = _validated(value, APPLICATION_CHANNELS, "channel")
        updates.append(f"{key} = ?")
        values.append(value)
    if not updates:
        return get_application(connect, application_id)
    updates.append("updated_at = ?")
    values.extend([_now(), application_id])
    conn = connect()
    try:
        conn.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()
    return get_application(connect, application_id)


def create_application_event(connect: ConnectionFactory, application_id: int, payload: dict) -> dict:
    event_type = _validated(payload.get("event_type"), APPLICATION_EVENTS, "event_type")
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO application_events (application_id, event_type, event_at, note)
               VALUES (?, ?, ?, ?)""",
            (application_id, event_type, payload.get("event_at") or _now(), payload.get("note")),
        )
        event_id = _last_insert_id(conn, cursor)
        conn.commit()
        row = conn.execute("SELECT * FROM application_events WHERE id = ?", (event_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def record_job_opened(connect: ConnectionFactory, job_id: int) -> dict:
    conn = connect()
    try:
        job = conn.execute("SELECT id FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise LookupError(f"Job not found: {job_id}")
        application = conn.execute(
            "SELECT id FROM applications WHERE job_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        now = _now()
        if application:
            application_id = int(application["id"])
            conn.execute("UPDATE applications SET updated_at = ? WHERE id = ?", (now, application_id))
        else:
            cursor = conn.execute(
                """INSERT INTO applications (
                       job_id, ats_type, status, channel, resume_variant_id,
                       created_at, submitted_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, None, "preparing", "portal", None, now, None, now),
            )
            application_id = _last_insert_id(conn, cursor)
        conn.execute("UPDATE job_postings SET pipeline_status = COALESCE(pipeline_status, 'new') WHERE id = ?", (job_id,))
        cursor = conn.execute(
            """INSERT INTO application_events (application_id, event_type, event_at, note)
               VALUES (?, ?, ?, ?)""",
            (application_id, "opened", now, "Opened application link."),
        )
        event_id = _last_insert_id(conn, cursor)
        conn.commit()
        return dict(conn.execute("SELECT * FROM application_events WHERE id = ?", (event_id,)).fetchone())
    finally:
        conn.close()


def create_resume_variant(connect: ConnectionFactory, payload: dict) -> dict:
    now = _now()
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO resume_variants (label, file_ref, base_version, created_at, diff_summary)
               VALUES (?, ?, ?, ?, ?)""",
            (payload["label"], payload.get("file_ref"), payload.get("base_version"), now, payload.get("diff_summary")),
        )
        item_id = _last_insert_id(conn, cursor)
        conn.commit()
        return dict(conn.execute("SELECT * FROM resume_variants WHERE id = ?", (item_id,)).fetchone())
    finally:
        conn.close()


def list_resume_variants(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    return _list_table(connect, read_sql_query, "resume_variants", "created_at DESC")


def register_generated_resume_variant(connect: ConnectionFactory, job_id: int, label: str, ats_cv_text: str) -> dict:
    summary = _diff_summary(ats_cv_text)
    resume = create_resume_variant(
        connect,
        {
            "label": label,
            "file_ref": f"generated://jobs/{job_id}/ats-cv",
            "base_version": "candidate_profile.base_cv_text",
            "diff_summary": summary,
        },
    )
    conn = connect()
    try:
        application = conn.execute(
            "SELECT id FROM applications WHERE job_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if application:
            application_id = int(application["id"])
            conn.execute(
                "UPDATE applications SET resume_variant_id = ?, updated_at = ? WHERE id = ?",
                (resume["id"], _now(), application_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO applications (
                       job_id, ats_type, status, channel, resume_variant_id,
                       created_at, submitted_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, None, "preparing", "portal", resume["id"], _now(), None, _now()),
            )
            application_id = _last_insert_id(conn, cursor)
        conn.execute(
            """INSERT INTO application_events (application_id, event_type, event_at, note)
               VALUES (?, ?, ?, ?)""",
            (application_id, "answer_saved", _now(), f"Linked resume variant {resume['label']}."),
        )
        conn.commit()
    finally:
        conn.close()
    return resume


def upsert_answer_definition(connect: ConnectionFactory, payload: dict) -> dict:
    now = _now()
    source = _validated(payload.get("source") or "approved", ANSWER_SOURCES, "source")
    sensitivity = _validated(payload.get("sensitivity") or "public", ANSWER_SENSITIVITIES, "sensitivity")
    patterns = payload.get("question_patterns") or []
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO answer_definitions (
                   canonical_key, question_patterns, answer_type, value, source,
                   sensitivity, requires_confirmation, last_confirmed_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_key) DO UPDATE SET
                   question_patterns = excluded.question_patterns,
                   answer_type = excluded.answer_type,
                   value = excluded.value,
                   source = excluded.source,
                   sensitivity = excluded.sensitivity,
                   requires_confirmation = excluded.requires_confirmation,
                   last_confirmed_at = excluded.last_confirmed_at,
                   updated_at = excluded.updated_at""",
            (
                payload["canonical_key"],
                json.dumps(patterns, ensure_ascii=False),
                payload.get("answer_type"),
                payload.get("value"),
                source,
                sensitivity,
                int(bool(payload.get("requires_confirmation", False))),
                payload.get("last_confirmed_at"),
                now,
            ),
        )
        conn.commit()
        return _answer_row(conn, payload["canonical_key"])
    finally:
        conn.close()


def list_answer_definitions(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    items = _list_table(connect, read_sql_query, "answer_definitions", "canonical_key ASC")
    for item in items:
        item["question_patterns"] = json.loads(item.get("question_patterns") or "[]")
        item["requires_confirmation"] = bool(item.get("requires_confirmation"))
    return items


def create_contact(connect: ConnectionFactory, payload: dict) -> dict:
    source = _validated(payload.get("source") or "manual", CONTACT_SOURCES, "source")
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO job_contacts (
                   job_id, company, name, role, linkedin_url, source, contacted_at, last_reply_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.get("job_id"),
                payload.get("company"),
                payload.get("name"),
                payload.get("role"),
                payload.get("linkedin_url"),
                source,
                payload.get("contacted_at"),
                payload.get("last_reply_at"),
            ),
        )
        contact_id = _last_insert_id(conn, cursor)
        conn.commit()
        return dict(conn.execute("SELECT * FROM job_contacts WHERE id = ?", (contact_id,)).fetchone())
    finally:
        conn.close()


def list_contacts(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    return _list_table(connect, read_sql_query, "job_contacts", "COALESCE(last_reply_at, contacted_at, id) DESC")


def create_follow_up(connect: ConnectionFactory, payload: dict) -> dict:
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO follow_ups (application_id, due_at, note, done_at)
               VALUES (?, ?, ?, ?)""",
            (payload["application_id"], payload["due_at"], payload.get("note"), payload.get("done_at")),
        )
        follow_up_id = _last_insert_id(conn, cursor)
        conn.commit()
        return dict(conn.execute("SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone())
    finally:
        conn.close()


def list_follow_ups(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    return _list_table(connect, read_sql_query, "follow_ups", "done_at IS NOT NULL ASC, due_at ASC")


def _list_table(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, table: str, order_by: str) -> list[dict]:
    conn = connect()
    try:
        return read_sql_query(f"SELECT * FROM {table} ORDER BY {order_by}", conn, None).to_dict("records")
    finally:
        conn.close()


def _answer_row(conn: sqlite3.Connection | db_connection.LibsqlConnection, key: str) -> dict:
    row = dict(conn.execute("SELECT * FROM answer_definitions WHERE canonical_key = ?", (key,)).fetchone())
    row["question_patterns"] = json.loads(row.get("question_patterns") or "[]")
    row["requires_confirmation"] = bool(row.get("requires_confirmation"))
    return row


def _validated(value: object, allowed: set[str], name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ValueError(f"Invalid {name}: {text}")
    return text


def _diff_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    headings = [line for line in lines if len(line) < 80 and not line.endswith(".")][:6]
    return "Generated ATS CV variant. Sections: " + ", ".join(headings or ["summary unavailable"])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _last_insert_id(conn: sqlite3.Connection | db_connection.LibsqlConnection, cursor: object) -> int:
    lastrowid = getattr(cursor, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    if not row:
        raise RuntimeError("Could not determine inserted row id.")
    return int(row["id"])
