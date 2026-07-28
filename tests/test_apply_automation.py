from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from joborchestrator.application_sessions import validate_transition
from joborchestrator.automation.adapters import AdapterRegistry, GenericFormAdapter, GreenhouseAdapter, LeverAdapter
from joborchestrator.automation.answer_bank import classify_field, map_answers, normalize_question
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


def test_answer_bank_uses_explicitly_approved_sensitive_answers() -> None:
    mapping = map_answers(
        {
            "fields": [
                {
                    "name": "work_authorization",
                    "label": "Do you have permanent authorization to work for Warp in the U.S. or Canada?",
                    "type": "select",
                    "required": True,
                    "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes"}],
                }
            ]
        },
        {},
        [
            {
                "canonical_key": "work_authorization",
                "question_patterns": ["Do you have permanent authorization to work for Warp in the U.S. or Canada?"],
                "answer_type": "select",
                "value": "No",
                "source": "approved",
                "status": "approved",
                "sensitivity": "sensitive",
                "requires_confirmation": False,
            }
        ],
    )

    answer = mapping["answers"][0]
    assert answer["classification"] == "sensitive"
    assert answer["requires_confirmation"] is False
    assert answer["source"] == "approved_answer"
    assert mapping["unknown_fields"] == []
    assert safe_fill_plan(mapping) == [
        {
            "field_name": "work_authorization",
            "value": "no",
            "canonical_key": "work_authorization",
            "action_type": "select_option",
        }
    ]


def test_answer_bank_uses_question_patterns_for_unknown_safe_fields() -> None:
    mapping = map_answers(
        {"fields": [{"name": "remote_pref", "label": "Where would you prefer to work from?", "required": True}]},
        {},
        [
            {
                "canonical_key": "preferred_location",
                "question_patterns": ["Where would you prefer to work from?"],
                "answer_type": "select",
                "value": "Remote",
                "source": "approved",
                "status": "approved",
                "sensitivity": "public",
                "requires_confirmation": False,
            }
        ],
    )

    answer = mapping["answers"][0]
    assert answer["canonical_key"] == "preferred_location"
    assert answer["value"] == "Remote"
    assert answer["source"] == "approved_answer"
    assert answer["match_strategy"] == "question_pattern_exact"
    assert mapping["unknown_fields"] == []


def test_answer_bank_does_not_use_generated_or_expired_answers() -> None:
    mapping = map_answers(
        {"fields": [{"name": "custom", "label": "Tell us about your favorite project", "required": True}]},
        {},
        [
            {
                "canonical_key": "favorite_project",
                "question_patterns": ["Tell us about your favorite project"],
                "value": "Generated answer",
                "source": "generated",
                "status": "proposed",
                "sensitivity": "public",
                "requires_confirmation": False,
            },
            {
                "canonical_key": "old_project",
                "question_patterns": ["Tell us about your favorite project"],
                "value": "Expired answer",
                "source": "approved",
                "status": "expired",
                "sensitivity": "public",
                "requires_confirmation": False,
            },
        ],
    )

    assert mapping["answers"][0]["value"] is None
    assert mapping["answers"][0]["requires_confirmation"] is True
    assert mapping["unknown_fields"][0]["name"] == "custom"


def test_question_normalization_removes_accents_punctuation_and_repeated_spaces() -> None:
    assert normalize_question("  Teléfono -- principal? ") == "telefono principal"


def test_greenhouse_detection_schema_and_dry_run_fill() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    adapter = GreenhouseAdapter()
    schema = adapter.extract_form_schema_html(html)
    mapping = adapter.map_answers(schema, {"email": "me@example.com", "full_name": "Ignacio Rodriguez"}, [])
    fill = adapter.fill_fields_html(html, mapping, dry_run=True)
    review = adapter.prepare_review(schema, mapping, fill)

    assert adapter.detect_html(html)
    assert len(schema["fields"]) >= 8
    assert fill.ok is True
    assert fill.data["dry_run"] is True
    assert review["fields_autofilled"] >= 2
    assert {field["name"] for field in review["unknown_fields"]} >= {"salary", "resume"}


def test_adapter_registry_prefers_greenhouse() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    assert AdapterRegistry().detect(html).provider == "greenhouse"


def test_adapter_registry_detects_lever() -> None:
    html = Path("tests/fixtures/lever_application.html").read_text(encoding="utf-8")

    assert LeverAdapter().detect_html(html, {"apply_url": "https://jobs.lever.co/acme/backend/apply"})
    assert AdapterRegistry().detect(html, {"apply_url": "https://jobs.lever.co/acme/backend/apply"}).provider == "lever"


def test_adapter_registry_uses_generic_form_before_assisted_fallback() -> None:
    html = Path("tests/fixtures/generic_application.html").read_text(encoding="utf-8")

    assert GenericFormAdapter().detect_html(html)
    assert AdapterRegistry().detect(html, {"apply_url": "https://careers.example.test/apply"}).provider == "generic_form"


def test_adapter_registry_uses_generic_form_for_apply_landing_page() -> None:
    html = Path("tests/fixtures/generic_apply_landing.html").read_text(encoding="utf-8")

    assert AdapterRegistry().detect(html, {"apply_url": "https://careers.example.test/jobs/backend"}).provider == "generic_form"


def test_provider_capabilities_are_explicit_and_do_not_claim_submit() -> None:
    registry = AdapterRegistry()
    greenhouse = registry.capabilities("greenhouse")
    lever = registry.capabilities("lever")
    generic_form = registry.capabilities("generic_form")
    linkedin = registry.capabilities("linkedin_easy_apply")

    assert not isinstance(greenhouse, list)
    assert greenhouse.provider == "greenhouse"
    assert greenhouse.can_detect_fields is True
    assert greenhouse.can_fill_text_fields is True
    assert greenhouse.can_fill_selects is True
    assert greenhouse.can_fill_radios is True
    assert greenhouse.can_fill_checkboxes is True
    assert greenhouse.can_upload_resume is True
    assert greenhouse.can_resume_browser_session is True
    assert greenhouse.can_submit is False
    assert not isinstance(lever, list)
    assert lever.can_detect_fields is True
    assert lever.can_fill_text_fields is True
    assert lever.can_fill_selects is True
    assert lever.can_fill_radios is True
    assert lever.can_fill_checkboxes is True
    assert lever.can_upload_resume is True
    assert lever.can_resume_browser_session is True
    assert lever.can_submit is False
    assert not isinstance(generic_form, list)
    assert generic_form.can_detect_fields is True
    assert generic_form.can_fill_text_fields is True
    assert generic_form.can_upload_resume is True
    assert generic_form.can_submit is False
    assert not isinstance(linkedin, list)
    assert linkedin.requires_login is True
    assert linkedin.can_submit is False


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
        {"field_name": "first_name", "value": "Ignacio Rodriguez", "canonical_key": "full_name", "action_type": "fill_text"},
        {"field_name": "email", "value": "me@example.com", "canonical_key": "email", "action_type": "fill_text"},
    ]


def test_safe_fill_plan_requires_exact_select_match() -> None:
    mapping = {
        "answers": [
            {
                "field_name": "location",
                "canonical_key": "preferred_location",
                "value": "Madrid",
                "field_type": "select",
                "options": [{"value": "remote", "label": "Remote"}, {"value": "madrid", "label": "Madrid"}],
                "requires_confirmation": False,
            },
            {
                "field_name": "ambiguous",
                "canonical_key": "preferred_location",
                "value": "Remote",
                "field_type": "select",
                "options": [{"value": "remote-1", "label": "Remote"}, {"value": "remote-2", "label": "Remote"}],
                "requires_confirmation": False,
            },
        ]
    }

    assert safe_fill_plan(mapping) == [
        {"field_name": "location", "value": "madrid", "canonical_key": "preferred_location", "action_type": "select_option"}
    ]
