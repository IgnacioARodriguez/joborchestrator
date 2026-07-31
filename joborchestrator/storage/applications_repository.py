from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Callable

import pandas as pd

from joborchestrator.application_sessions import dumps, loads, new_idempotency_key, now as session_now, validate_transition
from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[
    [str, sqlite3.Connection | db_connection.LibsqlConnection, list[object] | tuple[object, ...] | None],
    pd.DataFrame,
]

APPLICATION_STATUSES = {
    "preparing",
    "materials_ready",
    "opened",
    "prefilled",
    "needs_user_input",
    "submit_only",
    "ready_for_review",
    "submitted_manually",
    "submission_verified",
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
    "submitted_manually",
    "submission_verified",
    "submitted",
    "recruiter_reply",
    "rejection",
    "interview_scheduled",
    "ghosted",
    "status_changed",
    "follow_up_scheduled",
    "follow_up_completed",
    "note_added",
}
SUBMISSION_STATUSES = {"submitted", "submitted_manually", "submission_verified"}
ANSWER_SOURCES = {"approved", "generated"}
ANSWER_SENSITIVITIES = {"public", "preference", "sensitive"}
ANSWER_STATUSES = {"proposed", "approved", "rejected", "expired", "requires_confirmation"}
CONTACT_SOURCES = {"linkedin_scraper", "manual"}
ACCOUNT_STATUSES = {"unknown", "needs_login", "ready", "failed", "blocked"}


def create_application(connect: ConnectionFactory, payload: dict) -> dict:
    now = _now()
    status = _validated(payload.get("status") or "preparing", APPLICATION_STATUSES, "status")
    channel = _validated(payload.get("channel") or "portal", APPLICATION_CHANNELS, "channel")
    conn = connect()
    try:
        existing = conn.execute(
            """SELECT id, status, channel, submitted_at FROM applications
               WHERE job_id = ?
                 AND status NOT IN ('rejected', 'withdrawn')
               ORDER BY updated_at DESC, id DESC
               LIMIT 1""",
            (payload["job_id"],),
        ).fetchone()
        if existing:
            application_id = int(existing["id"])
            if status in SUBMISSION_STATUSES:
                submitted_at = payload.get("submitted_at") or existing["submitted_at"] or now
                previous_status = str(existing["status"] or "")
                should_advance = previous_status not in SUBMISSION_STATUSES or (
                    status == "submission_verified" and previous_status != "submission_verified"
                )
                effective_status = status if should_advance else previous_status
                conn.execute(
                    """UPDATE applications
                       SET status = ?, channel = ?, submitted_at = COALESCE(submitted_at, ?), updated_at = ?
                       WHERE id = ?""",
                    (effective_status, channel, submitted_at, now, application_id),
                )
                if should_advance:
                    if payload.get("record_submission_event"):
                        conn.execute(
                            """INSERT INTO application_events (application_id, event_type, event_at, note)
                               VALUES (?, ?, ?, ?)""",
                            (
                                application_id,
                                _submission_event_type(status),
                                submitted_at,
                                _submission_note(payload),
                            ),
                        )
                    _snapshot_application_materials(conn, application_id, int(payload["job_id"]), submitted_at)
                conn.commit()
            return get_application(connect, application_id) or {"id": application_id}

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
        if status in SUBMISSION_STATUSES:
            submitted_at = payload.get("submitted_at") or now
            if payload.get("record_submission_event"):
                conn.execute(
                    """INSERT INTO application_events (application_id, event_type, event_at, note)
                       VALUES (?, ?, ?, ?)""",
                    (app_id, _submission_event_type(status), submitted_at, _submission_note(payload)),
                )
            _snapshot_application_materials(conn, app_id, int(payload["job_id"]), submitted_at)
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
        return [_hydrate_application(conn, row, include_snapshot=False) for row in frame.to_dict("records")]
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
        return _hydrate_application(conn, dict(row), include_snapshot=True)
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

    conn = connect()
    try:
        current = conn.execute("SELECT status FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not current:
            return None
        now = _now()
        updates.append("updated_at = ?")
        values.extend([now, application_id])
        conn.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id = ?", values)

        previous_status = str(current["status"] or "")
        next_status = str(payload.get("status") or previous_status)
        if next_status != previous_status:
            if next_status in {"rejected", "withdrawn"}:
                pending_follow_ups = conn.execute(
                    "SELECT id, due_at, note FROM follow_ups WHERE application_id = ? AND done_at IS NULL",
                    (application_id,),
                ).fetchall()
                conn.execute(
                    "UPDATE follow_ups SET done_at = ? WHERE application_id = ? AND done_at IS NULL",
                    (now, application_id),
                )
                for follow_up in pending_follow_ups:
                    detail = _follow_up_note(
                        "Closed automatically",
                        str(follow_up["due_at"] or ""),
                        follow_up["note"],
                    )
                    conn.execute(
                        """INSERT INTO application_events (application_id, event_type, event_at, note)
                           VALUES (?, ?, ?, ?)""",
                        (application_id, "follow_up_completed", now, detail),
                    )
            note = str(payload.get("note") or "").strip() or f"Status changed from {previous_status} to {next_status}."
            conn.execute(
                """INSERT INTO application_events (application_id, event_type, event_at, note)
                   VALUES (?, ?, ?, ?)""",
                (application_id, "status_changed", now, note),
            )
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


def _submission_event_type(status: str) -> str:
    if status == "submission_verified":
        return "submission_verified"
    if status == "submitted":
        return "submitted"
    return "submitted_manually"


def _submission_note(payload: dict) -> str:
    parts = ["Submitted manually by the user."]
    if payload.get("recruiter_contacted"):
        parts.append("Recruiter contacted.")
    note = str(payload.get("note") or "").strip()
    if note:
        parts.append(note)
    return " ".join(parts)


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
    status = _validated(payload.get("status") or _default_answer_status(payload, source), ANSWER_STATUSES, "status")
    patterns = payload.get("question_patterns") or []
    conn = connect()
    try:
        _ensure_answer_definition_columns(conn)
        conn.execute(
            """INSERT INTO answer_definitions (
                   canonical_key, question_patterns, answer_type, value, source,
                   sensitivity, requires_confirmation, status, language, confidence,
                   expires_at, profile_version, last_confirmed_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_key) DO UPDATE SET
                   question_patterns = excluded.question_patterns,
                   answer_type = excluded.answer_type,
                   value = excluded.value,
                   source = excluded.source,
                   sensitivity = excluded.sensitivity,
                   requires_confirmation = excluded.requires_confirmation,
                   status = excluded.status,
                   language = excluded.language,
                   confidence = excluded.confidence,
                   expires_at = excluded.expires_at,
                   profile_version = excluded.profile_version,
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
                status,
                payload.get("language"),
                payload.get("confidence"),
                payload.get("expires_at"),
                payload.get("profile_version"),
                payload.get("last_confirmed_at"),
                now,
            ),
        )
        conn.commit()
        return _answer_row(conn, payload["canonical_key"])
    finally:
        conn.close()


def list_answer_definitions(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    conn = connect()
    try:
        _ensure_answer_definition_columns(conn)
        conn.commit()
    finally:
        conn.close()
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
    application_id = int(payload["application_id"])
    due_at = str(payload.get("due_at") or "").strip()
    if not due_at:
        raise ValueError("due_at is required")
    conn = connect()
    try:
        application = conn.execute("SELECT id FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not application:
            raise LookupError(f"Application not found: {application_id}")
        cursor = conn.execute(
            """INSERT INTO follow_ups (application_id, due_at, note, done_at)
               VALUES (?, ?, ?, ?)""",
            (application_id, due_at, payload.get("note"), payload.get("done_at")),
        )
        follow_up_id = _last_insert_id(conn, cursor)
        conn.execute(
            """INSERT INTO application_events (application_id, event_type, event_at, note)
               VALUES (?, ?, ?, ?)""",
            (application_id, "follow_up_scheduled", _now(), _follow_up_note("Scheduled", due_at, payload.get("note"))),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone())
    finally:
        conn.close()


def update_follow_up(connect: ConnectionFactory, follow_up_id: int, *, done: bool) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone()
        if not row:
            return None
        current = dict(row)
        was_done = bool(current.get("done_at"))
        if was_done == done:
            return current
        done_at = _now() if done else None
        conn.execute("UPDATE follow_ups SET done_at = ? WHERE id = ?", (done_at, follow_up_id))
        event_type = "follow_up_completed" if done else "follow_up_scheduled"
        verb = "Completed" if done else "Reopened"
        conn.execute(
            """INSERT INTO application_events (application_id, event_type, event_at, note)
               VALUES (?, ?, ?, ?)""",
            (
                int(current["application_id"]),
                event_type,
                done_at or _now(),
                _follow_up_note(verb, str(current.get("due_at") or ""), current.get("note")),
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone()
        return dict(updated) if updated else None
    finally:
        conn.close()


def list_follow_ups(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    return _list_table(connect, read_sql_query, "follow_ups", "done_at IS NOT NULL ASC, due_at ASC")


def create_application_session(connect: ConnectionFactory, payload: dict) -> dict:
    now = session_now()
    job_id = int(payload["job_id"])
    provider = str(payload.get("provider") or "generic")
    mode = str(payload.get("mode") or "review_before_submit")
    idempotency_key = str(payload.get("idempotency_key") or new_idempotency_key(job_id, provider, mode))
    conn = connect()
    try:
        job = conn.execute("SELECT id FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise LookupError(f"Job not found: {job_id}")
        application_id = payload.get("application_id")
        if application_id is None:
            existing = conn.execute(
                """SELECT id FROM applications
                   WHERE job_id = ? AND status NOT IN ('rejected', 'withdrawn')
                   ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
            if existing:
                application_id = int(existing["id"])
            else:
                cursor = conn.execute(
                    """INSERT INTO applications (
                           job_id, ats_type, status, channel, resume_variant_id,
                           created_at, submitted_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, provider, "preparing", "portal", None, now, None, now),
                )
                application_id = _last_insert_id(conn, cursor)
        cursor = conn.execute(
            """INSERT INTO application_sessions (
                   job_id, application_id, provider, mode, state, current_step,
                   idempotency_key, browser_session_ref, form_schema_json,
                   mapped_answers_json, unknown_fields_json, validation_errors_json,
                   artifacts_json, started_at, updated_at, completed_at, manual_seconds,
                   total_seconds, user_clicks, fields_detected, fields_autofilled,
                   requires_review, last_error
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                application_id,
                provider,
                mode,
                payload.get("state") or "created",
                payload.get("current_step"),
                idempotency_key,
                payload.get("browser_session_ref"),
                dumps(payload.get("form_schema_json")),
                dumps(payload.get("mapped_answers_json")),
                dumps(payload.get("unknown_fields_json") or []),
                dumps(payload.get("validation_errors_json") or []),
                dumps(payload.get("artifacts_json") or {}),
                now,
                now,
                payload.get("completed_at"),
                int(payload.get("manual_seconds") or 0),
                int(payload.get("total_seconds") or 0),
                int(payload.get("user_clicks") or 0),
                int(payload.get("fields_detected") or 0),
                int(payload.get("fields_autofilled") or 0),
                int(bool(payload.get("requires_review", True))),
                payload.get("last_error"),
            ),
        )
        session_id = _last_insert_id(conn, cursor)
        conn.execute(
            """INSERT INTO application_session_events (session_id, from_state, to_state, event_at, note, payload_json)
               VALUES (?, NULL, ?, ?, ?, ?)""",
            (session_id, payload.get("state") or "created", now, "Session created.", dumps({})),
        )
        conn.commit()
        return _session_row(conn, session_id)
    finally:
        conn.close()


def get_application_session(connect: ConnectionFactory, session_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM application_sessions WHERE id = ?", (session_id,)).fetchone()
        return _hydrate_session(conn, dict(row)) if row else None
    finally:
        conn.close()


def get_latest_application_session_for_job(connect: ConnectionFactory, job_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM application_sessions WHERE job_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return _hydrate_session(conn, dict(row)) if row else None
    finally:
        conn.close()


def transition_application_session(connect: ConnectionFactory, session_id: int, state: str, payload: dict) -> dict:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM application_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise LookupError(f"Application session not found: {session_id}")
        current = str(row["state"])
        transition = validate_transition(current, state)
        now = session_now()
        if not transition.idempotent:
            updates = ["state = ?", "updated_at = ?"]
            values: list[object] = [state, now]
            if state in {"submitted", "submitted_manually"}:
                updates.append("completed_at = ?")
                values.append(now)
            for column in [
                "current_step",
                "browser_session_ref",
                "form_schema_json",
                "mapped_answers_json",
                "unknown_fields_json",
                "validation_errors_json",
                "artifacts_json",
                "manual_seconds",
                "total_seconds",
                "user_clicks",
                "fields_detected",
                "fields_autofilled",
                "requires_review",
                "last_error",
            ]:
                if column not in payload:
                    continue
                value = payload[column]
                if column.endswith("_json"):
                    value = dumps(value)
                if column == "requires_review":
                    value = int(bool(value))
                updates.append(f"{column} = ?")
                values.append(value)
            values.append(session_id)
            conn.execute(f"UPDATE application_sessions SET {', '.join(updates)} WHERE id = ?", values)
            conn.execute(
                """INSERT INTO application_session_events (session_id, from_state, to_state, event_at, note, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, current, state, now, payload.get("note"), dumps(payload)),
            )
            if state in {"submitted", "submitted_manually", "submission_verified"} and row["application_id"]:
                application_status = "submission_verified" if state == "submission_verified" else state
                conn.execute(
                    "UPDATE applications SET status = ?, submitted_at = COALESCE(submitted_at, ?), updated_at = ? WHERE id = ?",
                    (application_status, now, now, row["application_id"]),
                )
                _snapshot_application_materials(conn, int(row["application_id"]), int(row["job_id"]), now)
            conn.commit()
        return _session_row(conn, session_id)
    finally:
        conn.close()


def list_application_sessions(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, job_id: int | None, limit: int) -> list[dict]:
    conn = connect()
    try:
        params: list[object] = []
        query = "SELECT * FROM application_sessions"
        if job_id is not None:
            query += " WHERE job_id = ?"
            params.append(job_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = read_sql_query(query, conn, params).to_dict("records")
        return [_hydrate_session(conn, row) for row in rows]
    finally:
        conn.close()


def upsert_automation_site_account(connect: ConnectionFactory, payload: dict) -> dict:
    now = _now()
    provider = str(payload.get("provider") or "generic")
    domain = str(payload.get("domain") or "").lower().strip()
    if not domain:
        raise ValueError("domain is required")
    status = _validated(payload.get("status") or "unknown", ACCOUNT_STATUSES, "status")
    username = payload.get("username")
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO automation_site_accounts (
                   provider, domain, status, username, password_ref, browser_profile_ref,
                   last_login_at, notes, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, domain, username) DO UPDATE SET
                   status = excluded.status,
                   password_ref = COALESCE(excluded.password_ref, automation_site_accounts.password_ref),
                   browser_profile_ref = COALESCE(excluded.browser_profile_ref, automation_site_accounts.browser_profile_ref),
                   last_login_at = COALESCE(excluded.last_login_at, automation_site_accounts.last_login_at),
                   notes = COALESCE(excluded.notes, automation_site_accounts.notes),
                   updated_at = excluded.updated_at""",
            (
                provider,
                domain,
                status,
                username,
                payload.get("password_ref"),
                payload.get("browser_profile_ref"),
                payload.get("last_login_at"),
                payload.get("notes"),
                now,
                now,
            ),
        )
        conn.commit()
        return get_automation_site_account(connect, provider, domain, username) or {}
    finally:
        conn.close()


def get_automation_site_account(connect: ConnectionFactory, provider: str, domain: str, username: str | None = None) -> dict | None:
    conn = connect()
    try:
        if username:
            row = conn.execute(
                """SELECT * FROM automation_site_accounts
                   WHERE provider = ? AND domain = ? AND username = ?
                   ORDER BY updated_at DESC LIMIT 1""",
                (provider, domain, username),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM automation_site_accounts
                   WHERE provider = ? AND domain = ?
                   ORDER BY status = 'ready' DESC, updated_at DESC LIMIT 1""",
                (provider, domain),
            ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_automation_site_accounts(connect: ConnectionFactory, read_sql_query: ReadSqlQuery) -> list[dict]:
    return _list_table(connect, read_sql_query, "automation_site_accounts", "updated_at DESC")


def _list_table(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, table: str, order_by: str) -> list[dict]:
    conn = connect()
    try:
        return read_sql_query(f"SELECT * FROM {table} ORDER BY {order_by}", conn, None).to_dict("records")
    finally:
        conn.close()


def _answer_row(conn: sqlite3.Connection | db_connection.LibsqlConnection, key: str) -> dict:
    _ensure_answer_definition_columns(conn)
    row = dict(conn.execute("SELECT * FROM answer_definitions WHERE canonical_key = ?", (key,)).fetchone())
    row["question_patterns"] = json.loads(row.get("question_patterns") or "[]")
    row["requires_confirmation"] = bool(row.get("requires_confirmation"))
    return row


def _default_answer_status(payload: dict, source: str) -> str:
    if payload.get("requires_confirmation"):
        return "requires_confirmation"
    if source == "generated":
        return "proposed"
    return "approved"


def _ensure_answer_definition_columns(conn: sqlite3.Connection | db_connection.LibsqlConnection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(answer_definitions)").fetchall()}
    for column, column_type in {
        "status": "TEXT",
        "language": "TEXT",
        "confidence": "REAL",
        "expires_at": "TEXT",
        "profile_version": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE answer_definitions ADD COLUMN {column} {column_type}")
            columns.add(column)
    conn.execute("UPDATE answer_definitions SET status = 'proposed' WHERE status IS NULL AND source = 'generated'")
    conn.execute("UPDATE answer_definitions SET status = 'requires_confirmation' WHERE status IS NULL AND requires_confirmation = 1")
    conn.execute("UPDATE answer_definitions SET status = 'approved' WHERE status IS NULL")


def _session_row(conn: sqlite3.Connection | db_connection.LibsqlConnection, session_id: int) -> dict:
    row = conn.execute("SELECT * FROM application_sessions WHERE id = ?", (session_id,)).fetchone()
    return _hydrate_session(conn, dict(row))


def _hydrate_session(conn: sqlite3.Connection | db_connection.LibsqlConnection, row: dict) -> dict:
    for key, fallback in {
        "form_schema_json": {},
        "mapped_answers_json": {},
        "unknown_fields_json": [],
        "validation_errors_json": [],
        "artifacts_json": {},
    }.items():
        row[key] = loads(row.get(key), fallback)
    row["requires_review"] = bool(row.get("requires_review"))
    row["events"] = [
        {**dict(event), "payload_json": loads(event["payload_json"], {})}
        for event in conn.execute(
            "SELECT * FROM application_session_events WHERE session_id = ? ORDER BY event_at ASC, id ASC",
            (row["id"],),
        ).fetchall()
    ]
    return row


def _hydrate_application(
    conn: sqlite3.Connection | db_connection.LibsqlConnection,
    row: dict,
    *,
    include_snapshot: bool,
) -> dict:
    application_id = int(row["id"])
    row["events"] = [
        dict(event)
        for event in conn.execute(
            "SELECT * FROM application_events WHERE application_id = ? ORDER BY event_at ASC, id ASC",
            (application_id,),
        ).fetchall()
    ]
    row["follow_ups"] = [
        dict(follow_up)
        for follow_up in conn.execute(
            "SELECT * FROM follow_ups WHERE application_id = ? ORDER BY done_at IS NOT NULL ASC, due_at ASC, id ASC",
            (application_id,),
        ).fetchall()
    ]
    if include_snapshot:
        snapshot = conn.execute(
            "SELECT * FROM application_material_snapshots WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if snapshot:
            row["materials_snapshot"] = dict(snapshot)
            row["materials_snapshot"]["generation_json"] = loads(
                row["materials_snapshot"].get("generation_json"),
                {},
            )
    return row


def _follow_up_note(verb: str, due_at: str, note: object) -> str:
    detail = str(note or "").strip()
    message = f"{verb} follow-up for {due_at}."
    return f"{message} {detail}" if detail else message


def _snapshot_application_materials(
    conn: sqlite3.Connection | db_connection.LibsqlConnection,
    application_id: int,
    job_id: int,
    captured_at: str,
) -> None:
    """Freeze the materials exactly once when the user records a submission."""
    job = conn.execute(
        """SELECT recruiter_message, cover_letter, ats_cv_text, autofill_notes,
                  materials_provider, materials_model, materials_prompt_versions_json,
                  materials_generated_at, materials_review_states_json
           FROM job_postings WHERE id = ?""",
        (job_id,),
    ).fetchone()
    if not job:
        return
    generation = {
        "provider": job["materials_provider"],
        "model": job["materials_model"],
        "prompt_versions": loads(job["materials_prompt_versions_json"], {}),
        "generated_at": job["materials_generated_at"],
        "review_states": loads(job["materials_review_states_json"], {}),
    }
    conn.execute(
        """INSERT INTO application_material_snapshots (
               application_id, job_id, recruiter_message, cover_letter, ats_cv_text,
               autofill_notes, generation_json, captured_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(application_id) DO NOTHING""",
        (
            application_id,
            job_id,
            job["recruiter_message"],
            job["cover_letter"],
            job["ats_cv_text"],
            job["autofill_notes"],
            dumps(generation),
            captured_at,
        ),
    )


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
