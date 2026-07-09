from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[
    [str, sqlite3.Connection | db_connection.LibsqlConnection, list[object] | tuple[object, ...] | None],
    pd.DataFrame,
]


def create_ranking_job(
    connect: ConnectionFactory,
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
    conn = connect()
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


def list_ranking_jobs(connect: ConnectionFactory, read_sql_query: ReadSqlQuery, limit: int = 20) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
            """SELECT
                   rj.*,
                   COALESCE(counts.queued_items, 0) AS queued_items,
                   COALESCE(counts.running_items, 0) AS running_items,
                   COALESCE(counts.completed_items, 0) AS completed_items,
                   COALESCE(counts.failed_item_count, 0) AS failed_item_count,
                   COALESCE(counts.cancelled_items, 0) AS cancelled_items,
                   (
                       SELECT error
                       FROM ranking_job_items rji_error
                       WHERE rji_error.ranking_job_id = rj.id
                         AND rji_error.error IS NOT NULL
                       ORDER BY rji_error.updated_at DESC
                       LIMIT 1
                   ) AS latest_item_error
               FROM ranking_jobs rj
               LEFT JOIN (
                   SELECT
                       ranking_job_id,
                       SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_items,
                       SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_items,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_items,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_item_count,
                       SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_items
                   FROM ranking_job_items
                   GROUP BY ranking_job_id
               ) counts ON counts.ranking_job_id = rj.id
               ORDER BY rj.created_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def get_ranking_job(connect: ConnectionFactory, ranking_job_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM ranking_jobs WHERE id = ?", (ranking_job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_next_ranking_job(connect: ConnectionFactory) -> dict | None:
    conn = connect()
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


def start_ranking_job(connect: ConnectionFactory, ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def cancel_ranking_job(connect: ConnectionFactory, ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def fail_ranking_job(connect: ConnectionFactory, ranking_job_id: int, error: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def complete_ranking_job_if_done(connect: ConnectionFactory, ranking_job_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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


def get_queued_ranking_items(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    ranking_job_id: int,
    limit: int = 100,
) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
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


def requeue_stale_ranking_items(
    connect: ConnectionFactory,
    ranking_job_id: int | None = None,
    stale_seconds: int = 60,
) -> int:
    now = datetime.now()
    cutoff = (now - timedelta(seconds=max(1, int(stale_seconds)))).isoformat(timespec="seconds")
    now_text = now.isoformat(timespec="seconds")
    conn = connect()
    try:
        params: list[object] = [
            "Requeued after worker timeout or interrupted run-once.",
            now_text,
            cutoff,
        ]
        job_filter = ""
        if ranking_job_id is not None:
            job_filter = " AND ranking_job_id = ?"
            params.append(int(ranking_job_id))
        cursor = conn.execute(
            f"""UPDATE ranking_job_items
                SET status = 'queued',
                    error = ?,
                    updated_at = ?
                WHERE status = 'running'
                  AND updated_at <= ?{job_filter}""",
            params,
        )
        if ranking_job_id is not None:
            conn.execute(
                """UPDATE ranking_jobs
                   SET updated_at = ?
                   WHERE id = ? AND status = 'running'""",
                (now_text, int(ranking_job_id)),
            )
        conn.commit()
        return int(cursor.rowcount if cursor.rowcount is not None else 0)
    finally:
        conn.close()


def requeue_failed_ranking_items(connect: ConnectionFactory, ranking_job_id: int) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        cursor = conn.execute(
            """UPDATE ranking_job_items
               SET status = 'queued',
                   error = 'Requeued after failed ranking attempt.',
                   updated_at = ?
               WHERE ranking_job_id = ? AND status = 'failed'""",
            (now, int(ranking_job_id)),
        )
        conn.execute(
            """UPDATE ranking_jobs
               SET status = 'queued',
                   error = NULL,
                   finished_at = NULL,
                   updated_at = ?
               WHERE id = ? AND status IN ('failed', 'running', 'queued', 'completed')""",
            (now, int(ranking_job_id)),
        )
        counts = _ranking_job_item_counts(conn, int(ranking_job_id))
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
                int(ranking_job_id),
            ),
        )
        conn.commit()
        return int(cursor.rowcount if cursor.rowcount is not None else 0)
    finally:
        conn.close()


def mark_ranking_items_running(connect: ConnectionFactory, ranking_job_id: int, job_ids: list[int]) -> None:
    if not job_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in job_ids)
    params: list[object] = [now, now, ranking_job_id, *[int(job_id) for job_id in job_ids]]
    conn = connect()
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
    connect: ConnectionFactory,
    ranking_job_id: int,
    ranking_version: str,
    job_ids: list[int] | None = None,
    missing_error: str = "NVIDIA did not save a ranking for this job.",
) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
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
                        error = ?,
                        finished_at = COALESCE(finished_at, ?),
                        updated_at = ?
                    WHERE ranking_job_id = ? AND job_posting_id IN ({placeholders})""",
                [missing_error[:2000], now, now, ranking_job_id, *failed_ids],
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
