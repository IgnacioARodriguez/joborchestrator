from __future__ import annotations

from joborchestrator.intelligence.materials_context import build_generation_context
from joborchestrator.intelligence.materials_controlled_pipeline import build_controlled_ats_cv
from joborchestrator.intelligence.materials_cv_ir import (
    AtsCvPlan,
    RolePlan,
    parse_candidate_cv_ir,
    render_ats_cv,
)
from joborchestrator.intelligence.materials_cv_policy import required_bullets_for_role
from joborchestrator.intelligence.materials_cv_semantics import validate_rendered_cv_against_ir
from joborchestrator.intelligence.materials_routing import (
    materials_routing_snapshot,
    resolve_cv_pipeline,
)


BASE_CV = """Ignacio Rodriguez
ignacio@example.com | Malaga, Spain

Professional Summary
Backend developer with Python API experience.

Technical Skills
Python, Django, REST APIs, PostgreSQL, Redis, Docker

Professional Experience
Backend Developer April 2025 - March 2026
Fiction Express
- Built analytics APIs with Python.
- Improved reporting endpoints.
- Added data-quality checks.
- Reduced support incidents.
- Documented operational workflows.
- Improved Redis-backed reliability.
- Added product analytics.
- Supported release validation.
- Coordinated requirements with product.
- Improved API observability.
- Maintained MongoDB integrations.
Technologies: Python, Django, REST APIs, PostgreSQL, Redis

Full Stack Developer October 2022 - April 2025
Talan Consulting
- Built Flask services.
- Implemented SQL dashboards.
- Added React interfaces.
- Integrated Redis workflows.
- Improved API monitoring.
- Supported Docker deployments.
Technologies: Python, Flask, SQL, React, Redis, Docker

Education
Backend Development Bootcamp
""".strip()


def test_parser_has_one_behavior_for_colon_and_bare_headings() -> None:
    bare = BASE_CV.replace("Professional Experience", "Career Journey")
    colon = BASE_CV.replace("Professional Experience", "Career Journey:")

    bare_ir = parse_candidate_cv_ir(bare, ["Python", "REST APIs"])
    colon_ir = parse_candidate_cv_ir(colon, ["Python", "REST APIs"])

    assert [role.company for role in bare_ir.roles] == ["Fiction Express", "Talan Consulting"]
    assert [role.company for role in colon_ir.roles] == ["Fiction Express", "Talan Consulting"]


def test_rendered_inline_headers_round_trip_to_same_roles() -> None:
    source = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "Redis"])
    rendered = render_ats_cv(source)
    generated = parse_candidate_cv_ir(rendered, ["Python", "REST APIs", "Redis"])

    assert [(role.title, role.company, role.dates) for role in generated.roles] == [
        (role.title, role.company, role.dates) for role in source.roles
    ]


def test_renderer_and_validator_share_density_policy() -> None:
    source = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "Redis"])
    plan = AtsCvPlan(
        role_plans=[
            RolePlan(
                role_id=source.roles[0].id,
                selected_bullet_ids=[source.roles[0].bullets[0].id],
            )
        ]
    )

    rendered = render_ats_cv(source, plan)
    generated = parse_candidate_cv_ir(rendered, ["Python", "REST APIs", "Redis"])

    assert len(generated.roles[0].bullets) == required_bullets_for_role(0, 11)
    assert validate_rendered_cv_against_ir(source, rendered) == []


def test_profile_skills_keep_technical_skills_section_for_unrelated_job() -> None:
    result = build_controlled_ats_cv(
        BASE_CV,
        [],
        canonical_skills=["Python", "Django", "PostgreSQL", "Docker"],
        planner_response={"summary_lines": [], "skill_ids": [], "role_plans": []},
    )

    assert "Technical Skills" in result["ats_cv_text"]
    assert "Python" in result["ats_cv_text"]
    assert result["_generation_metadata"]["selected_pipeline"] == "controlled_cv"


def test_semantic_validator_detects_moved_or_added_role_technology() -> None:
    source = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "Redis", "Kubernetes"])
    rendered = render_ats_cv(source).replace(
        "Technologies: Python, Flask, SQL, React, Redis, Docker",
        "Technologies: Python, Flask, SQL, React, Redis, Docker, Kubernetes",
    )

    problems = validate_rendered_cv_against_ir(source, rendered)

    assert any("unsupported role-specific technologies: Kubernetes" in problem for problem in problems)


def test_generation_context_contains_requirement_evidence_without_forbidden_aliases() -> None:
    context = build_generation_context(
        {
            "job": {
                "company": "Acme",
                "title": "Backend Engineer",
                "description_text": "Build Python APIs and unsupported secret-tool workflows.",
            },
            "ranking": {
                "decision": "APPLY_WITH_TAILORED_CV",
                "recommended_application_angle": "Lead with Python APIs; do not claim secret-tool.",
                "evidence": {
                    "central_requirements": ["Python APIs", "secret-tool"],
                    "strong_matches": ["Python"],
                    "partial_matches": ["API observability"],
                    "missing_requirements": ["secret-tool"],
                },
            },
            "ranking_constraints": {
                "avoid_overclaiming_aliases": {"secret-tool": ["secret-tool"]},
            },
            "ats_fit_analysis": {"supported_keywords": ["Python", "APIs"]},
        }
    )

    assert context["requirement_evidence"]["strong_matches"] == ["Python"]
    assert "description_text" in context["job"]
    assert "secret-tool" not in str(context)


def test_explicit_routing_is_not_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("MATERIALS_CONTROLLED_CV_ENABLED", "1")
    monkeypatch.setenv("MATERIALS_NVIDIA_PLANNER_ENABLED", "1")

    assert resolve_cv_pipeline("legacy") == "legacy_freeform"
    assert resolve_cv_pipeline("controlled") == "controlled_cv"
    assert materials_routing_snapshot("legacy")["requested_cv_strategy"] == "legacy"
    assert materials_routing_snapshot("legacy")["selected_pipeline"] == "legacy_freeform"
