from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]


def get_app_setting(connect: ConnectionFactory, key: str, fallback: object | None = None) -> object | None:
    conn = connect()
    try:
        row = conn.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return fallback
        return json.loads(row["value_json"])
    finally:
        conn.close()


def set_app_setting(connect: ConnectionFactory, key: str, value: object) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO app_settings (key, value_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value_json = excluded.value_json,
                   updated_at = excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        conn.commit()
    finally:
        conn.close()


def get_candidate_profile_payload(connect: ConnectionFactory) -> dict | None:
    value = get_app_setting(connect, "candidate_profile")
    return value if isinstance(value, dict) else None


def save_candidate_profile_payload(connect: ConnectionFactory, profile: dict) -> None:
    set_app_setting(connect, "candidate_profile", profile)
