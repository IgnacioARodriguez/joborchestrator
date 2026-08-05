from __future__ import annotations

import re
from typing import Any

from joborchestrator.intelligence.materials_language import detect_job_language


def build_cv_job_analysis(full_payload: dict[str, Any]) -> dict[str, Any]:
    """Build CV-specific job guidance without changing ranking decisions."""
    job = full_payload.get("job") if isinstance(full_payload.get("job"), dict) else {}
    ats = full_payload.get("ats_fit_analysis") if isinstance(full_payload.get("ats_fit_analysis"), dict) else {}
    ranking = full_payload.get("ranking") if isinstance(full_payload.get("ranking"), dict) else {}
    evidence = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    constraints = full_payload.get("ranking_constraints") if isinstance(full_payload.get("ranking_constraints"), dict) else {}
    aliases = constraints.get("avoid_overclaiming_aliases") if isinstance(constraints.get("avoid_overclaiming_aliases"), dict) else {}
    forbidden = [str(alias) for values in aliases.values() if isinstance(values, list) for alias in values if str(alias or '').strip()]

    def clean(value: Any) -> Any:
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if not isinstance(value, str):
            return value
        result = value
        for alias in forbidden:
            result = re.sub(rf"(?i)(?<![\w+#]){re.escape(alias)}(?![\w+#])", "unsupported target-stack requirement", result)
        return result

    return {
        "target_role": job.get("title"),
        "company": job.get("company"),
        "target_language": detect_job_language(
            str(job.get("title") or ""),
            str(job.get("description_text") or ""),
        ),
        "job_description": clean(str(job.get("description_text") or "")[:6000]),
        "core_requirements": clean(list(evidence.get("central_requirements") or [])),
        "strong_matches": clean(list(evidence.get("strong_matches") or [])),
        "partial_matches": clean(list(evidence.get("partial_matches") or [])),
        "missing_requirements": clean(list(evidence.get("missing_requirements") or [])),
        "nice_to_have_matches": clean(list(evidence.get("nice_to_have_matches") or [])),
        "supported_keywords": list(ats.get("supported_keywords") or [])[:30],
        "adjacent_or_review_keywords": list(ats.get("adjacent_or_review_keywords") or [])[:15],
        "avoid_keywords": list(ats.get("avoid_keywords") or [])[:30],
        "recommended_cv_angle": clean(ranking.get("recommended_application_angle")),
        "candidate_narrative": {
            "professional_identity": _professional_identity(job, evidence),
            "target_relevance": clean(
                list(evidence.get("strong_matches") or [])
                + list(ats.get("supported_keywords") or [])[:8]
            ),
            "value_proposition": clean(ranking.get("recommended_application_angle")),
            "limitations": clean(list(evidence.get("missing_requirements") or [])),
            "source_evidence": _narrative_evidence_ids(evidence),
        },
    }


def _professional_identity(job: dict[str, Any], evidence: dict[str, Any]) -> str:
    title = str(job.get("title") or "professional").strip()
    matches = [str(value) for value in evidence.get("strong_matches") or [] if str(value or '').strip()]
    focus = ", ".join(matches[:3])
    return f"Professional targeting {title}" + (f" with evidence in {focus}" if focus else "")


def _narrative_evidence_ids(evidence: dict[str, Any]) -> list[str]:
    ids = []
    for key in ("strong_matches", "partial_matches"):
        ids.extend(str(value) for value in evidence.get(key) or [] if str(value or '').strip())
    return list(dict.fromkeys(ids))[:12]
