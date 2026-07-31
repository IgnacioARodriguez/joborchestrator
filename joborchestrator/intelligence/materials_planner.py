from __future__ import annotations

from dataclasses import asdict
from typing import Any

from joborchestrator.intelligence.materials_context import build_generation_context
from joborchestrator.intelligence.materials_cv_ir import (
    AtsCvPlan,
    CandidateCvIR,
    RolePlan,
    SummaryLinePlan,
    validate_ats_cv_plan,
)


def build_cv_planner_context(full_payload: dict[str, Any], cv_ir: CandidateCvIR) -> dict[str, Any]:
    context = build_generation_context(full_payload)
    context["cv_ir"] = {
        "summary_facts": [asdict(fact) for fact in cv_ir.summary_facts],
        "skills": [asdict(skill) for skill in cv_ir.skills],
        "roles": [
            {
                "id": role.id,
                "title": role.title,
                "company": role.company,
                "location": role.location,
                "dates": role.dates,
                "bullets": [asdict(bullet) for bullet in role.bullets],
                "canonical_technologies": role.canonical_technologies,
            }
            for role in cv_ir.roles
        ],
        "education": [asdict(entry) for entry in cv_ir.education],
        "human_review_required": cv_ir.human_review_required,
        "parse_warnings": cv_ir.parse_warnings,
    }
    return context


def ats_cv_plan_from_response(response: dict[str, Any]) -> AtsCvPlan:
    return AtsCvPlan(
        summary_lines=[
            SummaryLinePlan(
                text=str(item.get("text") or "").strip(),
                evidence_ids=[str(value) for value in item.get("evidence_ids") or []],
            )
            for item in response.get("summary_lines") or []
            if isinstance(item, dict)
        ],
        skill_ids=[str(value) for value in response.get("skill_ids") or []],
        role_plans=[
            RolePlan(
                role_id=str(item.get("role_id") or ""),
                selected_bullet_ids=[str(value) for value in item.get("selected_bullet_ids") or []],
            )
            for item in response.get("role_plans") or []
            if isinstance(item, dict)
        ],
    )


def validate_planner_response(cv_ir: CandidateCvIR, response: dict[str, Any]) -> list[str]:
    plan = ats_cv_plan_from_response(response)
    errors = validate_ats_cv_plan(cv_ir, plan)
    if "ats_cv_text" in response:
        errors.append("planner response must not include ats_cv_text")
    if "keywords_used" in response:
        errors.append("planner response must not include keywords_used")
    return errors
