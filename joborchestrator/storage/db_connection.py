from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class NamedRow(tuple):
    def __new__(cls, values: Iterable[Any], columns: list[str]):
        obj = super().__new__(cls, values)
        obj._columns = columns
        obj._index = {name: index for index, name in enumerate(columns)}
        return obj

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, str):
            return super().__getitem__(self._index[key])
        return super().__getitem__(key)

    def keys(self) -> list[str]:
        return list(self._columns)


class LibsqlCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor
        self.description = cursor.description

    def fetchone(self) -> NamedRow | None:
        row = self._cursor.fetchone()
        return self._wrap(row) if row is not None else None

    def fetchall(self) -> list[NamedRow]:
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", -1))

    def _wrap(self, row: Iterable[Any]) -> NamedRow:
        columns = [column[0] for column in self.description or []]
        return NamedRow(row, columns)


class LibsqlConnection:
    is_cloud = True

    def __init__(self, database_url: str, auth_token: str | None):
        import libsql

        if auth_token:
            self._conn = libsql.connect(database=database_url, auth_token=auth_token)
        else:
            self._conn = libsql.connect(database=database_url)

    def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> LibsqlCursor:
        cursor = self._conn.execute(sql, tuple(parameters or ()))
        return LibsqlCursor(cursor)

    def executemany(self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]) -> None:
        for parameters in seq_of_parameters:
            self.execute(sql, parameters)

    def executescript(self, script: str) -> None:
        for statement in _split_sql_script(script):
            self.execute(statement)

    def cursor(self) -> "LibsqlCursorAdapter":
        return LibsqlCursorAdapter(self)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class LibsqlCursorAdapter:
    def __init__(self, conn: LibsqlConnection):
        self._conn = conn
        self._cursor: LibsqlCursor | None = None
        self.description = None

    def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> "LibsqlCursorAdapter":
        self._cursor = self._conn.execute(sql, parameters)
        self.description = self._cursor.description
        return self

    def fetchone(self) -> NamedRow | None:
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list[NamedRow]:
        if self._cursor is None:
            return []
        return self._cursor.fetchall()

    def close(self) -> None:
        if self._cursor is not None:
            self._cursor.close()


def connect(db_path: str | Path) -> sqlite3.Connection | LibsqlConnection:
    turso_url = os.getenv("TURSO_DATABASE_URL")
    if turso_url:
        return LibsqlConnection(turso_url, os.getenv("TURSO_AUTH_TOKEN"))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def connection_mode() -> str:
    return "turso" if os.getenv("TURSO_DATABASE_URL") else "sqlite"


def _split_sql_script(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]
