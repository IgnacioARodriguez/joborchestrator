from __future__ import annotations

from datetime import datetime
from typing import Callable

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]

RESOURCE_TABLES: dict[str, tuple[str, ...]] = {
    "jobs": ("job_postings", "job_rankings", "job_hiring_contacts"),
    "applications": (
        "applications",
        "application_events",
        "follow_ups",
        "application_material_snapshots",
    ),
    "sessions": ("application_sessions", "application_session_events"),
    "operations": ("operation_runs", "ranking_jobs", "ranking_job_items"),
}


def ensure_sync_schema(conn: db_connection.LibsqlConnection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sync_revisions (
               resource TEXT PRIMARY KEY,
               revision INTEGER NOT NULL DEFAULT 0,
               updated_at TEXT NOT NULL
           )"""
    )
    now = datetime.now().isoformat(timespec="seconds")
    for resource in RESOURCE_TABLES:
        conn.execute(
            """INSERT INTO sync_revisions (resource, revision, updated_at)
               VALUES (?, 0, ?)
               ON CONFLICT(resource) DO NOTHING""",
            (resource, now),
        )

    for resource, tables in RESOURCE_TABLES.items():
        for table in tables:
            for action in ("INSERT", "UPDATE", "DELETE"):
                trigger_name = f"sync_{resource}_{table}_{action.lower()}"
                conn.execute(
                    f"""CREATE TRIGGER IF NOT EXISTS {trigger_name}
                        AFTER {action} ON {table}
                        BEGIN
                            UPDATE sync_revisions
                            SET revision = revision + 1,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE resource = '{resource}';
                        END"""
                )


def get_sync_status(connect: ConnectionFactory) -> dict:
    conn = connect()
    try:
        revision_rows = conn.execute(
            "SELECT resource, revision, updated_at FROM sync_revisions ORDER BY resource"
        ).fetchall()
        activity = conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM operation_runs
                    WHERE status IN ('queued', 'running')) AS operations,
                   (SELECT COUNT(*) FROM ranking_jobs
                    WHERE status IN ('queued', 'running')) AS ranking_jobs"""
        ).fetchone()
        return {
            "resources": {
                str(row["resource"]): {
                    "revision": int(row["revision"]),
                    "updated_at": row["updated_at"],
                }
                for row in revision_rows
            },
            "activity": {
                "operations": int(activity["operations"] if activity else 0),
                "ranking_jobs": int(activity["ranking_jobs"] if activity else 0),
            },
        }
    finally:
        conn.close()
