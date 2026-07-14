from __future__ import annotations

from joborchestrator import worker
from joborchestrator.storage import persistence as db
from test_api_endpoints import make_job


def test_worker_processes_application_execution_operation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    db.init_db()
    apply_url = "https://boards.greenhouse.io/acme/jobs/worker"
    db.upsert_job_posting(make_job(external_id="job-application"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "review_before_submit"})

    async def fake_run_application_execution(**kwargs):
        db.transition_application_session(kwargs["session_id"], "preflight", {"note": "opened"})
        updated = db.transition_application_session(kwargs["session_id"], "needs_user_input", {"note": "needs input"})
        return {"session": updated, "provider": "greenhouse"}

    monkeypatch.setattr(worker, "run_application_execution", fake_run_application_execution)
    operation_id = db.create_operation(
        "application_execution",
        {
            "session_id": session["id"],
            "job_id": job_id,
            "apply_url": apply_url,
            "provider": "greenhouse",
            "dry_run": True,
        },
    )

    assert worker.process_once(worker_id="test-worker") is True
    operation = db.get_operation(operation_id)
    assert operation["status"] == "completed"
    assert db.get_application_session(session["id"])["state"] == "needs_user_input"
