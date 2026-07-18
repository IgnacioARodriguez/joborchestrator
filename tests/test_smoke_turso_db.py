from __future__ import annotations

import sqlite3

from scripts.smoke_turso_db import evaluate_turso_summary, inspect_turso_connection


def test_turso_db_smoke_inspects_expected_schema_readonly(tmp_path):
    db_path = tmp_path / "turso-shaped.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE job_postings (
            id TEXT PRIMARY KEY,
            source TEXT,
            company TEXT,
            title TEXT,
            last_seen_at TEXT,
            first_seen_at TEXT
        );
        CREATE TABLE job_rankings (
            id INTEGER PRIMARY KEY,
            job_id TEXT,
            decision TEXT,
            ranking_version TEXT
        );
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY,
            job_id TEXT
        );
        CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT
        );
        CREATE TABLE ranking_jobs (
            id INTEGER PRIMARY KEY,
            provider TEXT,
            model TEXT
        );
        INSERT INTO job_postings VALUES ('job-1', 'linkedin', 'Acme', 'ML Engineer', '2026-07-18', '2026-07-17');
        INSERT INTO job_rankings VALUES (1, 'job-1', 'APPLY_NOW', 'ranking/nvidia_response_contract/v1');
        INSERT INTO applications VALUES (1, 'job-1');
        INSERT INTO app_settings VALUES ('candidate_profile', '{"name":"Candidate"}');
        INSERT INTO ranking_jobs VALUES (1, 'nvidia', 'nvidia/llama-3.3-nemotron-super-49b-v1');
        """
    )
    conn.commit()

    before = db_path.read_bytes()
    try:
        summary = inspect_turso_connection(conn)
        checks = evaluate_turso_summary(summary)
    finally:
        conn.close()
    after = db_path.read_bytes()

    assert before == after
    assert checks["passed"] is True
    assert summary["counts"]["job_postings"] == 1
    assert summary["counts"]["job_rankings"] == 1
    assert summary["profile_present"] is True
    assert summary["latest_job"]["title"] == "ML Engineer"
    assert summary["source_counts"] == [{"source": "linkedin", "count": 1}]
    assert summary["ranking_jobs_by_provider"] == [
        {"provider": "nvidia", "model": "nvidia/llama-3.3-nemotron-super-49b-v1", "count": 1}
    ]


def test_turso_db_smoke_fails_when_core_data_is_missing():
    summary = {
        "counts": {"job_postings": 0, "job_rankings": 0, "applications": 0, "app_settings": 0},
        "profile_present": False,
        "ranking_versions": [],
        "source_counts": [],
    }

    checks = evaluate_turso_summary(summary, min_jobs=1, min_rankings=1, require_profile=True)

    assert checks["passed"] is False
    assert "Expected at least 1 job_postings rows." in checks["failures"]
    assert "Expected at least 1 job_rankings rows." in checks["failures"]
    assert "Candidate profile is missing from app_settings." in checks["failures"]
