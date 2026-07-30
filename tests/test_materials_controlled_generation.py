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
from joborchestrator.intelligence.materials_planner import (
    build_cv_planner_context,
    validate_planner_response,
)
from joborchestrator.intelligence.materials_repair import (
    build_repair_directive,
    deterministic_repair,
    frozen_field_regressions,
    repair_prompt_payload,
)
from joborchestrator.intelligence.materials_routing import max_semantic_repairs, should_auto_generate_materials
from joborchestrator.intelligence.materials_controlled_pipeline import build_controlled_ats_cv
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


def test_combined_generation_metadata_preserves_stage_attempts():
    metadata = llm._combined_generation_metadata(
        [
            {"_generation_metadata": {"stage": "cv_render", "validation_attempts": 1, "validation_errors": []}},
            {
                "_generation_metadata": {
                    "stage": "kit_generation",
                    "validation_attempts": 2,
                    "validation_errors": ["recruiter_message is generic"],
                }
            },
        ]
    )

    assert metadata["validation_attempts"] == 3
    assert [attempt["stage"] for attempt in metadata["stage_attempts"]] == ["cv_render", "kit_generation"]
    assert metadata["stage_attempts"][1]["attempt_number"] == 2


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


def test_deterministic_repair_removes_forbidden_aliases_from_kit_fields():
    response = {
        "recruiter_message": "Hi Acme, AWS Lambda experience may be useful.",
        "cover_letter": "I would discuss DynamoDB and API Gateway only if relevant.",
        "autofill": {"core_pitch": "Mention Serverless Architecture cautiously.", "application_caveats": ["Avoid AWS Lambda claims."]},
        "autofill_notes": "Do not claim AWS CDK directly.",
    }
    issues = validation_feedback_to_issues(
        "application_materials contains unsupported ranking avoid-overclaiming terms: "
        "Serverless Architecture (AWS Lambda, DynamoDB, API Gateway, AWS CDK)."
    )

    repaired, remaining = deterministic_repair(response, issues, supported_keywords=[])
    repaired_text = json.dumps(repaired, ensure_ascii=False)

    assert remaining == []
    assert "AWS Lambda" not in repaired_text
    assert "DynamoDB" not in repaired_text
    assert "API Gateway" not in repaired_text
    assert "AWS CDK" not in repaired_text
    assert "some target stack items are not directly evidenced" in repaired_text


def test_deterministic_repair_does_not_replace_alias_inside_larger_token():
    response = {"cover_letter": "NoSQL storage experience is supported; SQL is not direct here."}
    issues = validation_feedback_to_issues(
        "application_materials contains unsupported ranking avoid-overclaiming terms: SQL."
    )

    repaired, remaining = deterministic_repair(response, issues, supported_keywords=[])

    assert remaining == []
    assert "NoSQL" in repaired["cover_letter"]
    assert "SQL is not direct" not in repaired["cover_letter"]


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


def test_nvidia_planner_response_rejects_final_cv_and_unknown_ids():
    errors = validate_planner_response(
        _cv_ir(),
        {
            "ats_cv_text": "Should not be here",
            "keywords_used": ["Python"],
            "summary_lines": [{"text": "Backend", "evidence_ids": ["missing"]}],
        },
    )

    assert "summary line references unknown evidence ids: missing" in errors
    assert "planner response must not include ats_cv_text" in errors
    assert "planner response must not include keywords_used" in errors


def test_planner_context_uses_cv_ir_and_compact_generation_context():
    context = build_cv_planner_context(
        {
            "job": {"company": "Acme", "title": "Backend Engineer", "description_text": "Build Python APIs."},
            "ats_fit_analysis": {"supported_keywords": ["Python"]},
        },
        _cv_ir(),
    )

    assert context["job"]["company"] == "Acme"
    assert context["cv_ir"]["roles"][0]["id"] == "role_fiction"
    assert "base_cv" not in context


def test_controlled_pipeline_renders_cv_without_freeform_generation():
    result = build_controlled_ats_cv(
        _base_cv_text(),
        ["Python", "REST APIs", "Redis"],
        planner_response={
            "summary_lines": [{"text": "Backend developer with Python API experience.", "evidence_ids": ["fact_01"]}],
            "skill_ids": ["skill_python"],
            "role_plans": [],
        },
    )

    assert "Professional Experience" in result["ats_cv_text"]
    assert "Technologies: Python, REST APIs, Redis" in result["ats_cv_text"]
    assert result["keywords_used"] == ["Python", "REST APIs", "Redis"]
    assert result["_generation_metadata"]["pipeline"] == "controlled_cv"


def test_nvidia_controlled_flags_use_planner_instead_of_freeform_cv(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials as llm

    planner_contexts = []
    monkeypatch.setenv("MATERIALS_CONTROLLED_CV_ENABLED", "1")
    monkeypatch.setenv("MATERIALS_NVIDIA_PLANNER_ENABLED", "1")
    monkeypatch.setattr(
        llm,
        "_materials_payload",
        lambda job, ranking: {
            "base_cv": {"text": _base_cv_text()},
            "job": {"company": "Acme", "title": "Backend Engineer", "description_text": "Build Python APIs."},
            "ats_fit_analysis": {"supported_keywords": ["Python", "REST APIs", "Redis"]},
            "ranking": {"decision": "APPLY_NOW"},
        },
    )
    monkeypatch.setattr(llm, "_call_nvidia_cv", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy CV path used")))

    def fake_contract_once(contract, payload, api_key, model, timeout, validation_feedback=None, previous_response=None):
        planner_contexts.append(payload)
        return {
            "summary_lines": [{"text": "Backend developer with Python API experience.", "evidence_ids": ["fact_01"]}],
            "skill_ids": ["skill_python"],
            "role_plans": [],
        }

    monkeypatch.setattr(llm, "_call_nvidia_contract_once", fake_contract_once)
    monkeypatch.setattr(
        llm,
        "_call_nvidia_kit",
        lambda *args, **kwargs: {
            "recruiter_message": "Hi Acme, Python API background may be relevant.",
            "cover_letter": "Dear team, my Python API background may support this Backend Engineer role with source-backed experience.",
            "autofill_notes": "Python backend profile",
            "_generation_metadata": {"validation_attempts": 1, "validation_errors": []},
        },
    )

    kit = llm.build_application_kit_with_nvidia({"title": "Backend Engineer"}, api_key="test-key")

    assert planner_contexts
    assert "cv_ir" in planner_contexts[0]
    assert "base_cv" not in planner_contexts[0]
    assert "Professional Experience" in kit["ats_cv_text"]
    assert "Technologies: Python, REST APIs, Redis" in kit["ats_cv_text"]
    assert kit["_generation_metadata"]["validation_errors"] == []


def test_invalid_nvidia_planner_plan_falls_back_to_renderer_defaults(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials as llm

    monkeypatch.setattr(
        llm,
        "_call_nvidia_cv_planner",
        lambda *args, **kwargs: {
            "summary_lines": [{"text": "Unsupported", "evidence_ids": ["missing"]}],
            "ats_cv_text": "not allowed",
        },
    )

    response = llm._call_nvidia_controlled_cv(
        {
            "base_cv": {"text": _base_cv_text()},
            "job": {"company": "Acme", "title": "Backend Engineer", "description_text": "Build Python APIs."},
            "ats_fit_analysis": {"supported_keywords": ["Python", "REST APIs", "Redis"]},
        },
        "test-key",
        "test-model",
        1.0,
    )

    assert "Professional Experience" in response["ats_cv_text"]
    assert "summary line references unknown evidence ids: missing" in response["_generation_metadata"]["validation_errors"]
    assert "planner response must not include ats_cv_text" in response["_generation_metadata"]["validation_errors"]


def test_openai_fallback_renders_controlled_cv_after_nvidia_cv_failure(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials as llm

    monkeypatch.setenv("MATERIALS_OPENAI_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setattr(
        llm,
        "_materials_payload",
        lambda job, ranking: {
            "base_cv": {"text": _base_cv_text()},
            "job": {"company": "Acme", "title": "Backend Engineer", "description_text": "Build Python APIs."},
            "ats_fit_analysis": {"supported_keywords": ["Python", "REST APIs", "Redis"]},
            "ranking": {"decision": "APPLY_NOW"},
        },
    )
    monkeypatch.setattr(
        llm,
        "_call_nvidia_cv",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            llm.LLMMaterialsError(
                "NVIDIA CV failed",
                generation_metadata={"validation_attempts": 2, "validation_errors": ["CV_TOO_SHORT"]},
            )
        ),
    )
    monkeypatch.setattr(
        llm,
        "_call_openai_cv_planner",
        lambda *args, **kwargs: {
            "summary_lines": [{"text": "Backend developer with Python API experience.", "evidence_ids": ["fact_01"]}],
            "skill_ids": ["skill_python"],
            "role_plans": [],
        },
    )
    monkeypatch.setattr(
        llm,
        "_call_nvidia_kit",
        lambda *args, **kwargs: {
            "recruiter_message": "Hi Acme, Python API background may be relevant.",
            "cover_letter": "Dear team, my Python API background may support this Backend Engineer role with source-backed experience.",
            "autofill_notes": "Python backend profile",
            "_generation_metadata": {"validation_attempts": 1, "validation_errors": []},
        },
    )

    kit = llm.build_application_kit_with_nvidia({"title": "Backend Engineer"}, api_key="nvidia-test-key")

    assert "Professional Experience" in kit["ats_cv_text"]
    assert "Technologies: Python, REST APIs, Redis" in kit["ats_cv_text"]
    assert "CV_TOO_SHORT" in kit["_generation_metadata"]["validation_errors"]


def test_openai_fallback_without_key_preserves_original_cv_failure(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials as llm

    monkeypatch.setenv("MATERIALS_OPENAI_FALLBACK_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    previous_error = llm.LLMMaterialsError(
        "NVIDIA CV failed",
        generation_metadata={"validation_attempts": 2, "validation_errors": ["CV_TOO_SHORT"]},
    )

    try:
        llm._call_openai_controlled_cv_fallback(
            {"base_cv": {"text": _base_cv_text()}, "ats_fit_analysis": {"supported_keywords": ["Python"]}},
            "gpt-test",
            1.0,
            previous_error=previous_error,
        )
    except llm.LLMMaterialsError as exc:
        metadata = exc.generation_metadata
    else:
        raise AssertionError("Expected fallback failure without OPENAI_API_KEY")

    assert metadata["validation_errors"] == ["CV_TOO_SHORT"]
    assert metadata["fallback_provider"] == "openai"
    assert metadata["fallback_error"] == "OPENAI_API_KEY is required"


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


def _base_cv_text() -> str:
    return """Ignacio Rodriguez
Contact line

Professional Experience
Backend Developer April 2025 - March 2026
Fiction Express
- Built analytics APIs with Python.
- Improved data reliability with Redis.
Technologies: Python, REST APIs, Redis

Education
Computer Science
"""
