from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

from joborchestrator import worker
from joborchestrator.automation.executor import _looks_blocked, auto_submit_blockers, run_application_execution
from joborchestrator.automation import local_browser_agent
from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
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


def test_application_challenge_copy_is_not_human_verification() -> None:
    html = """
    <form id="application_form">
      <label>Application Challenge: Security Code</label>
      <input name="challenge_answer">
    </form>
    """

    assert _looks_blocked("https://job-boards.greenhouse.io/warp/jobs/1", html) is False
    assert _looks_blocked(
        "https://job-boards.greenhouse.io/warp/jobs/1",
        '<form id="application_form"><script src="/recaptcha.js"></script><input name="email"></form>',
    ) is False
    assert _looks_blocked(
        "https://job-boards.greenhouse.io/warp/jobs/1",
        '<script src="https://www.gstatic.com/recaptcha/releases/x/recaptcha__es.js"></script>',
    ) is False
    assert _looks_blocked("https://example.test", "<h1>Verify you are human</h1>") is True


def test_auto_submit_blocks_placeholder_resume_on_real_url(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_AUTO_SUBMIT_APPROVED", "1")
    blockers = auto_submit_blockers(
        session={"mode": "auto_submit_approved"},
        provider="greenhouse",
        apply_url="https://job-boards.greenhouse.io/warp/jobs/4324888004",
        job={"ats_cv_text": "Professional Summary\nSynthetic backend engineer for automation rehearsal."},
        schema={"fields": []},
        mapping={"unknown_fields": []},
        resume_upload={"status": "not_applicable"},
        forbidden_submit_controls=[{"text": "Submit application"}],
        dry_run=False,
    )

    assert blockers == ["placeholder_resume_for_real_url"]


def test_auto_submit_allows_placeholder_resume_for_local_fixture(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_AUTO_SUBMIT_APPROVED", "1")
    blockers = auto_submit_blockers(
        session={"mode": "auto_submit_approved"},
        provider="greenhouse",
        apply_url="data:text/html,<form></form>",
        job={"ats_cv_text": "Professional Summary\nSynthetic backend engineer for automation rehearsal."},
        schema={"fields": []},
        mapping={"unknown_fields": []},
        resume_upload={"status": "not_applicable"},
        forbidden_submit_controls=[{"text": "Submit application"}],
        dry_run=False,
    )

    assert blockers == []


def test_auto_submit_blocks_lever_until_explicitly_supported(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_AUTO_SUBMIT_APPROVED", "1")
    blockers = auto_submit_blockers(
        session={"mode": "auto_submit_approved"},
        provider="lever",
        apply_url="https://jobs.lever.co/acme/backend/apply",
        job={"ats_cv_text": "Professional Summary\nReal backend engineer."},
        schema={"fields": []},
        mapping={"unknown_fields": []},
        resume_upload={"status": "not_applicable"},
        forbidden_submit_controls=[{"text": "Submit application"}],
        dry_run=False,
    )

    assert blockers == ["provider_not_supported"]


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


def test_application_execution_handles_lever_review_before_submit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload(
        {
            "full_name": "Synthetic Candidate",
            "email": "candidate@example.test",
            "phone": "+34 000 000 000",
            "linkedin_url": "https://www.linkedin.com/in/synthetic",
        }
    )
    apply_url = "https://jobs.lever.co/acme/backend/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="lever-review-job",
            source="lever",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "lever-review-job"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
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
    db.upsert_answer_definition(
        {
            "canonical_key": "preferred_location",
            "value": "Remote",
            "source": "approved",
            "sensitivity": "public",
            "requires_confirmation": False,
        }
    )
    db.upsert_answer_definition(
        {
            "canonical_key": "sponsorship",
            "value": "No",
            "source": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        }
    )
    session = db.create_application_session({"job_id": job_id, "provider": "lever", "mode": "review_before_submit"})
    html = Path("tests/fixtures/lever_application.html").read_text(encoding="utf-8")

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="lever",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["provider"] == "lever"
    assert result["resume_upload"]["status"] == "uploaded"
    assert result["unknown_fields"] == 0
    assert result["auto_submit"]["status"] == "disabled"
    assert result["forbidden_submit_controls"] == [
        {"tag": "button", "text": "Submit application", "action_policy": "forbidden"}
    ]
    assert updated["state"] == "ready_for_review"


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
