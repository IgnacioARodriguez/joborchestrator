from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from typing import Any

from joborchestrator.ranking.fit_scorer import score_fit
from joborchestrator.ranking.llm_ranker import rank_job_with_llm
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.requirements_extractor import extract_requirements
from joborchestrator.ranking.ranker import _cap_decision, decision_from_score, result_to_dict
from joborchestrator.ranking.schemas import CandidateProfile, RankingEvidence, RankingResult, RankingScores
from joborchestrator.ranking.structural_requirements import (
    LLM_REVIEW_COVERAGE_THRESHOLD,
    LOW_COVERAGE_THRESHOLD,
    analyze_central_requirements,
)

SPEED_RANKING_VERSION = "ranking_v1.1.0-speed"


def rank_job_speed(
    job: Any,
    profile: CandidateProfile | None = None,
    *,
    use_llm_fallback: bool = False,
    model: str | None = None,
) -> RankingResult:
    profile = profile or load_candidate_profile()
    requirements = extract_requirements(job)
    legacy_scores, legacy_evidence, role_info = score_fit(job, requirements, profile)
    central = analyze_central_requirements(job, profile)

    technical_readiness = _technical_readiness(legacy_scores.technical_fit, central.coverage)
    role_confidence = _adjust_role_confidence(float(role_info.get("confidence", 0.5)), central.coverage)
    role_fit = _role_fit_with_structural_confidence(legacy_scores.role_fit, role_confidence, central.coverage)
    application_effort_signal = float(legacy_scores.application_roi)
    data_quality_signal = float(legacy_scores.opportunity_quality)
    source_reliability_signal = _source_reliability(job)
    barrier_absence = max(0.0, 100.0 - legacy_scores.risk_penalty * 2.5)
    narrative_transferability = min(float(role_fit), float(technical_readiness))

    speed_signal = (
        technical_readiness * 0.30
        + legacy_scores.seniority_fit * 0.20
        + barrier_absence * 0.20
        + narrative_transferability * 0.15
        + application_effort_signal * 0.10
        + data_quality_signal * 0.05
        - legacy_scores.risk_penalty
    )
    final_score = max(0, min(100, int(round(speed_signal))))
    decision = decision_from_score(final_score)

    decision, final_score = _apply_hard_overrides(
        decision,
        final_score,
        legacy_evidence.dealbreakers + legacy_evidence.red_flags,
    )
    decision, final_score = _apply_speed_gates(
        decision,
        final_score,
        technical_readiness,
        role_fit,
        central.coverage,
        data_quality_signal,
    )

    escalation_reasons = list(central.escalation_reasons)
    if role_confidence < 0.55:
        escalation_reasons.append("role_confidence_below_threshold")
    requires_llm = bool(escalation_reasons)

    evidence = RankingEvidence(
        strong_matches=legacy_evidence.strong_matches,
        partial_matches=legacy_evidence.partial_matches,
        missing_requirements=legacy_evidence.missing_requirements,
        nice_to_have_matches=legacy_evidence.nice_to_have_matches,
        dealbreakers=legacy_evidence.dealbreakers,
        red_flags=[*legacy_evidence.red_flags, *_coverage_flags(central.coverage, role_confidence)],
        central_requirement_coverage=central.coverage,
        central_requirement_thresholds=central.thresholds,
        central_requirements=[signal.to_dict() for signal in central.central_signals],
        requires_llm_review=requires_llm,
        llm_escalation_reasons=escalation_reasons,
    )
    scores = RankingScores(
        technical_fit=int(round(technical_readiness)),
        seniority_fit=legacy_scores.seniority_fit,
        role_fit=int(round(role_fit)),
        opportunity_quality=int(round(data_quality_signal)),
        application_roi=int(round(application_effort_signal)),
        market_alignment=0,
        risk_penalty=legacy_scores.risk_penalty,
        speed_signal=round(speed_signal, 2),
        technical_readiness=round(technical_readiness, 2),
        central_requirement_coverage=round(central.coverage * 100, 2),
        role_confidence=round(role_confidence * 100, 2),
        application_effort_signal=round(application_effort_signal, 2),
        data_quality_signal=round(data_quality_signal, 2),
        source_reliability_signal=round(source_reliability_signal, 2),
    )

    result = RankingResult(
        final_score=final_score,
        decision=decision,  # type: ignore[arg-type]
        confidence=_estimate_speed_confidence(central.coverage, role_confidence, data_quality_signal, legacy_scores.risk_penalty),
        scores=scores,
        evidence=evidence,
        reasoning_summary=_speed_summary(technical_readiness, role_fit, central.coverage, escalation_reasons),
        recommended_application_angle=_application_angle(role_info, legacy_evidence.strong_matches + legacy_evidence.partial_matches),
        cv_keywords_to_emphasize=_dedupe(legacy_evidence.strong_matches + requirements.tech_stack[:8])[:12],
        cv_keywords_to_avoid_overclaiming=_dedupe(legacy_evidence.missing_requirements)[:10],
        ranking_version=SPEED_RANKING_VERSION,
    )

    if use_llm_fallback and requires_llm and os.getenv("OPENAI_API_KEY"):
        llm_result = rank_job_with_llm(job, profile, model=model)
        return _merge_llm_fallback(llm_result, result, evidence, escalation_reasons)

    return result


def _technical_readiness(legacy_technical_fit: int, coverage: float) -> float:
    readiness = float(legacy_technical_fit)
    if coverage < LOW_COVERAGE_THRESHOLD:
        readiness = min(readiness, 30.0)
    elif coverage < LLM_REVIEW_COVERAGE_THRESHOLD:
        readiness = min(readiness, 45.0)
    return readiness


def _adjust_role_confidence(role_confidence: float, coverage: float) -> float:
    return max(0.15, min(0.95, role_confidence * (0.45 + coverage * 0.55)))


def _role_fit_with_structural_confidence(legacy_role_fit: int, role_confidence: float, coverage: float) -> float:
    role_fit = float(legacy_role_fit)
    if coverage < LOW_COVERAGE_THRESHOLD:
        role_fit = min(role_fit, 35.0)
    elif coverage < LLM_REVIEW_COVERAGE_THRESHOLD or role_confidence < 0.55:
        role_fit = min(role_fit, 55.0)
    return role_fit


def _apply_hard_overrides(decision: str, final_score: int, flags: list[str]) -> tuple[str, int]:
    joined = " ".join(flag.lower() for flag in flags)
    if "unpaid" in joined or "commission only" in joined or "commission-only" in joined:
        return "AVOID", min(final_score, 25)
    if any(term in joined for term in ["relocation", "visa", "manual qa"]):
        return _cap_decision(decision, "SKIP"), min(final_score, 45)
    return decision, final_score


def _apply_speed_gates(
    decision: str,
    final_score: int,
    technical_readiness: float,
    role_fit: float,
    coverage: float,
    data_quality_signal: float,
) -> tuple[str, int]:
    if coverage < LOW_COVERAGE_THRESHOLD or technical_readiness < 35 or role_fit < 40:
        return _cap_decision(decision, "SKIP"), min(final_score, 45)
    if coverage < LLM_REVIEW_COVERAGE_THRESHOLD or technical_readiness < 50 or role_fit < 55:
        return _cap_decision(decision, "MAYBE"), min(final_score, 64)
    if data_quality_signal < 50:
        return _cap_decision(decision, "MAYBE"), min(final_score, 64)
    return decision, final_score


def _source_reliability(job: Any) -> float:
    source = _job_to_dict(job).get("source")
    if source in {"greenhouse", "lever", "ashby"}:
        return 90.0
    if source in {"linkedin_scraper", "adzuna", "remotive", "arbeitnow", "themuse"}:
        return 72.0
    return 55.0


def _coverage_flags(coverage: float, role_confidence: float) -> list[str]:
    flags = []
    if coverage < LOW_COVERAGE_THRESHOLD:
        flags.append(f"Low central requirement coverage: {coverage:.2f}")
    elif coverage < LLM_REVIEW_COVERAGE_THRESHOLD:
        flags.append(f"Central requirement coverage needs review: {coverage:.2f}")
    if role_confidence < 0.55:
        flags.append(f"Low structural role confidence: {role_confidence:.2f}")
    return flags


def _estimate_speed_confidence(coverage: float, role_confidence: float, data_quality: float, risk_penalty: int) -> float:
    confidence = 0.45 + coverage * 0.25 + role_confidence * 0.20 + (data_quality / 100) * 0.10
    confidence -= min(0.12, risk_penalty * 0.01)
    return round(max(0.2, min(0.95, confidence)), 2)


def _speed_summary(technical_readiness: float, role_fit: float, coverage: float, reasons: list[str]) -> str:
    summary = (
        f"Speed-based ranking with technical readiness {technical_readiness:.0f}, "
        f"role viability {role_fit:.0f}, and central requirement coverage {coverage:.2f}."
    )
    if reasons:
        summary += f" Review triggers: {', '.join(reasons)}."
    return summary


def _application_angle(role_info: dict, matches: list[str]) -> str:
    keywords = ", ".join(_dedupe(matches)[:6]) or "verifiable technical overlap"
    role = role_info.get("primary_role", "the role")
    return f"Position around {role} only where the central requirements are covered. Emphasize {keywords}."


def result_to_speed_dict(result: RankingResult) -> dict[str, Any]:
    return result_to_dict(result)


def _merge_llm_fallback(
    llm_result: RankingResult,
    speed_result: RankingResult,
    evidence: RankingEvidence,
    escalation_reasons: list[str],
) -> RankingResult:
    """Keep speed-version metadata while allowing the LLM to adjudicate ambiguous cases."""
    llm_result.ranking_version = SPEED_RANKING_VERSION
    llm_result.scores.speed_signal = speed_result.scores.speed_signal
    llm_result.scores.technical_readiness = speed_result.scores.technical_readiness
    llm_result.scores.central_requirement_coverage = speed_result.scores.central_requirement_coverage
    llm_result.scores.role_confidence = speed_result.scores.role_confidence
    llm_result.scores.application_effort_signal = speed_result.scores.application_effort_signal
    llm_result.scores.data_quality_signal = speed_result.scores.data_quality_signal
    llm_result.scores.source_reliability_signal = speed_result.scores.source_reliability_signal
    llm_result.evidence.central_requirement_coverage = evidence.central_requirement_coverage
    llm_result.evidence.central_requirement_thresholds = evidence.central_requirement_thresholds
    llm_result.evidence.central_requirements = evidence.central_requirements
    llm_result.evidence.requires_llm_review = True
    llm_result.evidence.llm_escalation_reasons = _dedupe([*escalation_reasons, "llm_fallback_applied"])
    return llm_result


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


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = str(value).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
