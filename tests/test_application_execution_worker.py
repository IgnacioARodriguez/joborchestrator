from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

from joborchestrator import worker
from joborchestrator.automation.executor import run_application_execution
from joborchestrator.automation import local_browser_agent
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


def test_application_execution_starts_local_browser_handoff(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "1")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.upsert_job_posting(make_job(external_id="handoff-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "review_before_submit"})
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    result = asyncio.run(_run_handoff_once(int(session["id"]), job_id, html))
    updated = db.get_application_session(int(session["id"]))

    assert result["browser_handoff"]["status"] == "started"
    assert result["browser_handoff"]["ref"].startswith("local-browser://session/")
    assert updated["browser_session_ref"] == result["browser_handoff"]["ref"]
    assert updated["artifacts_json"]["browser_handoff"]["ref"] == result["browser_handoff"]["ref"]


def test_application_execution_resumes_local_browser_handoff(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "1")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.upsert_job_posting(make_job(external_id="handoff-resume-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "review_before_submit"})
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    result = asyncio.run(_run_handoff_twice(int(session["id"]), job_id, html))

    assert result["second_navigation"][0]["action"] == "resumed_browser_session"
    assert result["first_ref"] == result["second_ref"]


def test_application_execution_auto_submits_when_preconditions_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("ENABLE_AUTO_SUBMIT_APPROVED", "1")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="auto-submit-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\nSynthetic backend engineer.\n\n"
            "Technical Skills\nPython, FastAPI.\n\n"
            "Professional Experience\nBuilt reliable APIs.\n\n"
            "Education\nSynthetic degree."
        ),
    )
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "auto_submit_approved"})
    html = """
    <!doctype html>
    <html>
      <body>
        <main data-source="boards.greenhouse.io">
          <form id="application_form" onsubmit="window.__submitted = true; event.preventDefault(); document.body.setAttribute('data-submitted', 'true')">
            <label for="first_name">Full name *</label>
            <input id="first_name" name="first_name" type="text" required>
            <label for="email">Email *</label>
            <input id="email" name="email" type="email" required>
            <input id="resume" name="resume" type="file" required>
            <button type="submit">Submit application</button>
          </form>
        </main>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="greenhouse",
            dry_run=False,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    application = db.get_application(int(updated["application_id"]))

    assert result["auto_submit"]["status"] == "submitted"
    assert updated["state"] == "submitted"
    assert application["status"] == "submitted"
    assert updated["artifacts_json"]["auto_submit"]["control_text"] == "Submit application"


def test_application_execution_auto_submit_blocks_unknown_sensitive_required_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("ENABLE_AUTO_SUBMIT_APPROVED", "1")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="auto-submit-blocked-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\nSynthetic backend engineer.\n\n"
            "Technical Skills\nPython, FastAPI.\n\n"
            "Professional Experience\nBuilt reliable APIs.\n\n"
            "Education\nSynthetic degree."
        ),
    )
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "auto_submit_approved"})
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="greenhouse",
            dry_run=False,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["auto_submit"]["status"] == "blocked"
    assert "unknown_required_or_sensitive_fields" in result["auto_submit"]["reasons"]
    assert updated["state"] == "needs_user_input"


async def _run_handoff_once(session_id: int, job_id: int, html: str) -> dict:
    result = await run_application_execution(
        session_id=session_id,
        job_id=job_id,
        apply_url=f"data:text/html,{quote(html)}",
        provider_hint="greenhouse",
        dry_run=True,
    )
    ref = result["browser_handoff"]["ref"]
    local_session = await local_browser_agent.get_session(ref)
    try:
        assert local_session is not None
        assert not local_session.page.is_closed()
        return result
    finally:
        await local_browser_agent.close_session(ref)


async def _run_handoff_twice(session_id: int, job_id: int, html: str) -> dict:
    first = await run_application_execution(
        session_id=session_id,
        job_id=job_id,
        apply_url=f"data:text/html,{quote(html)}",
        provider_hint="greenhouse",
        dry_run=True,
    )
    second = await run_application_execution(
        session_id=session_id,
        job_id=job_id,
        apply_url=f"data:text/html,{quote(html)}",
        provider_hint="greenhouse",
        dry_run=True,
    )
    ref = second["browser_handoff"]["ref"]
    try:
        return {
            "first_ref": first["browser_handoff"]["ref"],
            "second_ref": second["browser_handoff"]["ref"],
            "second_navigation": second["navigation"],
        }
    finally:
        await local_browser_agent.close_session(ref)
