from __future__ import annotations

from typing import Any

from joborchestrator.intelligence.materials_language import detect_job_language


def build_generation_context(full_payload: dict[str, Any]) -> dict[str, Any]:
    job = full_payload.get("job") if isinstance(full_payload.get("job"), dict) else {}
    ats = full_payload.get("ats_fit_analysis") if isinstance(full_payload.get("ats_fit_analysis"), dict) else {}
    ranking = full_payload.get("ranking") if isinstance(full_payload.get("ranking"), dict) else {}
    return {
        "job": {
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "target_language": detect_job_language(str(job.get("title") or ""), str(job.get("description_text") or "")),
        },
        "supported_keywords": list(ats.get("supported_keywords") or [])[:30],
        "adjacent_or_review_keywords": list(ats.get("adjacent_or_review_keywords") or [])[:15],
        "ranking_decision": ranking.get("decision"),
        "tone": full_payload.get("application_tone_constraints"),
        "experience_claim_constraints": full_payload.get("experience_claim_constraints"),
    }


def forbidden_aliases_absent_from_generation_context(generation_context: dict[str, Any], forbidden_aliases: dict[str, list[str]]) -> bool:
    context_text = str(generation_context)
    return not any(alias and alias in context_text for aliases in forbidden_aliases.values() for alias in aliases)
