from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from joborchestrator import api as api_module
from joborchestrator.storage import operations_repository


_OPERATION_SCHEMA = """
CREATE TABLE operation_runs (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_message TEXT,
    input_json TEXT,
    output_json TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0,
    claimed_by TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _connection_factory(path):
    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    return connect


def test_list_operations_by_ids_returns_only_requested_rows(tmp_path):
    database_path = tmp_path / "operations.db"
    connect = _connection_factory(database_path)
    connection = connect()
    connection.execute(_OPERATION_SCHEMA)
    connection.executemany(
        """INSERT INTO operation_runs (
               id, type, status, input_json, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                1,
                "application_materials_generation",
                "running",
                '{"job_id": 10}',
                "2026-08-04T10:00:00",
                "2026-08-04T10:00:00",
            ),
            (
                2,
                "job_scan",
                "completed",
                '{}',
                "2026-08-04T10:01:00",
                "2026-08-04T10:01:00",
            ),
            (
                3,
                "application_execution",
                "queued",
                '{"job_id": 20}',
                "2026-08-04T10:02:00",
                "2026-08-04T10:02:00",
            ),
        ],
    )
    connection.commit()
    connection.close()

    operations = operations_repository.list_operations_by_ids(connect, [1, 3, 1])

    assert [operation["id"] for operation in operations] == [3, 1]
    assert operations[0]["input_json"] == {"job_id": 20}
    assert operations[1]["input_json"] == {"job_id": 10}


def test_operations_route_accepts_repeated_ids(monkeypatch):
    captured = {}

    def list_by_ids(operation_ids):
        captured["ids"] = operation_ids
        return [{"id": operation_id} for operation_id in operation_ids]

    monkeypatch.setattr(api_module.db, "list_operations_by_ids", list_by_ids)

    response = TestClient(api_module.app).get(
        "/api/operations",
        params=[("ids", 7), ("ids", 3), ("ids", 7)],
    )

    assert response.status_code == 200
    assert captured["ids"] == [7, 3]
    assert response.json() == {"operations": [{"id": 7}, {"id": 3}]}


def test_operations_endpoint_rejects_oversized_batches():
    with pytest.raises(HTTPException) as exc_info:
        api_module.list_operations(limit=20, ids=list(range(1, 102)))

    assert exc_info.value.status_code == 400
    assert "At most 100" in str(exc_info.value.detail)
