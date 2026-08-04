from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from joborchestrator import worker
from joborchestrator.automation.executor import (
    _build_application_automation_metrics,
    _build_human_intervention_report,
    _detect_page_access_issue,
    _looks_blocked,
    _looks_posting_unavailable,
    auto_submit_blockers,
    click_approved_submit_control,
    detect_safe_step_transition_controls,
    run_application_execution,
    run_bounded_repair_loop,
)
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
    assert _looks_blocked(
        "https://jobs.smartrecruiters.com/oneclick-ui",
        '<script src="https://ct.captcha-delivery.com/c.js"></script>',
    ) is True


def test_safe_step_transition_detection_excludes_final_submit() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <button type="button">Next</button>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    transition = asyncio.run(_detect_step_transition_for_html(html))

    assert transition["status"] == "available"
    assert transition["control"]["text"] == "Next"
    assert transition["blocked_controls"][0]["reason"] == "final_submit"


def test_safe_step_transition_blocks_continue_application_boundary() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <button type="button">Continue application</button>
        </form>
      </body>
    </html>
    """

    transition = asyncio.run(_detect_step_transition_for_html(html))

    assert transition["status"] == "not_available"
    assert transition["blocked_controls"][0]["reason"] == "application_boundary"


def test_posting_unavailable_copy_is_detected() -> None:
    html = """
    <h1>Sorry, we couldn't find anything here</h1>
    <p>The job posting you're looking for might have closed, or it has been removed. (404 error).</p>
    """

    assert _looks_posting_unavailable("https://jobs.lever.co/acme/closed/apply", html) is True


def test_access_issue_detection_checks_captcha_frames() -> None:
    html = """
    <!doctype html>
    <html><body>
      <iframe srcdoc="<h1>Please complete the CAPTCHA</h1>"></iframe>
    </body></html>
    """

    assert asyncio.run(_detect_access_issue_for_html(html)) == "challenge_detected"


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

    assert blockers == ["placeholder_resume_for_real_url", "final_submit_reserved_for_user"]


def test_auto_submit_reserves_final_submit_for_local_fixture(monkeypatch) -> None:
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

    assert blockers == ["final_submit_reserved_for_user"]


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

    assert blockers == ["provider_not_supported", "final_submit_reserved_for_user"]


def test_application_metrics_split_native_custom_and_shadow_controls() -> None:
    metrics = _build_application_automation_metrics(
        action_plan={
            "actions": [
                {
                    "action_type": "fill_text",
                    "field_name": "first_name",
                    "control_handle": {"locator_strategies": ["label_for"]},
                },
                {
                    "action_type": "select_option",
                    "field_name": "preferred_stack",
                    "control_handle": {"locator_strategies": ["aria_role"]},
                },
                {
                    "action_type": "fill_text",
                    "field_name": "shadow_email",
                    "control_handle": {"locator_strategies": ["label_for", "shadow_root"]},
                },
            ]
        },
        schema={"fields": []},
        validation_report={
            "status": "validation_clean",
            "checked_postconditions": 3,
            "satisfied_postconditions": 3,
            "summary": {"issues": 0},
        },
        fill_result={"filled_fields": ["first_name", "preferred_stack", "shadow_email"]},
        resume_upload={"status": "not_applicable"},
        repair_report={"dynamic_required_count": 0, "rescans": 1},
        mapping={"unknown_fields": []},
        step_transitions=[],
    )

    assert metrics["native_control_success_rate"] == 1.0
    assert metrics["custom_control_success_rate"] == 1.0
    assert metrics["shadow_control_success_rate"] == 1.0
    assert metrics["control_strategy_counts"]["planned"] == {
        "native_control": 1,
        "custom_control": 1,
        "shadow_control": 1,
    }


def test_application_metrics_do_not_mark_skipped_actions_submit_only_ready() -> None:
    metrics = _build_application_automation_metrics(
        action_plan={"actions": [{"action_type": "fill_text", "field_name": "name"}]},
        validation_report={"status": "validation_clean", "summary": {"issues": 0}},
        fill_result={"filled_fields": [], "skipped_fields": ["name"]},
        resume_upload={"status": "not_applicable"},
        repair_report={"dynamic_required_count": 0},
        mapping={"unknown_fields": []},
    )

    assert metrics["skipped_action_count"] == 1
    assert metrics["submit_only_ready"] is False


def test_application_metrics_track_resume_file_widget_uploads() -> None:
    metrics = _build_application_automation_metrics(
        action_plan={"actions": []},
        schema={
            "fields": [
                {
                    "name": "resume_upload",
                    "type": "file",
                    "locator_strategy": "file_widget",
                }
            ]
        },
        validation_report={
            "status": "validation_clean",
            "checked_postconditions": 0,
            "satisfied_postconditions": 0,
            "summary": {"issues": 0},
        },
        fill_result={"filled_fields": ["resume_upload"]},
        resume_upload={"status": "uploaded", "field_name": "resume_upload", "strategy": "file_chooser"},
        repair_report={"dynamic_required_count": 0, "rescans": 1},
        mapping={"unknown_fields": []},
        step_transitions=[],
    )

    assert metrics["resume_upload_success_rate"] == 1.0
    assert metrics["file_widget_success_rate"] == 1.0
    assert metrics["resume_upload_strategy"] == "file_chooser"


def test_human_intervention_report_classifies_answer_widget_and_submit_only() -> None:
    report = _build_human_intervention_report(
        next_state="needs_user_input",
        review={
            "unknown_fields": [
                {"name": "salary", "label": "Expected salary", "required": True, "sensitive": True},
                {"name": "validation", "type": "validation", "label": "Validation errors"},
            ]
        },
        mapping={"unknown_fields": []},
        validation_report={"status": "validation_failed", "summary": {"issues": 1}},
        repair_report={"dynamic_required_count": 0},
        resume_upload={"status": "unresolved", "field_name": "resume", "reason": "missing_resume_file"},
        fill_result={"skipped_fields": ["custom_select"]},
        automation_metrics={"submit_only_ready": False},
    )

    assert report["status"] == "needs_human"
    assert report["counts_by_type"]["answer"] == 1
    assert report["counts_by_type"]["validation"] == 1
    assert report["counts_by_type"]["resume_upload"] == 1
    assert report["counts_by_type"]["widget"] == 1
    assert report["blocking_count"] == 4

    submit_only = _build_human_intervention_report(
        next_state="submit_only",
        review={"unknown_fields": []},
        mapping={"unknown_fields": []},
        validation_report={"status": "validation_clean"},
        repair_report={"dynamic_required_count": 0},
        resume_upload={"status": "not_applicable"},
        fill_result={"skipped_fields": []},
        automation_metrics={"submit_only_ready": True},
    )

    assert submit_only["status"] == "submit_only"
    assert submit_only["types"] == ["submit_only"]
    assert submit_only["blocking_count"] == 0


def test_human_intervention_report_ignores_executed_policy_answers() -> None:
    report = _build_human_intervention_report(
        next_state="submit_only",
        review={"unknown_fields": []},
        mapping={
            "answers": [
                {
                    "field_name": "office",
                    "canonical_key": "preferred_location",
                    "value": None,
                    "requires_confirmation": True,
                }
            ]
        },
        validation_report={"status": "validation_clean"},
        repair_report={"dynamic_required_count": 0},
        resume_upload={"status": "not_applicable"},
        fill_result={"filled_fields": ["office"]},
        automation_metrics={"submit_only_ready": True},
    )

    assert report["status"] == "submit_only"
    assert report["types"] == ["submit_only"]


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
    assert updated["state"] == "submit_only"
    assert updated["artifacts_json"]["action_plan"]["provider"] == "lever"
    assert updated["artifacts_json"]["action_plan"]["summary"]["actions"] >= 4


def test_application_execution_handles_generic_form_review_before_submit(tmp_path, monkeypatch) -> None:
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
    apply_url = "https://careers.example.test/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="generic-review-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "generic-review-job"},
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
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = Path("tests/fixtures/generic_application.html").read_text(encoding="utf-8")

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["provider"] == "generic_form"
    assert result["resume_upload"]["status"] == "uploaded"
    assert result["unknown_fields"] == 0
    assert result["auto_submit"]["status"] == "disabled"
    assert result["forbidden_submit_controls"] == [
        {"tag": "button", "text": "Submit application", "action_policy": "forbidden"}
    ]
    assert updated["state"] == "submit_only"
    assert updated["artifacts_json"]["journey"]["phase"] == "actions_planned"
    assert updated["artifacts_json"]["action_plan"]["provider"] == "generic_form"
    assert updated["artifacts_json"]["action_plan"]["summary"]["actions"] >= 3


def test_application_execution_requires_real_name_when_only_headline_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"headline": "Synthetic backend engineer", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="headline-name-block-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]
    answers = {answer["field_name"]: answer for answer in updated["mapped_answers_json"]["answers"]}

    assert result["unknown_fields"] == 1
    assert updated["state"] == "needs_user_input"
    assert answers["name"]["canonical_key"] == "full_name"
    assert answers["name"]["value"] is None
    assert answers["name"]["match_strategy"] == "unresolved"
    assert artifacts["automation_metrics"]["submit_only_ready"] is False
    assert artifacts["human_intervention"]["status"] == "needs_human"


def test_application_execution_blocks_visual_only_terms_checkbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="visual-checkbox-block-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required>
          <div role="checkbox" aria-checked="false" aria-required="true" aria-label="Terms acknowledgement"
            onclick="window.__termsClicked = (window.__termsClicked || 0) + 1; this.setAttribute('aria-checked', 'true')">
            I agree
          </div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=False,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert updated["state"] == "needs_user_input"
    assert result["fields_autofilled"] == 2
    assert artifacts["automation_metrics"]["submit_only_ready"] is False
    assert artifacts["human_intervention"]["status"] == "needs_human"
    assert any("terms" in str(field.get("label") or "").lower() for field in updated["unknown_fields_json"])


def test_application_execution_does_not_check_legal_consent_even_with_approved_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    apply_url = "https://careers.example.test/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="consent-review-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "consent-review-job"},
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
            "canonical_key": "privacy_consent",
            "question_patterns": ["I agree to the privacy policy and certify my answers are accurate"],
            "value": "yes",
            "source": "approved",
            "sensitivity": "public",
            "requires_confirmation": False,
        }
    )
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required>
          <label for="resume">Resume *</label>
          <input id="resume" name="resume" type="file" required>
          <label for="privacy_consent">I agree to the privacy policy and certify my answers are accurate</label>
          <input id="privacy_consent" name="privacy_consent" type="checkbox" required>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    unknown_fields = updated["unknown_fields_json"]
    action_plan = updated["artifacts_json"]["action_plan"]
    human_intervention = updated["artifacts_json"]["human_intervention"]

    assert result["fields_autofilled"] == 3
    assert result["unknown_fields"] >= 1
    assert updated["state"] == "needs_user_input"
    assert "privacy_consent" not in {action["field_name"] for action in action_plan["actions"]}
    assert any(field.get("name") == "privacy_consent" for field in unknown_fields)
    assert any(item["field"] == "privacy_consent" and item["type"] == "answer" for item in human_intervention["items"])


def test_application_execution_handles_form_inside_accessible_iframe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    apply_url = "https://careers.example.test/jobs/backend"
    db.upsert_job_posting(
        JobPosting(
            external_id="iframe-application-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "iframe-application-job"},
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
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <h1>Job details</h1>
        <iframe srcdoc='
          <form id="application">
            <label for="name">Full name *</label>
            <input id="name" name="name" required>
            <label for="email">Email *</label>
            <input id="email" name="email" type="email" required>
            <label for="resume">Resume *</label>
            <input id="resume" name="resume" type="file" required>
            <button type="submit">Submit application</button>
          </form>
        '></iframe>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["provider"] == "generic_form"
    assert result["fields_detected"] == 3
    assert result["fields_autofilled"] == 3
    assert result["resume_upload"]["status"] == "uploaded"
    assert result["unknown_fields"] == 0
    assert updated["state"] == "submit_only"
    assert updated["artifacts_json"]["journey"]["surface"]["kind"] == "frame"
    assert updated["artifacts_json"]["action_plan"]["actions"][0]["surface_id"].startswith("frame:")


def test_application_execution_blocks_ready_when_validation_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    apply_url = "https://careers.example.test/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="validation-error-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "validation-error-job"},
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
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required aria-invalid="true">
          <input id="resume" name="resume" type="file" required>
          <div role="alert">Email domain is not accepted.</div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["fields_autofilled"] == 3
    assert result["unknown_fields"] == 1
    assert updated["state"] == "needs_user_input"
    assert updated["artifacts_json"]["validation"]["status"] == "validation_failed"
    assert updated["unknown_fields_json"][0]["type"] == "validation"
    assert any(issue["issue_type"] == "aria_invalid" for issue in updated["artifacts_json"]["validation"]["issues"])


def test_application_execution_detects_dynamic_required_fields_after_autofill(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate"})
    apply_url = "https://careers.example.test/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="dynamic-required-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "dynamic-required-job"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required oninput="document.getElementById('dynamic').style.display = 'block'">
          <div id="dynamic" style="display:none">
            <label for="portfolio">Portfolio URL *</label>
            <input id="portfolio" name="portfolio" required>
          </div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert result["fields_autofilled"] == 1
    assert result["unknown_fields"] == 1
    assert updated["state"] == "needs_user_input"
    assert artifacts["validation"]["status"] == "validation_clean"
    assert artifacts["repair"]["dynamic_required_count"] == 1
    assert artifacts["repair"]["dynamic_required_fields"][0]["name"] == "portfolio"
    assert artifacts["automation_metrics"]["dynamic_required_count"] == 1
    assert artifacts["automation_metrics"]["submit_only_ready"] is False


def test_application_execution_waits_for_delayed_spa_application_form(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="delayed-spa-form-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <main id="app">
          <h1>Backend Engineer</h1>
          <button onclick="
            setTimeout(() => {
              document.getElementById('app').innerHTML = `
                <form id='application'>
                  <label for='name'>Full name *</label>
                  <input id='name' name='name' required>
                  <label for='email'>Email *</label>
                  <input id='email' name='email' type='email' required>
                  <button type='submit'>Submit application</button>
                </form>
              `;
            }, 250);
          ">Apply now</button>
        </main>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["fields_autofilled"] == 2
    assert result["unknown_fields"] == 0
    assert updated["state"] == "submit_only"
    assert any(step["action"] == "clicked_control" for step in result["navigation"])
    assert any(step.get("stability_status") == "stable" for step in result["navigation"])


def test_application_execution_detects_delayed_dynamic_required_fields_after_autofill(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate"})
    db.upsert_job_posting(make_job(external_id="delayed-dynamic-required-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required oninput="
            setTimeout(() => {
              document.getElementById('dynamic').innerHTML = `
                <label for='portfolio'>Portfolio URL *</label>
                <input id='portfolio' name='portfolio' required>
              `;
            }, 250);
          ">
          <div id="dynamic"></div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert result["fields_autofilled"] == 1
    assert result["unknown_fields"] == 1
    assert artifacts["repair"]["dynamic_required_count"] == 1
    assert artifacts["repair"]["dynamic_required_fields"][0]["name"] == "portfolio"
    assert artifacts["journey"]["steps"][0]["fill_stability"]["mutation_count"] > 0
    assert artifacts["human_intervention"]["status"] == "needs_human"
    assert artifacts["human_intervention"]["counts_by_type"]["dynamic_field"] == 1


def test_application_execution_repairs_rerendered_control_with_logical_rebind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("APPLICATION_REPAIR_RETRY_BUDGET", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="repair-rerender-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <div id="name-holder">
            <label for="name_1">Full name *</label>
            <input id="name_1" name="name_1" required oninput="
              if (!window.__rerendered) {
                window.__rerendered = true;
                document.getElementById('name-holder').innerHTML = `<label for='name_2'>Full name *</label><input id='name_2' name='name_2' required>`;
              }
            ">
          </div>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required oninput="
            window.__emailInputs = (window.__emailInputs || 0) + 1;
            if (window.__emailInputs > 1) {
              this.value = '';
            }
          ">
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert updated["state"] == "submit_only"
    assert result["unknown_fields"] == 0
    assert artifacts["repair"]["status"] == "repaired"
    assert artifacts["repair"]["attempts"] == 1
    assert artifacts["repair"]["retry_attempts"][0]["rebound"] is True
    assert artifacts["repair"]["retry_attempts"][0]["second_validation"]["status"] == "validation_clean"
    assert artifacts["repair"]["retry_attempts"][0]["policy"]["outcome"] == "ALLOW"
    assert "email" in artifacts["repair"]["skipped_already_verified"]
    assert artifacts["validation"]["checked_postconditions"] == 2
    assert artifacts["journey"]["steps"][0]["validation"]["status"] == "validation_clean"
    assert artifacts["review"]["fields_autofilled"] == 2


def test_application_execution_retry_budget_exhaustion_blocks_terminally(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("APPLICATION_REPAIR_RETRY_BUDGET", "0")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate"})
    db.upsert_job_posting(make_job(external_id="repair-budget-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required oninput="this.value = ''">
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert updated["state"] == "needs_user_input"
    assert result["unknown_fields"] == 0
    assert artifacts["validation"]["status"] == "validation_failed"
    assert artifacts["repair"]["status"] == "failed_terminal"
    assert artifacts["repair"]["terminal_blocker"] == "retry_budget_exhausted"
    assert "retry_budget_exhausted" in artifacts["repair"]["reason_codes"]


def test_application_execution_policy_blocks_retry_during_repair(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("APPLICATION_REPAIR_RETRY_BUDGET", "1")
    db.init_db()
    db.save_candidate_profile_payload(
        {
            "full_name": "Synthetic Candidate",
            "email": "candidate@example.test",
            "linkedin_url": "https://www.linkedin.com/in/synthetic",
        }
    )
    db.upsert_job_posting(make_job(external_id="policy-repair-block-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <div id="dynamic-holder">
            <label for="linkedin">LinkedIn profile *</label>
            <input id="linkedin" name="linkedin" type="url" required oninput="
              if (!window.__changedToPolicyControl) {
                window.__changedToPolicyControl = true;
                document.getElementById('dynamic-holder').innerHTML = `
                  <label for='linkedin'>Authorize background check</label>
                  <input id='linkedin' name='linkedin' required
                    oninput='window.__forbiddenFills = (window.__forbiddenFills || 0) + 1'>`;
              }
            ">
          </div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=False,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]
    attempt = artifacts["repair"]["retry_attempts"][0]

    assert updated["state"] == "needs_user_input"
    assert result["unknown_fields"] >= 1
    assert artifacts["repair"]["status"] == "failed_terminal"
    assert attempt["policy"]["outcome"] == "REVIEW_REQUIRED"
    assert attempt["reason"] == "legal_consent_reserved_for_user"
    assert attempt["policy"]["semantic_category"] == "background_check_authorization"
    assert attempt["status"] == "failed-terminal"
    assert artifacts["automation_metrics"]["submit_only_ready"] is False


def test_repair_policy_block_prevents_forbidden_retry() -> None:
    previous_action_plan = {
        "actions": [
            {
                "field_name": "background_check_authorization",
                "action_type": "check",
                "control_handle": {
                    "fingerprint": "old-background",
                    "logical_identity": {
                        "semantic_key": "background_check_authorization",
                        "label_norm": "background check authorization",
                        "type": "checkbox",
                        "required": True,
                    },
                },
            }
        ]
    }
    rescanned_action_plan = {
        "actions": [
            {
                "field_name": "background_check_authorization",
                "action_type": "check",
                "control_handle": {
                    "fingerprint": "new-background",
                    "logical_identity": {
                        "semantic_key": "background_check_authorization",
                        "label_norm": "background check authorization",
                        "type": "checkbox",
                        "required": True,
                    },
                },
            }
        ]
    }
    rescanned_schema = {
        "fields": [
            {
                "name": "background_check_authorization",
                "label": "Authorize background check",
                "type": "checkbox",
                "required": True,
                "fingerprint": "new-background",
                "logical_identity": {
                    "semantic_key": "background_check_authorization",
                    "label_norm": "background check authorization",
                    "type": "checkbox",
                    "required": True,
                },
            }
        ]
    }
    rescanned_mapping = {
        "answers": [
            {
                "field_name": "background_check_authorization",
                "label": "Authorize background check",
                "canonical_key": "background_check_authorization",
                "value": "yes",
                "field_type": "checkbox",
                "source": "approved_answer",
                "requires_confirmation": False,
            }
        ],
        "unknown_fields": [],
    }
    previous_step = _repair_step(
        schema={"fields": []},
        mapping={"answers": [], "unknown_fields": []},
        action_plan=previous_action_plan,
    )
    rescanned_step = _repair_step(
        schema=rescanned_schema,
        mapping=rescanned_mapping,
        action_plan=rescanned_action_plan,
    )

    async def run() -> dict:
        from playwright.async_api import async_playwright

        async def inspect_surface(**_):
            return rescanned_step

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(
                    """
                    <form>
                      <label><input name="background_check_authorization" type="checkbox" required
                        onclick="window.__forbiddenClicks = (window.__forbiddenClicks || 0) + 1">
                        Authorize background check
                      </label>
                    </form>
                    """
                )
                repair = await run_bounded_repair_loop(
                    page=page,
                    journey_engine=SimpleNamespace(inspect_surface=inspect_surface),
                    adapter=SimpleNamespace(),
                    capabilities=SimpleNamespace(),
                    current_step=previous_step,
                    html=await page.content(),
                    profile={},
                    answer_bank=[],
                    previous_validation_report={
                        "status": "validation_failed",
                        "issues": [
                            {
                                "field_name": "background_check_authorization",
                                "issue_type": "control_missing",
                                "message": "Control changed after first attempt.",
                            }
                        ],
                    },
                    fill_stability={"mutation_count": 1},
                    fill_result={"filled_fields": [], "skipped_fields": []},
                    resume_upload={"status": "not_applicable"},
                    dry_run=False,
                    timeout_ms=1000,
                    action_states={
                        "old-background": {
                            "status": "failed-recoverable",
                            "field_name": "background_check_authorization",
                            "reason": "control_missing",
                        }
                    },
                    progress=None,
                )
                clicks = await page.evaluate("() => window.__forbiddenClicks || 0")
                return {"repair": repair["repair_report"], "clicks": clicks}
            finally:
                await browser.close()

    result = asyncio.run(run())
    repair = result["repair"]

    assert repair["status"] == "failed_terminal"
    assert repair["retry_attempts"][0]["policy"]["outcome"] == "REVIEW_REQUIRED"
    assert repair["retry_attempts"][0]["reason"] == "legal_consent_reserved_for_user"
    assert repair["retry_attempts"][0]["policy"]["semantic_category"] == "background_check_authorization"
    assert repair["retry_attempts"][0]["status"] == "failed-terminal"
    assert result["clicks"] == 0


def test_click_approved_submit_control_is_policy_blocked() -> None:
    result = asyncio.run(click_approved_submit_control(None, timeout_ms=1))  # type: ignore[arg-type]

    assert result == {
        "status": "blocked",
        "reasons": ["final_submit_reserved_for_user"],
        "policy": "reserved_for_user",
    }


def test_application_execution_advances_safe_multistep_and_stops_at_submit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("APPLICATION_MAX_AUTO_STEPS", "3")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    apply_url = "https://careers.example.test/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="multistep-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "multistep-job"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="application">
          <section id="step-1">
            <label for="name">Full name *</label>
            <input id="name" name="name" required>
            <button type="button" onclick="document.getElementById('step-1').style.display='none';document.getElementById('step-2').style.display='block'">Next</button>
          </section>
          <section id="step-2" style="display:none">
            <label for="email">Email *</label>
            <input id="email" name="email" type="email" required>
            <button type="submit">Submit application</button>
          </section>
        </form>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert result["fields_autofilled"] == 2
    assert result["unknown_fields"] == 0
    assert updated["state"] == "submit_only"
    assert artifacts["forbidden_submit_controls"] == [
        {"tag": "button", "text": "Submit application", "action_policy": "forbidden"}
    ]
    assert artifacts["automation_metrics"]["steps_completed_without_human"] == 1
    assert artifacts["automation_metrics"]["step_advance_success_rate"] == 1.0
    assert artifacts["automation_metrics"]["submit_only_ready"] is True
    assert artifacts["human_intervention"]["status"] == "submit_only"
    assert artifacts["automation_metrics"]["submit_only_intervention_rate"] == 1.0
    assert artifacts["journey"]["step_transitions"][0]["result"]["status"] == "advanced"


def test_application_execution_opens_generic_apply_cta_before_form_fill(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    apply_url = "https://careers.example.test/jobs/backend"
    db.upsert_job_posting(
        JobPosting(
            external_id="generic-landing-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "generic-landing-job"},
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
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = Path("tests/fixtures/generic_apply_landing.html").read_text(encoding="utf-8")

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )

    assert result["provider"] == "generic_form"
    assert result["fields_detected"] == 3
    assert result["resume_upload"]["status"] == "uploaded"
    assert result["unknown_fields"] == 0


def test_application_execution_blocks_when_generic_form_fields_are_not_detected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    apply_url = "https://careers.example.test/jobs/backend"
    db.upsert_job_posting(
        JobPosting(
            external_id="generic-empty-job",
            source="company_page",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "generic-empty-job"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic_form", "mode": "review_before_submit"})
    html = "<html><body><button type='button'>I'm interested</button></body></html>"

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(html)}",
            provider_hint="generic_form",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))

    assert result["provider"] == "generic_form"
    assert result["fields_detected"] == 0
    assert result["unknown_fields"] == 1
    assert updated["state"] == "needs_user_input"
    assert updated["unknown_fields_json"][0]["label"] == "No application form fields were detected."


def test_application_execution_marks_closed_posting_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    db.init_db()
    apply_url = "https://jobs.lever.co/acme/closed/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="closed-lever-job",
            source="lever",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Closed job.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Closed job.", apply_url),
            raw_payload={"id": "closed-lever-job"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "lever", "mode": "review_before_submit"})
    html = """
    <!doctype html>
    <html><body>
      <h1>Sorry, we couldn't find anything here</h1>
      <p>The job posting you're looking for might have closed, or it has been removed. (404 error).</p>
    </body></html>
    """

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

    assert result["reason"] == "posting_unavailable"
    assert result["blocked"] is False
    assert updated["state"] == "needs_user_input"
    assert updated["last_error"] == "Posting unavailable."


def test_application_execution_blocks_auto_submit_even_when_preconditions_pass(tmp_path, monkeypatch) -> None:
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

    assert result["auto_submit"]["status"] == "blocked"
    assert result["auto_submit"]["reasons"] == ["final_submit_reserved_for_user"]
    assert updated["state"] == "submit_only"
    assert application["status"] == "preparing"
    assert updated["artifacts_json"]["auto_submit"]["status"] == "blocked"


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


def test_application_execution_fills_application_form_opened_in_popup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "worker.db")
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("APPLICATION_BROWSER_HANDOFF", "0")
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})
    db.upsert_job_posting(make_job(external_id="popup-apply-job"), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    session = db.create_application_session({"job_id": job_id, "provider": "generic", "mode": "review_before_submit"})
    popup_html = (
        "<!doctype html><html><body><form id='application'>"
        "<label for='name'>Full name *</label><input id='name' name='name' required>"
        "<label for='email'>Email *</label><input id='email' name='email' type='email' required>"
        "<button type='submit'>Submit application</button></form></body></html>"
    )
    launcher_html = f"""
    <!doctype html>
    <html>
      <body>
        <h1>Backend Engineer</h1>
        <button onclick="const popup = window.open('about:blank', '_blank'); popup.document.write(`{popup_html}`); popup.document.close();">Apply now</button>
      </body>
    </html>
    """

    result = asyncio.run(
        run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=f"data:text/html,{quote(launcher_html)}",
            provider_hint="generic",
            dry_run=True,
        )
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated["artifacts_json"]

    assert any(step["action"] == "opened_popup" for step in result["navigation"])
    assert result["fields_autofilled"] == 2
    assert result["unknown_fields"] == 0
    assert updated["state"] == "submit_only"
    assert artifacts["journey"]["surface"]["kind"] == "popup"
    assert artifacts["automation_metrics"]["submit_only_ready"] is True
    assert artifacts["automation_metrics"]["popup_handling_success_rate"] == 1.0


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


async def _detect_access_issue_for_html(html: str) -> str | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            await page.wait_for_timeout(500)
            return await _detect_page_access_issue(page, page.url, await page.content())
        finally:
            await browser.close()


async def _detect_step_transition_for_html(html: str) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            return await detect_safe_step_transition_controls(page)
        finally:
            await browser.close()


def _repair_step(*, schema: dict, mapping: dict, action_plan: dict):
    return SimpleNamespace(
        schema=schema,
        mapping=mapping,
        action_plan=SimpleNamespace(to_dict=lambda: action_plan),
        surface=SimpleNamespace(),
        browser_surface={},
        surfaces=[],
        to_dict=lambda: {
            "schema": schema,
            "mapping": mapping,
            "action_plan": action_plan,
            "surface": {},
            "browser_surface": {},
            "surfaces": [],
        },
    )


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
