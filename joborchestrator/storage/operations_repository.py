from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]


def create_operation(
    connect: ConnectionFactory,
    operation_type: str,
    input_payload: dict,
    progress_message: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO operation_runs (
                   type, status, progress_message, input_json, attempts,
                   created_at, updated_at
               ) VALUES (?, 'queued', ?, ?, 0, ?, ?)""",
            (operation_type, progress_message, json.dumps(input_payload, ensure_ascii=False), now, now),
        )
        conn.commit()
        return _last_insert_id(conn, cursor)
    finally:
        conn.close()


def get_operation(connect: ConnectionFactory, operation_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM operation_runs WHERE id = ?", (operation_id,)).fetchone()
        return operation_row_to_dict(row) if row else None
    finally:
        conn.close()


def get_latest_operation(connect: ConnectionFactory, operation_type: str | None = None) -> dict | None:
    conn = connect()
    try:
        if operation_type:
            row = conn.execute(
                "SELECT * FROM operation_runs WHERE type = ? ORDER BY created_at DESC LIMIT 1",
                (operation_type,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM operation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return operation_row_to_dict(row) if row else None
    finally:
        conn.close()


def get_active_operation(connect: ConnectionFactory, operation_type: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """SELECT *
               FROM operation_runs
               WHERE type = ?
                 AND status IN ('queued', 'running')
               ORDER BY
                 CASE status WHEN 'running' THEN 0 ELSE 1 END,
                 updated_at DESC,
                 created_at DESC
               LIMIT 1""",
            (operation_type,),
        ).fetchone()
        return operation_row_to_dict(row) if row else None
    finally:
        conn.close()


def list_operations(connect: ConnectionFactory, limit: int = 20) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT *
               FROM operation_runs
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (int(limit),),
        ).fetchall()
        return [operation_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def claim_next_operation(
    connect: ConnectionFactory,
    worker_id: str,
    operation_types: list[str] | None = None,
) -> dict | None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        params: list[object] = []
        query = "SELECT id FROM operation_runs WHERE status = 'queued'"
        if operation_types:
            placeholders = ",".join("?" for _ in operation_types)
            query += f" AND type IN ({placeholders})"
            params.extend(operation_types)
        query += " ORDER BY created_at ASC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        operation_id = int(row["id"])
        conn.execute(
            """UPDATE operation_runs
               SET status = 'running',
                   attempts = attempts + 1,
                   claimed_by = ?,
                   started_at = COALESCE(started_at, ?),
                   progress_message = 'Worker started processing.',
                   updated_at = ?
               WHERE id = ? AND status = 'queued'""",
            (worker_id, now, now, operation_id),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM operation_runs WHERE id = ?", (operation_id,)).fetchone()
        if not claimed or claimed["status"] != "running" or claimed["claimed_by"] != worker_id:
            return None
        return operation_row_to_dict(claimed)
    finally:
        conn.close()


def requeue_stale_operations(
    connect: ConnectionFactory,
    operation_types: list[str] | None = None,
    stale_seconds: int = 3600,
) -> int:
    now = datetime.now()
    cutoff = (now - timedelta(seconds=max(1, int(stale_seconds)))).isoformat(timespec="seconds")
    conn = connect()
    try:
        params: list[object] = [now.isoformat(timespec="seconds"), cutoff]
        query = """UPDATE operation_runs
                   SET status = 'queued',
                       claimed_by = NULL,
                       progress_message = 'Requeued after worker timeout.',
                       updated_at = ?
                   WHERE status = 'running'
                     AND updated_at < ?"""
        if operation_types:
            placeholders = ",".join("?" for _ in operation_types)
            query += f" AND type IN ({placeholders})"
            params.extend(operation_types)
        cursor = conn.execute(query, params)
        conn.commit()
        return int(getattr(cursor, "rowcount", 0) or 0)
    finally:
        conn.close()


def update_operation_progress(connect: ConnectionFactory, operation_id: int, message: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        conn.execute(
            "UPDATE operation_runs SET progress_message = ?, updated_at = ? WHERE id = ?",
            (message, now, operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def complete_operation(
    connect: ConnectionFactory,
    operation_id: int,
    output_payload: dict,
    message: str = "Completed.",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        conn.execute(
            """UPDATE operation_runs
               SET status = 'completed',
                   progress_message = ?,
                   output_json = ?,
                   error = NULL,
                   finished_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (message, json.dumps(output_payload, ensure_ascii=False), now, now, operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def fail_operation(connect: ConnectionFactory, operation_id: int, error: str, message: str = "Failed.") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        conn.execute(
            """UPDATE operation_runs
               SET status = 'failed',
                   progress_message = ?,
                   error = ?,
                   finished_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (message, error, now, now, operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def operation_row_to_dict(row: object) -> dict:
    data = dict(row)
    for field in ("input_json", "output_json"):
        value = data.get(field)
        data[field] = parse_json_value(value, {}) if value else None
    return data


def parse_json_value(value: object, fallback: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback


def _last_insert_id(conn: sqlite3.Connection | db_connection.LibsqlConnection, cursor: object) -> int:
    lastrowid = getattr(cursor, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    if not row:
        raise RuntimeError("Could not determine inserted row id.")
    return int(row["id"])
