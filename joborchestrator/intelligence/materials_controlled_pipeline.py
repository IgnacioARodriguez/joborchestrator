from __future__ import annotations

from typing import Any

from joborchestrator.intelligence.materials_cv_ir import AtsCvPlan, parse_candidate_cv_ir, render_ats_cv
from joborchestrator.intelligence.materials_keywords import derive_keywords_used
from joborchestrator.intelligence.materials_planner import ats_cv_plan_from_response, validate_planner_response


def build_controlled_ats_cv(
    base_cv_text: str,
    supported_keywords: list[str],
    *,
    planner_response: dict[str, Any] | None = None,
    min_bullets_per_role: int = 2,
) -> dict[str, Any]:
    cv_ir = parse_candidate_cv_ir(base_cv_text, supported_keywords)
    plan = AtsCvPlan()
    plan_errors: list[str] = []
    if planner_response:
        plan_errors = validate_planner_response(cv_ir, planner_response)
        if not plan_errors:
            plan = ats_cv_plan_from_response(planner_response)
    ats_cv_text = render_ats_cv(cv_ir, plan, min_bullets_per_role=min_bullets_per_role)
    validation_errors = [*cv_ir.parse_warnings, *plan_errors]
    return {
        "ats_cv_text": ats_cv_text,
        "keywords_used": derive_keywords_used(ats_cv_text, supported_keywords),
        "risk_flags": ["human_review_required"] if cv_ir.human_review_required else [],
        "_generation_metadata": {
            "pipeline": "controlled_cv",
            "planner_errors": plan_errors,
            "parse_warnings": cv_ir.parse_warnings,
            "validation_errors": validation_errors,
            "human_review_required": cv_ir.human_review_required,
        },
    }
