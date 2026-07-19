from __future__ import annotations

import json
from typing import Any

import pandas as pd

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION, filter_llm_ranking_versions
from joborchestrator.priority import compute_priority
from joborchestrator.storage import persistence as db


def parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback


def job_dto(
    job: dict[str, Any],
    ranking_row: dict[str, Any] | None,
    *,
    include_hiring_contacts: bool = True,
    compact: bool = False,
) -> dict[str, Any]:
    ranking = ranking_dto(ranking_row)
    priority = compute_priority(job, ranking).to_dict()
    location_mode = _string(job.get("location") or job.get("workplace_type")).lower()
    hiring_contacts = _hiring_contacts_for_job(job) if include_hiring_contacts else []
    return {
        "id": str(job["id"]),
        "title": _string(job.get("title"), "Untitled role"),
        "company": _string(job.get("company"), "Unknown company"),
        "location": _string(job.get("location"), "Unspecified"),
        "remote": any(marker in location_mode for marker in ["remote", "remoto", "remota"]),
        "source": _source_label(job.get("source")),
        "source_raw": job.get("source"),
        "url": _string(job.get("url") or job.get("apply_url"), "#"),
        "apply_url": _string(job.get("apply_url") or job.get("url"), "#"),
        "applicant_count": _int_or_none(job.get("applicant_count")),
        "applicant_count_raw": _nullable_string(job.get("applicant_count_raw")),
        "salary_min": _float_or_none(job.get("salary_min")),
        "salary_max": _float_or_none(job.get("salary_max")),
        "salary_currency": _nullable_string(job.get("salary_currency")),
        "recruiter_name": _nullable_string(job.get("recruiter_name")),
        "recruiter_profile_url": _nullable_string(job.get("recruiter_profile_url")),
        "hiring_contacts": hiring_contacts,
        "hiring_contacts_count": len(hiring_contacts),
        "apply_type": _nullable_string(job.get("apply_type")),
        "external_apply_url": _nullable_string(job.get("external_apply_url")),
        "description_text": _string(job.get("description_text")) if not compact else _string(job.get("description_text"))[:1200],
        "first_seen_at": _string(job.get("first_seen_at")),
        "last_seen_at": _string(job.get("last_seen_at")),
        "status": "active" if int(job.get("is_active") or 0) else "expired",
        "pipeline_status": job.get("pipeline_status") or "new",
        "ranking": ranking,
        "priority": priority,
        "materials": {
            "recruiter_message": _string(job.get("recruiter_message")) if not compact else "",
            "cover_letter": _string(job.get("cover_letter")) if not compact else "",
            "ats_cv_notes": _string(job.get("ats_cv_text")) if not compact else "",
            "autofill_notes": _string(job.get("autofill_notes")) if not compact else "",
            "review": materials_review_dto(job, ranking),
            "generation": materials_generation_dto(job),
        },
    }


def materials_review_dto(job: dict[str, Any], ranking: dict[str, Any]) -> dict[str, Any]:
    recruiter_message = _string(job.get("recruiter_message")).strip()
    cover_letter = _string(job.get("cover_letter")).strip()
    ats_cv_text = _string(job.get("ats_cv_text")).strip()
    autofill_notes = _string(job.get("autofill_notes")).strip()
    has_materials = bool(recruiter_message or cover_letter or ats_cv_text or autofill_notes)
    reasons: list[str] = []
    if not has_materials:
        return {"status": "missing", "requires_review": True, "reasons": ["materials_missing"]}

    evidence = ranking.get("evidence") or {}
    if bool(evidence.get("requires_llm_review")):
        reasons.append("ranking_requires_review")
    if float(ranking.get("confidence") or 0) < 0.75:
        reasons.append("ranking_low_confidence")
    if ranking.get("decision") not in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"}:
        reasons.append("ranking_not_actionable")
    if not recruiter_message:
        reasons.append("recruiter_message_missing")
    if not ats_cv_text:
        reasons.append("ats_cv_missing")
    elif len(ats_cv_text) < 500:
        reasons.append("ats_cv_too_short")
    if not autofill_notes:
        reasons.append("autofill_notes_missing")

    normalized_ats_cv = _normalize_for_review(ats_cv_text)
    overclaim_terms = [
        term
        for term in ranking.get("cv_keywords_to_avoid_overclaiming") or []
        if _normalize_for_review(str(term)) and _normalize_for_review(str(term)) in normalized_ats_cv
    ]
    if overclaim_terms:
        reasons.append("ats_cv_contains_avoid_overclaiming_terms:" + ",".join(overclaim_terms[:6]))

    return {
        "status": "needs_review" if reasons else "ready",
        "requires_review": bool(reasons),
        "reasons": reasons,
    }


def materials_generation_dto(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": _nullable_string(job.get("materials_provider")),
        "model": _nullable_string(job.get("materials_model")),
        "prompt_versions": parse_json_value(job.get("materials_prompt_versions_json"), {}),
        "generated_at": _nullable_string(job.get("materials_generated_at")),
        "validation_attempts": _int_or_none(job.get("materials_validation_attempts")),
        "validation_errors": parse_json_value(job.get("materials_validation_errors_json"), []),
        "candidate_profile_hash": _nullable_string(job.get("materials_candidate_profile_hash")),
    }


def _hiring_contacts_for_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    job_id = _int_or_none(job.get("id"))
    if job_id is None:
        return []
    contacts = db.list_job_hiring_contacts(job_id)
    return [
        {
            "id": str(contact["id"]),
            "name": _string(contact.get("name")),
            "profile_url": _string(contact.get("profile_url")),
            "headline": _nullable_string(contact.get("headline")),
            "role": _nullable_string(contact.get("role")),
            "is_primary": bool(contact.get("is_primary")),
            "source": _string(contact.get("source"), "linkedin_hiring_team"),
        }
        for contact in contacts
        if contact.get("name") and contact.get("profile_url")
    ]


def ranking_dto(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return _default_ranking()
    scores = parse_json_value(row.get("scores_json"), {})
    scores.setdefault("technical_fit", 0)
    scores.setdefault("seniority_fit", 0)
    scores.setdefault("role_fit", 0)
    scores.setdefault("opportunity_quality", 0)
    scores.setdefault("application_roi", 0)
    scores.setdefault("market_alignment", 0)
    scores.setdefault("risk_penalty", 0)
    scores.setdefault("requirement_coverage", scores.get("central_requirement_coverage") or 0)
    scores.setdefault("seniority_match", scores.get("seniority_fit") or 0)
    scores.setdefault("location_fit", scores.get("market_alignment") or 0)
    scores.setdefault("compensation", 0)

    evidence = parse_json_value(row.get("evidence_json"), {})
    evidence.setdefault("strong_matches", [])
    evidence.setdefault("partial_matches", [])
    evidence.setdefault("missing_requirements", [])
    evidence.setdefault("dealbreakers", [])
    evidence.setdefault("red_flags", [])
    evidence.setdefault("requires_llm_review", False)
    evidence.setdefault("llm_escalation_reasons", [])
    evidence.setdefault("central_requirements", [])
    evidence["central_requirements"] = [
        item.get("requirement") if isinstance(item, dict) else str(item)
        for item in evidence.get("central_requirements") or []
    ]
    ranking = {
        "final_score": int(row.get("final_score") or 0),
        "decision": row.get("decision") or "MAYBE",
        "confidence": float(row.get("confidence") or 0),
        "scores": scores,
        "evidence": evidence,
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": parse_json_value(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": parse_json_value(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
        "ranking_version": row.get("ranking_version") or NVIDIA_RANKING_VERSION,
        "generation": ranking_generation_dto(row),
    }
    ranking["review"] = ranking_review_dto(ranking)
    return ranking


def ranking_review_dto(ranking: dict[str, Any]) -> dict[str, Any]:
    if ranking.get("ranking_version") == "unranked":
        return {"status": "missing", "requires_review": True, "reasons": ["ranking_missing"]}
    evidence = ranking.get("evidence") or {}
    generation = ranking.get("generation") or {}
    decision = ranking.get("decision")
    reasons: list[str] = []
    if bool(evidence.get("requires_llm_review")):
        reasons.append("ranking_requires_llm_review")
    if float(ranking.get("confidence") or 0) < 0.75:
        reasons.append("ranking_low_confidence")
    if int(generation.get("validation_attempts") or 0) > 1:
        reasons.append("ranking_validation_retry")
    if decision in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"} and not evidence.get("strong_matches"):
        reasons.append("ranking_thin_positive_evidence")
    if decision in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"} and not evidence.get("central_requirements"):
        reasons.append("ranking_missing_central_requirements")
    return {
        "status": "needs_review" if reasons else "ready",
        "requires_review": bool(reasons),
        "reasons": reasons,
    }


def ranking_generation_dto(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": _nullable_string(row.get("ranking_provider")),
        "model": _nullable_string(row.get("ranking_model")),
        "prompt_versions": parse_json_value(row.get("ranking_prompt_versions_json"), {}),
        "validation_attempts": _int_or_none(row.get("ranking_validation_attempts")),
        "validation_errors": parse_json_value(row.get("ranking_validation_errors_json"), []),
        "candidate_profile_hash": _nullable_string(row.get("ranking_candidate_profile_hash")),
    }


def latest_rankings_by_job_id(ranking_version: str | None = None) -> dict[int, dict[str, Any]]:
    versions = [ranking_version] if ranking_version else filter_llm_ranking_versions(db.get_ranking_versions())[:1]
    rankings: dict[int, dict[str, Any]] = {}
    for version in versions:
        if not version:
            continue
        ranked = db.get_ranked_jobs(ranking_version=version)
        for row in ranked.to_dict("records"):
            job_id = int(row["job_id"])
            rankings.setdefault(job_id, row)
    return rankings


def scan_result_dto(result: Any) -> dict[str, Any]:
    return {
        "source_type": result.source_type,
        "company_name": result.company_name,
        "company_ref": result.company_ref,
        "found_count": result.found_count,
        "new_count": len(result.new_jobs),
        "updated_count": len(result.updated_jobs),
        "unchanged_count": len(result.unchanged_jobs),
        "errors": result.errors,
        "duration_seconds": result.duration_seconds,
    }


def _default_ranking() -> dict[str, Any]:
    return {
        "final_score": 0,
        "decision": "MAYBE",
        "confidence": 0,
        "scores": {
            "technical_fit": 0,
            "seniority_fit": 0,
            "role_fit": 0,
            "opportunity_quality": 0,
            "application_roi": 0,
            "market_alignment": 0,
            "risk_penalty": 0,
            "requirement_coverage": 0,
            "seniority_match": 0,
            "location_fit": 0,
            "compensation": 0,
        },
        "evidence": {
            "strong_matches": [],
            "partial_matches": [],
            "missing_requirements": [],
            "dealbreakers": [],
            "red_flags": [],
            "requires_llm_review": False,
            "llm_escalation_reasons": [],
            "central_requirements": [],
        },
        "reasoning_summary": "Not ranked yet.",
        "recommended_application_angle": "",
        "cv_keywords_to_emphasize": [],
        "cv_keywords_to_avoid_overclaiming": [],
        "ranking_version": "unranked",
        "review": {
            "status": "missing",
            "requires_review": True,
            "reasons": ["ranking_missing"],
        },
        "generation": {
            "provider": None,
            "model": None,
            "prompt_versions": {},
            "validation_attempts": None,
            "validation_errors": [],
            "candidate_profile_hash": None,
        },
    }


def _source_label(source: str | None) -> str:
    raw = (source or "").lower()
    mapping = {
        "linkedin_scraper": "LinkedIn",
        "linkedin": "LinkedIn",
        "greenhouse": "Greenhouse",
        "lever": "Lever",
        "ashby": "Ashby",
        "remotive": "API",
        "arbeitnow": "API",
        "adzuna": "API",
        "themuse": "API",
        "infojobs": "API",
        "manual": "Manual",
    }
    return mapping.get(raw, "API")


def _string(value: Any, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    return str(value)


def _nullable_string(value: Any) -> str | None:
    text = _string(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_for_review(value: str) -> str:
    return " ".join(str(value or "").lower().split())
