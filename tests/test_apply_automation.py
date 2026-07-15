from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from joborchestrator.application_sessions import validate_transition
from joborchestrator.automation.adapters import AdapterRegistry, GreenhouseAdapter
from joborchestrator.automation.answer_bank import classify_field, map_answers
from joborchestrator.automation.executor import find_apply_links, safe_fill_plan
from joborchestrator.priority import compute_priority


def test_priority_uses_freshness_and_recruiter_advantage() -> None:
    job = {
        "title": "Solutions Engineer",
        "company": "Acme",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
        "first_seen_at": (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds"),
        "recruiter_profile_url": "https://linkedin.com/in/recruiter",
        "is_active": 1,
    }

    priority = compute_priority(job, {"final_score": 82})

    assert priority.priority_score >= 70
    assert priority.freshness_score == 100
    assert priority.freshness_bucket == "fresh"
    assert priority.recruiter_advantage_score == 90
    assert priority.next_action in {"Prepare", "Review", "Apply now"}


def test_priority_penalizes_stale_jobs_without_changing_fit() -> None:
    now = datetime(2026, 7, 15, 12, 0, 0)
    base_job = {
        "title": "Backend Engineer",
        "company": "Acme",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
        "is_active": 1,
    }

    fresh = compute_priority({**base_job, "first_seen_at": "2026-07-15T10:00:00"}, {"final_score": 90}, now=now)
    stale = compute_priority({**base_job, "first_seen_at": "2026-07-01T10:00:00"}, {"final_score": 90}, now=now)

    assert stale.freshness_bucket == "stale"
    assert stale.fit_score == fresh.fit_score
    assert stale.priority_score < fresh.priority_score


def test_application_session_transition_validation_and_idempotency() -> None:
    transition = validate_transition("created", "created")

    assert transition.idempotent is True
    assert validate_transition("created", "preflight").to_state == "preflight"
    with pytest.raises(ValueError):
        validate_transition("created", "submitted")


def test_answer_bank_marks_sensitive_fields_unknown_without_approved_answer() -> None:
    canonical, classification = classify_field("Expected salary")
    mapping = map_answers(
        {"fields": [{"name": "salary", "label": "Expected salary", "required": True}]},
        {"email": "me@example.com"},
        [],
    )

    assert canonical == "salary"
    assert classification == "sensitive"
    assert mapping["answers"][0]["requires_confirmation"] is True
    assert mapping["unknown_fields"][0]["name"] == "salary"


def test_greenhouse_detection_schema_and_dry_run_fill() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    adapter = GreenhouseAdapter()
    schema = adapter.extract_form_schema_html(html)
    mapping = adapter.map_answers(schema, {"email": "me@example.com", "full_name": "Ignacio Rodriguez"}, [])
    fill = adapter.fill_fields_html(html, mapping, dry_run=True)
    review = adapter.prepare_review(schema, mapping, fill)

    assert adapter.detect_html(html)
    assert len(schema["fields"]) == 5
    assert fill.ok is True
    assert fill.data["dry_run"] is True
    assert review["fields_autofilled"] == 2
    assert {field["name"] for field in review["unknown_fields"]} >= {"salary", "resume"}


def test_adapter_registry_prefers_greenhouse() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    assert AdapterRegistry().detect(html).provider == "greenhouse"


def test_external_apply_intermediate_links_are_detected() -> None:
    html = """
    <html>
      <body>
        <a href="/jobs/123">Job details</a>
        <a href="/jobs/123/apply">Apply now</a>
        <a href="https://boards.greenhouse.io/acme/jobs/123" aria-label="Apply for this role">Continue</a>
      </body>
    </html>
    """

    links = find_apply_links(html, "https://careers.example.com/jobs/123")

    assert links == [
        {"url": "https://careers.example.com/jobs/123/apply", "text": "Apply now"},
        {"url": "https://boards.greenhouse.io/acme/jobs/123", "text": "Continue Apply for this role"},
    ]


def test_safe_fill_plan_only_includes_non_sensitive_confirmed_answers() -> None:
    mapping = {
        "answers": [
            {"field_name": "first_name", "canonical_key": "full_name", "value": "Ignacio Rodriguez", "requires_confirmation": False},
            {"field_name": "email", "canonical_key": "email", "value": "me@example.com", "requires_confirmation": False},
            {"field_name": "salary", "canonical_key": "salary", "value": "100000", "requires_confirmation": True},
            {"field_name": "custom", "canonical_key": None, "value": "something", "requires_confirmation": False},
        ]
    }

    assert safe_fill_plan(mapping) == [
        {"field_name": "first_name", "value": "Ignacio Rodriguez", "canonical_key": "full_name"},
        {"field_name": "email", "value": "me@example.com", "canonical_key": "email"},
    ]
