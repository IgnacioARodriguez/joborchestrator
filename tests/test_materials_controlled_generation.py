from __future__ import annotations

import json

import pytest

from joborchestrator.intelligence import llm_application_materials as llm
from joborchestrator.intelligence.materials_context import (
    build_generation_context,
    forbidden_aliases_absent_from_generation_context,
)
from joborchestrator.intelligence.materials_cv_ir import (
    AtsCvPlan,
    CandidateCvIR,
    CandidateIdentity,
    EducationEntry,
    EvidenceBullet,
    EvidenceFact,
    ExperienceRole,
    RolePlan,
    SkillEvidence,
    render_ats_cv,
    validate_ats_cv_plan,
)
from joborchestrator.intelligence.materials_keywords import derive_keywords_used
from joborchestrator.intelligence.materials_kit import parse_autofill, render_autofill
from joborchestrator.intelligence.materials_language import detect_job_language, language_mismatch
from joborchestrator.intelligence.materials_repair import (
    build_repair_directive,
    deterministic_repair,
    frozen_field_regressions,
    repair_prompt_payload,
)
from joborchestrator.intelligence.materials_routing import max_semantic_repairs, should_auto_generate_materials
from joborchestrator.intelligence.materials_validation import (
    issues_to_messages,
    validation_feedback_to_issues,
)


def test_materials_evidence_baseline_documents_packet_cases():
    with open("tests/fixtures/materials_evidence_baseline.json", encoding="utf-8") as handle:
        baseline = json.load(handle)

    assert baseline["records_found"] == 29
    assert baseline["validation_error_themes"]["overcompressed_cv"] == 10
    case_ids = {case["operation_id"] for case in baseline["representative_cases"]}
    assert {37, 41, 60, 62, 63}.issubset(case_ids)


def test_keywords_used_are_derived_from_rendered_cv():
    cv = "Technical Skills\nPython, REST APIs, PostgreSQL\nExperience\nBuilt API integrations."

    assert derive_keywords_used(cv, ["Python", "REST API", "PostgreSQL", "Kubernetes"]) == [
        "Python",
        "REST API",
        "PostgreSQL",
    ]


def test_sql_does_not_match_nosql():
    assert derive_keywords_used("Designed NoSQL storage with MongoDB.", ["SQL", "NoSQL"]) == ["NoSQL"]


def test_validation_feedback_has_stable_issue_codes():
    issues = validation_feedback_to_issues(
        "keywords_used contains terms not present as normalized token-aware phrases in ats_cv_text: API Design. "
        "Add the truthful keyword phrase to ats_cv_text or remove it from keywords_used.; "
        "Fiction Express is missing canonical role technologies: Redis."
    )

    assert [issue.code for issue in issues] == ["KEYWORD_METADATA_MISMATCH", "MISSING_CANONICAL_ROLE_TECH"]
    assert "KEYWORD_METADATA_MISMATCH in keywords_used" in issues_to_messages(issues)[0]


def test_retry_cannot_change_frozen_fields():
    previous = {"ats_cv_text": "old cv", "cover_letter": "old cover", "recruiter_message": "old note"}
    directive = build_repair_directive(
        previous,
        validation_feedback_to_issues("application materials use overconfident tone for AVOID ranking: eager to"),
    )
    repaired = {"ats_cv_text": "changed cv", "cover_letter": "new cover", "recruiter_message": "new note"}

    assert "ats_cv_text" in directive.frozen_fields
    assert frozen_field_regressions(previous, repaired, directive.frozen_fields) == ["ats_cv_text"]


def test_repair_receives_previous_response():
    previous = {"ats_cv_text": "old cv", "cover_letter": "old cover", "recruiter_message": "old note"}
    messages = llm._nvidia_contract_messages(
        "Return JSON.",
        {"job": {"title": "Backend Engineer"}},
        "application materials use overconfident tone for AVOID ranking: eager to",
        previous_response=previous,
    )

    assert "previous_response" in messages[1]["content"]
    assert "all_other_fields_must_remain_byte_for_byte_identical" in messages[1]["content"]


def test_renderer_preserves_all_role_headers():
    cv_ir = _cv_ir()

    rendered = render_ats_cv(cv_ir)

    assert "Backend Developer | Fiction Express | April 2025 - March 2026" in rendered
    assert "Full Stack Developer | Talan | October 2022 - April 2025" in rendered


def test_renderer_preserves_titles_companies_and_dates():
    rendered = render_ats_cv(_cv_ir())

    assert "Backend Developer | Fiction Express" in rendered
    assert "Full Stack Developer | Talan" in rendered
    assert "October 2022 - April 2025" in rendered


def test_renderer_restores_minimum_role_bullets():
    cv_ir = _cv_ir()
    plan = AtsCvPlan(role_plans=[RolePlan(role_id="role_fiction", selected_bullet_ids=["fiction_b1"])])

    rendered = render_ats_cv(cv_ir, plan, min_bullets_per_role=2)

    assert "- Built analytics APIs." in rendered
    assert "- Improved data reliability." in rendered


def test_renderer_injects_canonical_role_technologies():
    rendered = render_ats_cv(_cv_ir())

    assert "Technologies: Python, Django, REST APIs, SQL, MongoDB, Redis" in rendered


def test_renderer_rejects_unknown_evidence_ids():
    errors = validate_ats_cv_plan(
        _cv_ir(),
        AtsCvPlan(role_plans=[RolePlan(role_id="role_fiction", selected_bullet_ids=["missing_bullet"])]),
    )

    assert errors == ["role role_fiction references unknown bullet ids: missing_bullet"]


def test_unsupported_role_technology_is_not_rendered():
    cv_ir = _cv_ir()

    rendered = render_ats_cv(cv_ir)

    fiction_block = rendered.split("Full Stack Developer | Talan")[0]
    assert "FastAPI" not in fiction_block


def test_forbidden_aliases_are_absent_from_generation_context():
    context = build_generation_context(
        {
            "job": {"company": "Acme", "title": "Backend", "description_text": "Build Python APIs"},
            "ats_fit_analysis": {"supported_keywords": ["Python"]},
            "ranking_constraints": {
                "avoid_overclaiming_aliases": {"Kubernetes": ["Kubernetes", "EKS"]},
            },
        }
    )

    assert forbidden_aliases_absent_from_generation_context(context, {"Kubernetes": ["Kubernetes", "EKS"]})


def test_summary_claims_require_evidence_ids():
    plan = AtsCvPlan(summary_lines=[type("Line", (), {"text": "Unsupported claim", "evidence_ids": []})()])
    assert validate_ats_cv_plan(_cv_ir(), plan) == ["summary line must include at least one evidence id"]
    bad = AtsCvPlan(summary_lines=[type("Line", (), {"text": "Unsupported claim", "evidence_ids": ["missing"]})()])
    assert validate_ats_cv_plan(_cv_ir(), bad) == ["summary line references unknown evidence ids: missing"]


def test_language_matches_job_language():
    assert detect_job_language("ANALISTA PROGRAMADOR/A PYTHON", "Requisitos experiencia remoto") == "es"
    assert language_mismatch("Experiencia profesional en Python remoto", "es") is False


def test_autofill_rejects_json_encoded_object_string():
    with pytest.raises(ValueError, match="JSON-encoded string"):
        parse_autofill('{"core_pitch": "Python backend"}')

    rendered = render_autofill(parse_autofill({"core_pitch": "Python backend", "application_caveats": ["Review gaps"]}))
    assert "Caveats: Review gaps" in rendered


def test_deterministic_repair_runs_before_semantic_retry():
    response = {"ats_cv_text": "Technical Skills\nPython and REST APIs", "keywords_used": ["Kubernetes"]}
    issues = validation_feedback_to_issues(
        "keywords_used contains terms not present as normalized token-aware phrases in ats_cv_text: Kubernetes."
    )

    repaired, remaining = deterministic_repair(response, issues, supported_keywords=["Python", "REST APIs", "Kubernetes"])

    assert repaired["keywords_used"] == ["Python", "REST APIs"]
    assert remaining == []


def test_semantic_retry_limit_is_one(monkeypatch):
    monkeypatch.setenv("MATERIALS_MAX_SEMANTIC_REPAIRS", "1")

    assert max_semantic_repairs() == 1


def test_repair_payload_lists_mutable_and_frozen_fields():
    previous = {"ats_cv_text": "cv", "cover_letter": "cover", "autofill_notes": "notes"}
    directive = build_repair_directive(
        previous,
        validation_feedback_to_issues("application_materials contains unsupported ranking avoid-overclaiming terms: Kubernetes."),
    )
    payload = repair_prompt_payload(directive)

    assert "cover_letter" in payload["only_these_fields_may_change"]
    assert "previous_response" in payload


def test_avoid_job_does_not_auto_generate_without_override():
    ranking = {"decision": "AVOID"}

    assert should_auto_generate_materials(ranking, override=False) is False
    assert should_auto_generate_materials(ranking, override=True) is True


def _cv_ir() -> CandidateCvIR:
    return CandidateCvIR(
        candidate=CandidateIdentity(name="Ignacio Rodriguez"),
        summary_facts=[EvidenceFact(id="fact_01", source_text="Backend developer with source-backed Python experience.")],
        skills=[
            SkillEvidence(id="skill_python", name="Python", source_text="Python"),
            SkillEvidence(id="skill_rest", name="REST APIs", source_text="REST APIs"),
        ],
        roles=[
            ExperienceRole(
                id="role_fiction",
                title="Backend Developer",
                company="Fiction Express",
                location=None,
                dates="April 2025 - March 2026",
                bullets=[
                    EvidenceBullet(id="fiction_b1", source_text="Built analytics APIs.", technologies=["Python"], mandatory=True),
                    EvidenceBullet(id="fiction_b2", source_text="Improved data reliability.", technologies=["SQL"]),
                ],
                canonical_technologies=["Python", "Django", "REST APIs", "SQL", "MongoDB", "Redis"],
            ),
            ExperienceRole(
                id="role_talan",
                title="Full Stack Developer",
                company="Talan",
                location=None,
                dates="October 2022 - April 2025",
                bullets=[
                    EvidenceBullet(id="talan_b1", source_text="Built dashboards for finance teams.", technologies=["React"], mandatory=True),
                    EvidenceBullet(id="talan_b2", source_text="Automated reporting workflows.", technologies=["Python"]),
                ],
                canonical_technologies=["Python", "Flask", "React", "JavaScript", "TypeScript", "SQL", "MySQL", "Docker", "Redis", "Git", "REST APIs"],
            ),
        ],
        education=[EducationEntry(id="education_01", source_text="Computer Science")],
        base_cv_text="source",
    )
