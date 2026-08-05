from __future__ import annotations

import re
from typing import Any

from joborchestrator.intelligence.materials_language import detect_job_language
from joborchestrator.intelligence.cv_job_analysis import build_cv_job_analysis


def build_generation_context(full_payload: dict[str, Any]) -> dict[str, Any]:
    job = full_payload.get("job") if isinstance(full_payload.get("job"), dict) else {}
    ats = full_payload.get("ats_fit_analysis") if isinstance(full_payload.get("ats_fit_analysis"), dict) else {}
    ranking = full_payload.get("ranking") if isinstance(full_payload.get("ranking"), dict) else {}
    evidence = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    forbidden_aliases = _forbidden_aliases(full_payload)

    requirements = {
        "central_requirements": evidence.get("central_requirements") or [],
        "strong_matches": evidence.get("strong_matches") or [],
        "partial_matches": evidence.get("partial_matches") or [],
        "missing_requirements": evidence.get("missing_requirements") or [],
        "nice_to_have_matches": evidence.get("nice_to_have_matches") or [],
        "red_flags": evidence.get("red_flags") or [],
        "dealbreakers": evidence.get("dealbreakers") or [],
        "coverage": evidence.get("central_requirement_coverage"),
        "evidence_quality": evidence.get("central_requirement_evidence_quality"),
    }

    return {
        "cv_job_analysis": build_cv_job_analysis(full_payload),
        "job": {
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "description_text": str(_sanitize(job.get("description_text"), forbidden_aliases) or "")[:6000],
            "target_language": detect_job_language(
                str(job.get("title") or ""),
                str(job.get("description_text") or ""),
            ),
        },
        "supported_keywords": list(ats.get("supported_keywords") or [])[:30],
        "adjacent_or_review_keywords": list(ats.get("adjacent_or_review_keywords") or [])[:15],
        "ranking_decision": ranking.get("decision"),
        "recommended_application_angle": _sanitize(
            ranking.get("recommended_application_angle"),
            forbidden_aliases,
        ),
        "requirement_evidence": _sanitize(requirements, forbidden_aliases),
        "tone": full_payload.get("application_tone_constraints"),
        "experience_claim_constraints": full_payload.get("experience_claim_constraints"),
    }


def forbidden_aliases_absent_from_generation_context(
    generation_context: dict[str, Any],
    forbidden_aliases: dict[str, list[str]],
) -> bool:
    context_text = str(generation_context).casefold()
    return not any(
        str(alias or "").casefold() in context_text
        for aliases in forbidden_aliases.values()
        for alias in aliases
        if str(alias or "").strip()
    )


def _forbidden_aliases(full_payload: dict[str, Any]) -> list[str]:
    constraints = (
        full_payload.get("ranking_constraints")
        if isinstance(full_payload.get("ranking_constraints"), dict)
        else {}
    )
    aliases = constraints.get("avoid_overclaiming_aliases")
    if not isinstance(aliases, dict):
        return []
    values: list[str] = []
    for group in aliases.values():
        if isinstance(group, list):
            values.extend(str(value) for value in group if str(value or "").strip())
    return sorted(set(values), key=len, reverse=True)


def _sanitize(value: Any, forbidden_aliases: list[str]) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item, forbidden_aliases) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, forbidden_aliases) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for alias in forbidden_aliases:
        result = re.sub(
            rf"(?i)(?<![\w+#]){re.escape(alias)}(?![\w+#])",
            "unsupported target-stack requirement",
            result,
        )
    return re.sub(r"\s+", " ", result).strip()
