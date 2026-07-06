from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranker import result_to_dict
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores, VALID_DECISIONS
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION


class ManualLLMReviewError(ValueError):
    pass


def manual_review_status(evidence: dict[str, Any]) -> tuple[bool, str]:
    requires_review = bool(evidence.get("requires_llm_review"))
    reasons = [str(reason) for reason in evidence.get("llm_escalation_reasons") or []]
    if "manual_chatgpt_review_applied" in reasons:
        return False, "Reviewed"
    if not requires_review and not reasons:
        return False, ""
    visible_reasons = [reason for reason in reasons if reason != "manual_chatgpt_review_applied"]
    return requires_review, ", ".join(_friendly_reason(reason) for reason in visible_reasons) or "Needs review"


def build_manual_review_prompt(job: dict[str, Any], current_ranking: RankingResult) -> str:
    profile = load_candidate_profile()
    payload = {
        "candidate_profile": asdict(profile),
        "job": _compact_job(job),
        "current_ranking": result_to_dict(current_ranking),
        "ranking_goal": (
            "Prioritize jobs where the candidate has the highest probability of getting hired quickly. "
            "This is not a salary or dream-job ranking. Salary, prestige and personal preference are post-filters."
        ),
        "review_rules": [
            "Do not invent skills or experience.",
            "A role can be viable if it is backend/Python/API/integration focused or an adjacent technical consultant/solutions role.",
            "If central requirements are mostly outside the candidate profile, cap the decision at SKIP.",
            "If the job text is too noisy or incomplete, prefer MAYBE or SKIP with lower confidence.",
            "Keep hard dealbreakers above everything else.",
            "Return only valid JSON. No markdown, no prose outside JSON.",
        ],
    }
    return (
        "Actua como evaluador estricto de oportunidades laborales para Job Orchestrator.\n"
        "Revisa el ranking actual y corrige falsos positivos/falsos negativos si la evidencia lo justifica.\n\n"
        "Devuelve SOLO un JSON con esta forma exacta:\n"
        "{\n"
        '  "final_score": 0,\n'
        '  "decision": "APPLY_NOW | APPLY_WITH_TAILORED_CV | MAYBE | SKIP | AVOID",\n'
        '  "confidence": 0.0,\n'
        '  "scores": {\n'
        '    "technical_fit": 0,\n'
        '    "seniority_fit": 0,\n'
        '    "role_fit": 0,\n'
        '    "opportunity_quality": 0,\n'
        '    "application_roi": 0,\n'
        '    "market_alignment": 0,\n'
        '    "risk_penalty": 0,\n'
        '    "speed_signal": 0,\n'
        '    "technical_readiness": 0,\n'
        '    "central_requirement_coverage": 0,\n'
        '    "role_confidence": 0,\n'
        '    "application_effort_signal": 0,\n'
        '    "data_quality_signal": 0,\n'
        '    "source_reliability_signal": 0\n'
        "  },\n"
        '  "evidence": {\n'
        '    "strong_matches": [],\n'
        '    "partial_matches": [],\n'
        '    "missing_requirements": [],\n'
        '    "nice_to_have_matches": [],\n'
        '    "dealbreakers": [],\n'
        '    "red_flags": [],\n'
        '    "central_requirement_coverage": 0.0,\n'
        '    "central_requirement_raw_coverage": 0.0,\n'
        '    "central_requirement_evidence_quality": 0.0,\n'
        '    "requirement_backed_signal_count": 0,\n'
        '    "central_requirement_thresholds": {},\n'
        '    "central_requirements": [],\n'
        '    "requires_llm_review": false,\n'
        '    "llm_escalation_reasons": []\n'
        "  },\n"
        '  "reasoning_summary": "short explanation",\n'
        '  "recommended_application_angle": "short positioning",\n'
        '  "cv_keywords_to_emphasize": [],\n'
        '  "cv_keywords_to_avoid_overclaiming": []\n'
        "}\n\n"
        "Contexto a revisar:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_manual_review_response(response_text: str, baseline: RankingResult) -> RankingResult:
    payload = _extract_json_object(response_text)
    if not isinstance(payload, dict):
        raise ManualLLMReviewError("La respuesta no contiene un objeto JSON.")

    decision = payload.get("decision", baseline.decision)
    if decision not in VALID_DECISIONS:
        raise ManualLLMReviewError(f"Decision invalida: {decision}")

    scores_payload = asdict(baseline.scores)
    scores_payload.update(payload.get("scores") or {})
    evidence_payload = asdict(baseline.evidence)
    evidence_payload.update(payload.get("evidence") or {})
    evidence_payload["requires_llm_review"] = False
    reasons = list(evidence_payload.get("llm_escalation_reasons") or [])
    if "manual_chatgpt_review_applied" not in reasons:
        reasons.append("manual_chatgpt_review_applied")
    evidence_payload["llm_escalation_reasons"] = reasons

    return RankingResult(
        final_score=_int_between(payload.get("final_score", baseline.final_score), 0, 100, "final_score"),
        decision=decision,
        confidence=_float_between(payload.get("confidence", baseline.confidence), 0.0, 1.0, "confidence"),
        scores=RankingScores(**scores_payload),
        evidence=RankingEvidence(**evidence_payload),
        reasoning_summary=str(payload.get("reasoning_summary") or baseline.reasoning_summary),
        recommended_application_angle=str(
            payload.get("recommended_application_angle") or baseline.recommended_application_angle
        ),
        cv_keywords_to_emphasize=list(payload.get("cv_keywords_to_emphasize") or baseline.cv_keywords_to_emphasize),
        cv_keywords_to_avoid_overclaiming=list(
            payload.get("cv_keywords_to_avoid_overclaiming") or baseline.cv_keywords_to_avoid_overclaiming
        ),
        ranking_version=SPEED_RANKING_VERSION,
    )


def ranking_from_storage_row(row: dict[str, Any]) -> RankingResult:
    scores = json.loads(row.get("scores_json") or "{}")
    evidence = json.loads(row.get("evidence_json") or "{}")
    return RankingResult(
        final_score=int(row.get("final_score") or 0),
        decision=row.get("decision") or "SKIP",
        confidence=float(row.get("confidence") or 0.0),
        scores=RankingScores(**scores),
        evidence=RankingEvidence(**evidence),
        reasoning_summary=row.get("reasoning_summary") or "",
        recommended_application_angle=row.get("recommended_application_angle") or "",
        cv_keywords_to_emphasize=json.loads(row.get("cv_keywords_to_emphasize_json") or "[]"),
        cv_keywords_to_avoid_overclaiming=json.loads(row.get("cv_keywords_to_avoid_overclaiming_json") or "[]"),
        ranking_version=row.get("ranking_version") or SPEED_RANKING_VERSION,
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ManualLLMReviewError("No pude encontrar JSON en la respuesta.")
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ManualLLMReviewError(f"JSON invalido: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ManualLLMReviewError("La respuesta JSON debe ser un objeto.")
    return parsed


def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "title",
        "company",
        "location",
        "source",
        "url",
        "apply_url",
        "description_text",
        "posted_at",
        "first_seen_at",
        "last_seen_at",
        "parse_confidence",
        "data_quality_flags",
    ]
    compact = {key: job.get(key) for key in keys if job.get(key) is not None}
    description = str(compact.get("description_text") or "")
    if len(description) > 8000:
        compact["description_text"] = description[:8000] + "\n[truncated]"
    return compact


def _friendly_reason(reason: str) -> str:
    labels = {
        "central_requirement_coverage_below_low_threshold": "Low central coverage",
        "central_requirement_coverage_requires_review": "Coverage needs review",
        "role_confidence_below_threshold": "Low role confidence",
        "insufficient_requirement_backed_evidence": "Thin requirement evidence",
        "llm_fallback_applied": "LLM fallback applied",
    }
    return labels.get(reason, reason.replace("_", " ").title())


def _int_between(value: Any, low: int, high: int, field: str) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ManualLLMReviewError(f"{field} debe ser numerico.") from exc
    if not low <= parsed <= high:
        raise ManualLLMReviewError(f"{field} debe estar entre {low} y {high}.")
    return parsed


def _float_between(value: Any, low: float, high: float, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ManualLLMReviewError(f"{field} debe ser numerico.") from exc
    if not low <= parsed <= high:
        raise ManualLLMReviewError(f"{field} debe estar entre {low} y {high}.")
    return parsed
