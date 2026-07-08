from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable

from joborchestrator.profile_skill_catalog import DEFAULT_SKILL_CATALOG
from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]


def list_skill_catalog(connect: ConnectionFactory) -> list[dict[str, object]]:
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT id, category, name, sort_order
               FROM skill_catalog
               ORDER BY category COLLATE NOCASE ASC, sort_order ASC, name COLLATE NOCASE ASC"""
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_skill_catalog_item(connect: ConnectionFactory, category: str, name: str) -> dict[str, object]:
    clean_category = category.strip() or "General"
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Skill name is required.")
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM skill_catalog WHERE category = ?",
            (clean_category,),
        ).fetchone()
        sort_order = int(row["next_sort"] if row else 0)
        cursor = conn.execute(
            """INSERT OR IGNORE INTO skill_catalog (category, name, sort_order, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (clean_category, clean_name, sort_order, now, now),
        )
        conn.commit()
        existing = conn.execute(
            """SELECT id, category, name, sort_order
               FROM skill_catalog
               WHERE category = ? AND lower(name) = lower(?)
               ORDER BY id DESC
               LIMIT 1""",
            (clean_category, clean_name),
        ).fetchone()
        if existing:
            return dict(existing)
        return {"id": _last_insert_id(conn, cursor), "category": clean_category, "name": clean_name, "sort_order": sort_order}
    finally:
        conn.close()


def seed_skill_catalog(conn: sqlite3.Connection | db_connection.LibsqlConnection) -> None:
    existing = conn.execute("SELECT 1 FROM skill_catalog LIMIT 1").fetchone()
    if existing:
        return
    now = datetime.now().isoformat(timespec="seconds")
    for category, skills in DEFAULT_SKILL_CATALOG.items():
        for index, skill in enumerate(skills):
            conn.execute(
                """INSERT OR IGNORE INTO skill_catalog (category, name, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (category, skill, index, now, now),
            )


def _last_insert_id(conn: sqlite3.Connection | db_connection.LibsqlConnection, cursor: object) -> int:
    lastrowid = getattr(cursor, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    if not row:
        raise RuntimeError("Could not determine inserted row id.")
    return int(row["id"])
