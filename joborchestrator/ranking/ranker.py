from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from joborchestrator.ranking.fit_scorer import score_fit
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.requirements_extractor import extract_requirements
from joborchestrator.ranking.schemas import CandidateProfile, RankingEvidence, RankingResult, RankingScores
from joborchestrator.scanning.normalization import normalize_text

RANKING_VERSION = "ranking_v1.0.0"


def rank_job(job: Any, profile: CandidateProfile | None = None) -> RankingResult:
    profile = profile or load_candidate_profile()
    requirements = extract_requirements(job)
    scores, evidence, role_info = score_fit(job, requirements, profile)
    raw_score = (
        scores.technical_fit * 0.30
        + scores.seniority_fit * 0.15
        + scores.role_fit * 0.15
        + scores.opportunity_quality * 0.15
        + scores.application_roi * 0.15
        + scores.market_alignment * 0.10
        - scores.risk_penalty
    )
    final_score = max(0, min(100, int(round(raw_score))))
    decision = decision_from_score(final_score)

    severe_dealbreaker = any(_is_critical_dealbreaker(x) for x in evidence.dealbreakers + evidence.red_flags)
    if severe_dealbreaker:
        decision = "AVOID" if any(_is_avoid_flag(x) for x in evidence.dealbreakers + evidence.red_flags) else _cap_decision(decision, "SKIP")
        final_score = min(final_score, 35 if decision == "SKIP" else 25)
    if scores.technical_fit < 40:
        decision = _cap_decision(decision, "APPLY_WITH_TAILORED_CV")
    if scores.seniority_fit < 35 or scores.role_fit < 35:
        decision = _cap_decision(decision, "MAYBE")
    final_score, decision = _apply_data_quality_guard(job, final_score, decision)

    confidence = _estimate_confidence(scores, evidence, role_info)
    summary = _reasoning_summary(scores, evidence, role_info, confidence)
    emphasize = _keywords_to_emphasize(evidence, requirements.tech_stack)
    avoid = _keywords_to_avoid(evidence)

    return RankingResult(
        final_score=final_score,
        decision=decision,  # type: ignore[arg-type]
        confidence=confidence,
        scores=scores,
        evidence=evidence,
        reasoning_summary=summary,
        recommended_application_angle=_application_angle(role_info, emphasize),
        cv_keywords_to_emphasize=emphasize,
        cv_keywords_to_avoid_overclaiming=avoid,
        ranking_version=RANKING_VERSION,
    )


def rank_jobs(jobs: list[Any], profile: CandidateProfile | None = None) -> list[RankingResult]:
    profile = profile or load_candidate_profile()
    return [rank_job(job, profile) for job in jobs]


def decision_from_score(score: int) -> str:
    if score >= 80:
        return "APPLY_NOW"
    if score >= 65:
        return "APPLY_WITH_TAILORED_CV"
    if score >= 50:
        return "MAYBE"
    if score >= 30:
        return "SKIP"
    return "AVOID"


def result_to_dict(result: RankingResult) -> dict:
    return {
        "final_score": result.final_score,
        "decision": result.decision,
        "confidence": result.confidence,
        "scores": asdict(result.scores),
        "evidence": asdict(result.evidence),
        "reasoning_summary": result.reasoning_summary,
        "recommended_application_angle": result.recommended_application_angle,
        "cv_keywords_to_emphasize": result.cv_keywords_to_emphasize,
        "cv_keywords_to_avoid_overclaiming": result.cv_keywords_to_avoid_overclaiming,
        "ranking_version": result.ranking_version,
    }


def _cap_decision(decision: str, max_decision: str) -> str:
    order = ["AVOID", "SKIP", "MAYBE", "APPLY_WITH_TAILORED_CV", "APPLY_NOW"]
    return order[min(order.index(decision), order.index(max_decision))]


def _apply_data_quality_guard(job: Any, final_score: int, decision: str) -> tuple[int, str]:
    data = _job_to_dict(job)
    parse_confidence = data.get("parse_confidence")
    if parse_confidence is None:
        return final_score, decision
    confidence = float(parse_confidence)
    if confidence < 0.5:
        return min(final_score, 64), _cap_decision(decision, "MAYBE")
    if confidence < 0.65:
        return min(final_score, 79), _cap_decision(decision, "APPLY_WITH_TAILORED_CV")
    return final_score, decision


def _job_to_dict(job: Any) -> dict:
    if isinstance(job, dict):
        return job
    if is_dataclass(job):
        return asdict(job)
    if hasattr(job, "to_dict"):
        return job.to_dict()
    if hasattr(job, "__dict__"):
        return vars(job)
    return {}


def _is_critical_dealbreaker(flag: str) -> bool:
    text = normalize_text(flag)
    return any(x in text for x in ["unpaid", "commission only", "relocation", "manual qa", "visa"])


def _is_avoid_flag(flag: str) -> bool:
    text = normalize_text(flag)
    return "unpaid" in text or "commission only" in text


def _estimate_confidence(scores: RankingScores, evidence: RankingEvidence, role_info: dict) -> float:
    confidence = 0.58
    if evidence.strong_matches:
        confidence += 0.12
    if evidence.missing_requirements:
        confidence -= min(0.18, len(evidence.missing_requirements) * 0.03)
    if scores.opportunity_quality >= 70:
        confidence += 0.08
    confidence += (role_info.get("confidence", 0.5) - 0.5) * 0.25
    if evidence.red_flags:
        confidence -= min(0.12, len(evidence.red_flags) * 0.02)
    return round(max(0.2, min(0.95, confidence)), 2)


def _reasoning_summary(scores: RankingScores, evidence: RankingEvidence, role_info: dict, confidence: float) -> str:
    parts = [
        f"{role_info['primary_role']} fit with technical score {scores.technical_fit}.",
        f"Seniority score {scores.seniority_fit}, ROI score {scores.application_roi}.",
    ]
    if evidence.strong_matches:
        parts.append(f"Strong matches: {', '.join(evidence.strong_matches[:5])}.")
    if evidence.partial_matches:
        parts.append(f"Partial matches: {', '.join(evidence.partial_matches[:3])}.")
    if evidence.missing_requirements:
        parts.append(f"Missing: {', '.join(evidence.missing_requirements[:4])}.")
    if evidence.red_flags:
        parts.append(f"Risks: {', '.join(evidence.red_flags[:3])}.")
    if confidence < 0.45:
        parts.insert(0, "Low confidence ranking due to limited or ambiguous job data.")
    return " ".join(parts)


def _application_angle(role_info: dict, emphasize: list[str]) -> str:
    keywords = ", ".join(emphasize[:6]) or "relevant backend experience"
    if role_info["primary_role"] in {"Solutions Engineer", "Technical Consultant"}:
        return f"Position as a technical customer-facing engineer with API/integration depth. Emphasize {keywords}."
    if role_info["primary_role"] in {"ML/AI Engineer", "Data Engineer"}:
        return f"Position as Python backend engineer moving into data/AI systems. Emphasize {keywords}."
    return f"Position as Python backend engineer with strong API, cloud and product delivery ownership. Emphasize {keywords}."


def _keywords_to_emphasize(evidence: RankingEvidence, tech_stack: list[str]) -> list[str]:
    return _dedupe(evidence.strong_matches + evidence.nice_to_have_matches + tech_stack[:6])[:12]


def _keywords_to_avoid(evidence: RankingEvidence) -> list[str]:
    avoid = []
    for missing in evidence.missing_requirements:
        avoid.append(missing)
    for partial in evidence.partial_matches:
        if ":" in partial:
            avoid.append(partial.split(":", 1)[0])
    return _dedupe(avoid)[:10]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
