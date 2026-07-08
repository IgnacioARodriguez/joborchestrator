from __future__ import annotations

import json
from typing import Any

import pandas as pd

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION, filter_llm_ranking_versions
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


def job_dto(job: dict[str, Any], ranking_row: dict[str, Any] | None) -> dict[str, Any]:
    ranking = ranking_dto(ranking_row)
    location_mode = _string(job.get("location") or job.get("workplace_type")).lower()
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
        "description_text": _string(job.get("description_text")),
        "first_seen_at": _string(job.get("first_seen_at")),
        "last_seen_at": _string(job.get("last_seen_at")),
        "status": "active" if int(job.get("is_active") or 0) else "expired",
        "pipeline_status": job.get("pipeline_status") or "new",
        "ranking": ranking,
        "materials": {
            "recruiter_message": _string(job.get("recruiter_message")),
            "cover_letter": _string(job.get("cover_letter")),
            "ats_cv_notes": _string(job.get("ats_cv_text")),
            "autofill_notes": _string(job.get("autofill_notes")),
        },
    }


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
    evidence.setdefault("red_flags", [])
    evidence.setdefault("central_requirements", [])
    evidence["central_requirements"] = [
        item.get("requirement") if isinstance(item, dict) else str(item)
        for item in evidence.get("central_requirements") or []
    ]
    evidence.pop("requires_llm_review", None)
    evidence.pop("llm_escalation_reasons", None)
    return {
        "final_score": int(row.get("final_score") or 0),
        "decision": row.get("decision") or "MAYBE",
        "confidence": float(row.get("confidence") or 0),
        "scores": scores,
        "evidence": evidence,
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "ranking_version": row.get("ranking_version") or NVIDIA_RANKING_VERSION,
    }


def latest_rankings_by_job_id(ranking_version: str | None = None) -> dict[int, dict[str, Any]]:
    versions = [ranking_version] if ranking_version else filter_llm_ranking_versions(db.get_ranking_versions())
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
            "red_flags": [],
            "central_requirements": [],
        },
        "reasoning_summary": "Not ranked yet.",
        "recommended_application_angle": "",
        "ranking_version": "unranked",
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
    }
    return mapping.get(raw, "API")


def _string(value: Any, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    return str(value)
