from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from joborchestrator.storage import sync_repository


def _connect_factory(path):
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    return connect


def _create_domain_tables(conn: sqlite3.Connection) -> None:
    for table in {
        table
        for tables in sync_repository.RESOURCE_TABLES.values()
        for table in tables
    }:
        conn.execute(
            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, status TEXT)"
        )
    conn.commit()


def test_sync_revisions_follow_domain_changes(tmp_path):
    connect = _connect_factory(tmp_path / "sync.db")
    conn = connect()
    _create_domain_tables(conn)
    sync_repository.ensure_sync_schema(conn)
    conn.commit()

    conn.execute("INSERT INTO job_postings (status) VALUES ('new')")
    conn.execute("INSERT INTO applications (status) VALUES ('submitted')")
    conn.execute("UPDATE applications SET status = 'interview' WHERE id = 1")
    conn.execute("DELETE FROM applications WHERE id = 1")
    conn.commit()
    conn.close()

    status = sync_repository.get_sync_status(connect)
    assert status["resources"]["jobs"]["revision"] == 1
    assert status["resources"]["applications"]["revision"] == 3
    assert status["resources"]["sessions"]["revision"] == 0


def test_sync_schema_is_idempotent_and_reports_activity(tmp_path):
    connect = _connect_factory(tmp_path / "sync.db")
    conn = connect()
    _create_domain_tables(conn)
    sync_repository.ensure_sync_schema(conn)
    sync_repository.ensure_sync_schema(conn)
    conn.execute("INSERT INTO operation_runs (status) VALUES ('queued')")
    conn.execute("INSERT INTO ranking_jobs (status) VALUES ('running')")
    conn.commit()
    conn.close()

    status = sync_repository.get_sync_status(connect)
    assert status["resources"]["operations"]["revision"] == 2
    assert status["activity"] == {"operations": 1, "ranking_jobs": 1}


def test_sync_status_endpoint_disables_http_caching(monkeypatch):
    from joborchestrator import api as api_module

    expected = {
        "resources": {
            resource: {"revision": 0, "updated_at": "2026-08-04T17:00:00"}
            for resource in sync_repository.RESOURCE_TABLES
        },
        "activity": {"operations": 0, "ranking_jobs": 0},
    }
    monkeypatch.setattr(api_module.db, "get_sync_status", lambda: expected)

    response = TestClient(api_module.app).get("/api/sync/status")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "private, no-store"
