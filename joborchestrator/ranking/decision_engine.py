from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from joborchestrator.ranking.schemas import (
    Decision,
    RankingEvidence,
    RankingResult,
    RankingScores,
)

RequirementKind = Literal[
    "skill",
    "experience",
    "seniority",
    "role",
    "location",
    "work_mode",
    "language",
    "education",
    "work_authorization",
    "compensation",
    "contract",
    "application_step",
    "other",
]
RequirementImportance = Literal["required", "preferred", "context"]
BlockingBasis = Literal["explicit_eligibility", "explicit_exclusion", "inferred", "unclear"]
MatchStatus = Literal["strong", "partial", "missing", "unknown", "not_applicable"]
PostingValidity = Literal["valid", "incomplete", "invalid"]

VALID_REQUIREMENT_KINDS = {
    "skill",
    "experience",
    "seniority",
    "role",
    "location",
    "work_mode",
    "language",
    "education",
    "work_authorization",
    "compensation",
    "contract",
    "application_step",
    "other",
}
VALID_IMPORTANCE = {"required", "preferred", "context"}
VALID_VALIDITY = {"valid", "incomplete", "invalid"}
VALID_EFFORT = {"low", "medium", "high", "blocking"}
VALID_BLOCKING_BASIS = {"explicit_eligibility", "explicit_exclusion", "inferred", "unclear"}

_ELIGIBILITY_KINDS = {
    "location",
    "work_mode",
    "language",
    "education",
    "work_authorization",
    "compensation",
    "contract",
}
_FIT_KINDS = {"skill", "experience", "seniority", "role"}
_MATCH_VALUE: dict[MatchStatus, float] = {
    "strong": 1.0,
    "partial": 0.55,
    "unknown": 0.20,
    "missing": 0.0,
    "not_applicable": 1.0,
}
_REQUIREMENT_WEIGHT: dict[str, float] = {
    "skill": 1.00,
    "experience": 1.05,
    "seniority": 1.05,
    "role": 1.00,
    "location": 1.20,
    "work_mode": 1.15,
    "language": 1.10,
    "education": 1.00,
    "work_authorization": 1.20,
    "compensation": 1.10,
    "contract": 1.05,
    "application_step": 0.0,
    "other": 0.85,
}
_DECISION_SCORE_BANDS: dict[Decision, tuple[int, int]] = {
    "APPLY_NOW": (65, 100),
    "APPLY_WITH_TAILORED_CV": (50, 84),
    "MAYBE": (30, 69),
    "SKIP": (10, 49),
    "AVOID": (0, 34),
}


@dataclass(frozen=True, slots=True)
class RequirementFact:
    requirement_id: str
    text: str
    kind: RequirementKind
    importance: RequirementImportance
    blocking: bool = False
    blocking_basis: BlockingBasis = "unclear"
    alternatives: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    minimum_value: float | None = None
    unit: str | None = None
    evidence: str = ""
    confidence: float = 1.0
    comparison_confidence: float | None = None
    comparison_status: MatchStatus | None = None


@dataclass(frozen=True, slots=True)
class JobFacts:
    job_id: int
    validity: PostingValidity
    validity_evidence: str
    requirements: tuple[RequirementFact, ...]
    application_effort: str
    application_effort_evidence: tuple[str, ...]
    data_quality: float
    source_reliability: float
    extraction_confidence: float


@dataclass(frozen=True, slots=True)
class RequirementAssessment:
    fact: RequirementFact
    status: MatchStatus
    candidate_evidence: tuple[str, ...] = ()
    reason: str = ""


@dataclass(slots=True)
class CandidateIndex:
    strong_skills: set[str] = field(default_factory=set)
    partial_skills: set[str] = field(default_factory=set)
    weak_skills: set[str] = field(default_factory=set)
    target_roles: set[str] = field(default_factory=set)
    secondary_roles: set[str] = field(default_factory=set)
    locations: set[str] = field(default_factory=set)
    work_modes: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    education: set[str] = field(default_factory=set)
    authorizations: set[str] = field(default_factory=set)
    contract_preferences: set[str] = field(default_factory=set)
    dealbreakers: set[str] = field(default_factory=set)
    experience_years: float | None = None
    min_salary: float | None = None


def parse_job_facts(payload: dict[str, Any], *, expected_job_id: int | None = None) -> JobFacts:
    job_id = _int_value(payload.get("job_id"))
    if job_id is None:
        raise ValueError("job facts require integer job_id")
    if expected_job_id is not None and job_id != int(expected_job_id):
        raise ValueError(f"job facts job_id mismatch: expected {expected_job_id}, got {job_id}")

    posting = payload.get("posting") if isinstance(payload.get("posting"), dict) else {}
    validity_raw = _normalized_enum(posting.get("validity"), VALID_VALIDITY, "incomplete")
    requirements_raw = payload.get("requirements")
    if not isinstance(requirements_raw, list):
        raise ValueError(f"job_id {job_id}: requirements must be an array")

    requirements = tuple(
        _parse_requirement(item, index=index)
        for index, item in enumerate(requirements_raw)
        if isinstance(item, dict)
    )
    effort = payload.get("application_effort") if isinstance(payload.get("application_effort"), dict) else {}
    effort_level = _normalized_enum(effort.get("level"), VALID_EFFORT, "medium")
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    extraction_confidence = _ratio(
        payload.get("extraction_confidence"),
        default=_ratio(posting.get("confidence"), default=0.65),
    )
    return JobFacts(
        job_id=job_id,
        validity=cast(PostingValidity, validity_raw),
        validity_evidence=str(posting.get("evidence") or "").strip(),
        requirements=requirements,
        application_effort=effort_level,
        application_effort_evidence=tuple(_string_list(effort.get("evidence"))),
        data_quality=_percentage(quality.get("score"), default=65.0),
        source_reliability=_percentage(quality.get("source_reliability"), default=65.0),
        extraction_confidence=extraction_confidence,
    )


def rank_job_facts(
    job: dict[str, Any],
    facts_payload: dict[str, Any] | JobFacts,
    candidate_profile: dict[str, Any],
    *,
    ranking_version: str,
) -> RankingResult:
    job_id = _int_value(job.get("id") or job.get("job_id"))
    facts = (
        facts_payload
        if isinstance(facts_payload, JobFacts)
        else parse_job_facts(facts_payload, expected_job_id=job_id)
    )
    candidate = build_candidate_index(candidate_profile)
    assessments = tuple(_assess_requirement(fact, candidate) for fact in facts.requirements)

    required = tuple(
        item
        for item in assessments
        if item.fact.importance == "required" and item.fact.kind != "application_step"
    )
    preferred = tuple(item for item in assessments if item.fact.importance == "preferred")
    missing_required = tuple(item for item in required if item.status == "missing")
    unknown_required = tuple(item for item in required if item.status == "unknown")
    partial_required = tuple(item for item in required if item.status == "partial")
    hard_blockers = tuple(
        item
        for item in missing_required
        if item.fact.blocking or item.fact.kind in _ELIGIBILITY_KINDS
    )

    coverage = _weighted_coverage(required)
    raw_coverage = _raw_coverage(required)
    evidence_quality = _evidence_quality(required)
    technical_fit = _subset_score(required, {"skill"}, fallback=coverage)
    seniority_fit = _subset_score(required, {"experience", "seniority"}, fallback=coverage)
    role_fit = _role_fit_score(job, required, candidate, coverage)
    market_alignment = _subset_score(required, _ELIGIBILITY_KINDS, fallback=coverage)
    opportunity_quality = _clamp_score(facts.data_quality * 0.65 + facts.source_reliability * 0.35)
    application_effort = _application_effort_score(facts.application_effort)
    risk_penalty = _risk_penalty(
        facts=facts,
        missing_required=missing_required,
        unknown_required=unknown_required,
        partial_required=partial_required,
        hard_blockers=hard_blockers,
    )
    application_roi = _clamp_score(
        coverage * 65.0 + application_effort * 0.20 + opportunity_quality * 0.15 - risk_penalty * 0.45
    )

    decision = _decide(
        facts=facts,
        required=required,
        coverage=coverage,
        missing_required=missing_required,
        unknown_required=unknown_required,
        partial_required=partial_required,
        hard_blockers=hard_blockers,
    )
    natural_score = _clamp_score(
        technical_fit * 0.28
        + seniority_fit * 0.16
        + role_fit * 0.20
        + market_alignment * 0.14
        + opportunity_quality * 0.10
        + application_effort * 0.12
        - risk_penalty * 0.55
    )
    final_score = _score_for_decision(natural_score, decision)
    confidence = _confidence(facts, required, assessments)
    evidence = _build_evidence(
        facts=facts,
        assessments=assessments,
        required=required,
        preferred=preferred,
        coverage=coverage,
        raw_coverage=raw_coverage,
        evidence_quality=evidence_quality,
        decision=decision,
        hard_blockers=hard_blockers,
        unknown_required=unknown_required,
        partial_required=partial_required,
    )
    strong_terms = _assessment_terms(assessments, {"strong"}, kinds=_FIT_KINDS)
    partial_terms = _assessment_terms(assessments, {"partial"}, kinds=_FIT_KINDS)
    avoid_terms = _assessment_terms(assessments, {"missing", "unknown"}, kinds=_FIT_KINDS)

    return RankingResult(
        final_score=final_score,
        decision=decision,
        confidence=confidence,
        scores=RankingScores(
            technical_fit=technical_fit,
            seniority_fit=seniority_fit,
            role_fit=role_fit,
            opportunity_quality=opportunity_quality,
            application_roi=application_roi,
            market_alignment=market_alignment,
            risk_penalty=risk_penalty,
            technical_readiness=technical_fit,
            central_requirement_coverage=coverage * 100.0,
            role_confidence=confidence * 100.0,
            application_effort_signal=application_effort,
            data_quality_signal=facts.data_quality,
            source_reliability_signal=facts.source_reliability,
        ),
        evidence=evidence,
        reasoning_summary=_reasoning_summary(required, decision, facts.validity),
        recommended_application_angle=_application_angle(strong_terms, partial_terms, avoid_terms),
        cv_keywords_to_emphasize=_dedupe([*strong_terms, *partial_terms]),
        cv_keywords_to_avoid_overclaiming=_dedupe(avoid_terms),
        ranking_version=ranking_version,
    )


def build_candidate_index(profile: dict[str, Any]) -> CandidateIndex:
    index = CandidateIndex()
    for item in profile.get("skills") or []:
        if not isinstance(item, dict):
            continue
        names = [item.get("name"), *list(item.get("aliases") or [])]
        level = _normalize_text(str(item.get("level") or ""))
        target = (
            index.strong_skills
            if level == "strong"
            else index.partial_skills
            if level in {"medium", "partial", "working", "familiar"}
            else index.weak_skills
        )
        target.update(_normalized_values(names))
    index.strong_skills.update(_normalized_values(profile.get("strong_skills")))
    index.partial_skills.update(_normalized_values(profile.get("medium_skills")))
    index.weak_skills.update(_normalized_values(profile.get("weak_skills")))

    index.target_roles.update(_normalized_values(profile.get("target_roles")))
    index.secondary_roles.update(_normalized_values(profile.get("secondary_roles")))
    role_aliases = profile.get("role_aliases")
    if isinstance(role_aliases, dict):
        for role, aliases in role_aliases.items():
            normalized_role = _normalize_text(str(role))
            target = index.target_roles if normalized_role in index.target_roles else index.secondary_roles
            target.update(_normalized_values(aliases))

    index.locations.update(_normalized_values(profile.get("preferred_locations")))
    index.work_modes.update(_normalized_values(profile.get("preferred_work_modes")))
    index.languages.update(_normalized_values(profile.get("languages")))
    index.education.update(_normalized_values(profile.get("education")))
    index.authorizations.update(
        _normalized_values(
            profile.get("work_authorizations")
            or profile.get("authorizations")
            or profile.get("work_authorization")
        )
    )
    index.contract_preferences.update(
        _normalized_values(profile.get("preferred_contract_types") or profile.get("contract_preferences"))
    )
    index.dealbreakers.update(_normalized_values(profile.get("dealbreakers")))
    index.experience_years = _float_value(profile.get("real_experience_years"))
    index.min_salary = _float_value(profile.get("min_salary"))
    return index


def _parse_requirement(payload: dict[str, Any], *, index: int) -> RequirementFact:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError(f"requirement index {index} is missing text")
    kind = _normalized_enum(payload.get("kind"), VALID_REQUIREMENT_KINDS, "other")
    importance = _normalized_enum(payload.get("importance"), VALID_IMPORTANCE, "context")
    raw_blocking = bool(payload.get("blocking", False))
    raw_basis = payload.get("blocking_basis")
    default_basis = "explicit_eligibility" if raw_blocking and kind in _ELIGIBILITY_KINDS else "unclear"
    blocking_basis = _normalized_enum(raw_basis, VALID_BLOCKING_BASIS, default_basis)
    evidence = str(payload.get("evidence") or text).strip()
    confidence = _ratio(payload.get("confidence"), default=0.75)
    comparison_confidence = _ratio(payload.get("comparison_confidence"), default=None)
    comparison_status_raw = payload.get("comparison_status")
    comparison_status = (
        cast(MatchStatus, comparison_status_raw)
        if comparison_status_raw in _MATCH_VALUE
        else None
    )
    blocking = raw_blocking and blocking_basis in {"explicit_eligibility", "explicit_exclusion"} and confidence >= 0.85 and bool(evidence)
    return RequirementFact(
        requirement_id=str(payload.get("id") or f"requirement_{index + 1}"),
        text=text,
        kind=cast(RequirementKind, kind),
        importance=cast(RequirementImportance, importance),
        blocking=blocking,
        blocking_basis=cast(BlockingBasis, blocking_basis),
        alternatives=tuple(_string_list(payload.get("alternatives"))),
        allowed_values=tuple(_string_list(payload.get("allowed_values"))),
        minimum_value=_float_value(payload.get("minimum_value")),
        unit=str(payload.get("unit") or "").strip() or None,
        evidence=evidence,
        confidence=confidence,
        comparison_confidence=comparison_confidence,
        comparison_status=comparison_status,
    )


def _assess_requirement(fact: RequirementFact, candidate: CandidateIndex) -> RequirementAssessment:
    if fact.comparison_status is not None:
        return RequirementAssessment(fact=fact, status=fact.comparison_status, reason="llm_comparison")
    terms = _requirement_terms(fact)
    dealbreaker_matches = _matching_values(terms, candidate.dealbreakers)
    if dealbreaker_matches:
        return RequirementAssessment(
            fact=fact,
            status="missing",
            candidate_evidence=tuple(dealbreaker_matches),
            reason="candidate_dealbreaker",
        )

    if fact.kind == "skill":
        return _assess_term_sets(fact, terms, candidate.strong_skills, candidate.partial_skills | candidate.weak_skills)
    if fact.kind == "role":
        return _assess_term_sets(fact, terms, candidate.target_roles, candidate.secondary_roles)
    if fact.kind in {"experience", "seniority"}:
        if fact.minimum_value is None or candidate.experience_years is None:
            return RequirementAssessment(fact=fact, status="unknown", reason="structured_value_unavailable")
        if candidate.experience_years >= fact.minimum_value:
            return RequirementAssessment(
                fact=fact,
                status="strong",
                candidate_evidence=(str(candidate.experience_years),),
                reason="minimum_satisfied",
            )
        if candidate.experience_years >= fact.minimum_value * 0.75:
            return RequirementAssessment(
                fact=fact,
                status="partial",
                candidate_evidence=(str(candidate.experience_years),),
                reason="minimum_nearly_satisfied",
            )
        return RequirementAssessment(
            fact=fact,
            status="missing",
            candidate_evidence=(str(candidate.experience_years),),
            reason="minimum_not_satisfied",
        )
    if fact.kind == "location":
        return _assess_value_set(fact, terms, candidate.locations)
    if fact.kind == "work_mode":
        return _assess_value_set(fact, terms, candidate.work_modes)
    if fact.kind == "language":
        return _assess_value_set(fact, terms, candidate.languages)
    if fact.kind == "education":
        return _assess_value_set(fact, terms, candidate.education)
    if fact.kind == "work_authorization":
        return _assess_value_set(fact, terms, candidate.authorizations)
    if fact.kind == "contract":
        return _assess_value_set(fact, terms, candidate.contract_preferences)
    if fact.kind == "compensation":
        if fact.minimum_value is None or candidate.min_salary is None:
            return RequirementAssessment(fact=fact, status="unknown", reason="structured_value_unavailable")
        if fact.minimum_value >= candidate.min_salary:
            return RequirementAssessment(
                fact=fact,
                status="strong",
                candidate_evidence=(str(candidate.min_salary),),
                reason="minimum_satisfied",
            )
        return RequirementAssessment(
            fact=fact,
            status="missing",
            candidate_evidence=(str(candidate.min_salary),),
            reason="minimum_not_satisfied",
        )
    if fact.kind == "application_step":
        return RequirementAssessment(fact=fact, status="not_applicable", reason="operational_requirement")
    if fact.importance == "context":
        return RequirementAssessment(fact=fact, status="not_applicable", reason="context_only")
    return RequirementAssessment(fact=fact, status="unknown", reason="unsupported_structured_comparison")


def _assess_term_sets(
    fact: RequirementFact,
    terms: set[str],
    strong_values: set[str],
    partial_values: set[str],
) -> RequirementAssessment:
    strong = _matching_values(terms, strong_values)
    if strong:
        return RequirementAssessment(fact=fact, status="strong", candidate_evidence=tuple(strong), reason="profile_supported")
    partial = _matching_values(terms, partial_values)
    if partial:
        return RequirementAssessment(fact=fact, status="partial", candidate_evidence=tuple(partial), reason="profile_partial")
    return RequirementAssessment(fact=fact, status="missing", reason="profile_support_missing")


def _assess_value_set(fact: RequirementFact, terms: set[str], values: set[str]) -> RequirementAssessment:
    if not values:
        return RequirementAssessment(fact=fact, status="unknown", reason="candidate_constraint_unavailable")
    matches = _matching_values(terms, values)
    if matches:
        return RequirementAssessment(fact=fact, status="strong", candidate_evidence=tuple(matches), reason="constraint_satisfied")
    return RequirementAssessment(fact=fact, status="missing", reason="constraint_not_satisfied")


def _requirement_terms(fact: RequirementFact) -> set[str]:
    return _normalized_values([fact.text, *fact.alternatives, *fact.allowed_values])


def _matching_values(requirement_values: set[str], candidate_values: set[str]) -> list[str]:
    matches: list[str] = []
    for candidate in sorted(candidate_values):
        for required in requirement_values:
            if _value_matches(required, candidate):
                matches.append(candidate)
                break
    return matches


def _value_matches(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if len(left_tokens) == 1 or len(right_tokens) == 1:
        return left in right or right in left
    overlap = len(left_tokens & right_tokens)
    return overlap / max(1, min(len(left_tokens), len(right_tokens))) >= 0.8


def _weighted_coverage(items: tuple[RequirementAssessment, ...]) -> float:
    weighted_total = 0.0
    weights = 0.0
    for item in items:
        weight = _REQUIREMENT_WEIGHT.get(item.fact.kind, 0.85)
        if weight <= 0:
            continue
        weighted_total += _MATCH_VALUE[item.status] * weight
        weights += weight
    if weights == 0:
        return 0.0
    return max(0.0, min(1.0, weighted_total / weights))


def _raw_coverage(items: tuple[RequirementAssessment, ...]) -> float:
    if not items:
        return 0.0
    supported = sum(1 for item in items if item.status in {"strong", "partial"})
    return supported / len(items)


def _evidence_quality(items: tuple[RequirementAssessment, ...]) -> float:
    if not items:
        return 0.0
    return sum(item.fact.confidence for item in items) / len(items)


def _subset_score(
    items: tuple[RequirementAssessment, ...],
    kinds: set[str],
    *,
    fallback: float,
) -> int:
    selected = tuple(item for item in items if item.fact.kind in kinds)
    return _clamp_score((_weighted_coverage(selected) if selected else fallback) * 100.0)


def _role_fit_score(
    job: dict[str, Any],
    required: tuple[RequirementAssessment, ...],
    candidate: CandidateIndex,
    coverage: float,
) -> int:
    role_requirements = tuple(item for item in required if item.fact.kind == "role")
    if role_requirements:
        return _clamp_score(_weighted_coverage(role_requirements) * 100.0)
    title = _normalize_text(str(job.get("title") or ""))
    if not title:
        return _clamp_score(coverage * 100.0)
    if _matching_values({title}, candidate.target_roles):
        return 100
    if _matching_values({title}, candidate.secondary_roles):
        return 65
    return _clamp_score(coverage * 75.0)


def _risk_penalty(
    *,
    facts: JobFacts,
    missing_required: tuple[RequirementAssessment, ...],
    unknown_required: tuple[RequirementAssessment, ...],
    partial_required: tuple[RequirementAssessment, ...],
    hard_blockers: tuple[RequirementAssessment, ...],
) -> int:
    if facts.validity == "invalid" or hard_blockers:
        return 40
    risk = len(missing_required) * 8 + len(unknown_required) * 4 + len(partial_required) * 2
    if facts.validity == "incomplete":
        risk += 8
    if facts.application_effort == "high":
        risk += 5
    elif facts.application_effort == "blocking":
        risk += 12
    return max(0, min(40, int(risk)))


def _decide(
    *,
    facts: JobFacts,
    required: tuple[RequirementAssessment, ...],
    coverage: float,
    missing_required: tuple[RequirementAssessment, ...],
    unknown_required: tuple[RequirementAssessment, ...],
    partial_required: tuple[RequirementAssessment, ...],
    hard_blockers: tuple[RequirementAssessment, ...],
) -> Decision:
    if facts.validity == "invalid" or hard_blockers:
        return cast(Decision, "AVOID")
    if not required or facts.validity == "incomplete":
        return cast(Decision, "MAYBE")
    missing_pressure = len(missing_required) / max(1, len(required))
    if coverage < 0.45 or missing_pressure >= 0.40:
        return cast(Decision, "SKIP")
    if coverage < 0.65 or unknown_required:
        return cast(Decision, "MAYBE")
    if coverage < 0.88 or partial_required or facts.application_effort in {"high", "blocking"}:
        return cast(Decision, "APPLY_WITH_TAILORED_CV")
    return cast(Decision, "APPLY_NOW")


def _score_for_decision(score: int, decision: Decision) -> int:
    low, high = _DECISION_SCORE_BANDS[decision]
    return max(low, min(high, score))


def _confidence(
    facts: JobFacts,
    required: tuple[RequirementAssessment, ...],
    assessments: tuple[RequirementAssessment, ...],
) -> float:
    known = sum(1 for item in required if item.status not in {"unknown"})
    known_ratio = known / len(required) if required else 0.35
    evidence_ratio = (
        sum(
            item.fact.comparison_confidence
            if item.fact.comparison_confidence is not None
            else item.fact.confidence
            for item in assessments
        ) / len(assessments)
        if assessments
        else 0.35
    )
    value = facts.extraction_confidence * 0.50 + known_ratio * 0.30 + evidence_ratio * 0.20
    return round(max(0.10, min(0.98, value)), 4)


def _build_evidence(
    *,
    facts: JobFacts,
    assessments: tuple[RequirementAssessment, ...],
    required: tuple[RequirementAssessment, ...],
    preferred: tuple[RequirementAssessment, ...],
    coverage: float,
    raw_coverage: float,
    evidence_quality: float,
    decision: Decision,
    hard_blockers: tuple[RequirementAssessment, ...],
    unknown_required: tuple[RequirementAssessment, ...],
    partial_required: tuple[RequirementAssessment, ...],
) -> RankingEvidence:
    strong = _assessment_terms(assessments, {"strong"})
    partial = _assessment_terms(assessments, {"partial"})
    missing = _assessment_terms(required, {"missing", "unknown"})
    preferred_matches = _assessment_terms(preferred, {"strong", "partial"})
    dealbreakers = _assessment_terms(hard_blockers, {"missing"})
    red_flags: list[str] = []
    if facts.validity != "valid" and facts.validity_evidence:
        red_flags.append(facts.validity_evidence)
    red_flags.extend(_assessment_terms(unknown_required, {"unknown"}))
    reasons: list[str] = []
    if hard_blockers:
        reasons.append("deterministic_hard_blocker")
    if unknown_required:
        reasons.append("deterministic_unknown_required")
    if partial_required:
        reasons.append("deterministic_partial_required")
    if facts.validity != "valid":
        reasons.append("deterministic_posting_quality_review")
    central = [
        {
            "id": item.fact.requirement_id,
            "requirement": item.fact.text,
            "kind": item.fact.kind,
            "importance": item.fact.importance,
            "blocking": item.fact.blocking,
            "blocking_basis": item.fact.blocking_basis,
            "match": item.status,
            "candidate_evidence": list(item.candidate_evidence),
            "job_evidence": item.fact.evidence,
            "reason": item.reason,
        }
        for item in required
    ]
    return RankingEvidence(
        strong_matches=_dedupe(strong),
        partial_matches=_dedupe(partial),
        missing_requirements=_dedupe(missing),
        nice_to_have_matches=_dedupe(preferred_matches),
        dealbreakers=_dedupe(dealbreakers),
        red_flags=_dedupe(red_flags),
        central_requirement_coverage=round(coverage, 4),
        central_requirement_raw_coverage=round(raw_coverage, 4),
        central_requirement_evidence_quality=round(evidence_quality, 4),
        requirement_backed_signal_count=len(required),
        central_requirement_thresholds={
            "apply_now": 0.88,
            "tailored": 0.65,
            "skip": 0.45,
        },
        central_requirements=central,
        requires_llm_review=decision != "APPLY_NOW",
        llm_escalation_reasons=reasons,
    )


def _reasoning_summary(
    required: tuple[RequirementAssessment, ...],
    decision: Decision,
    validity: PostingValidity,
) -> str:
    strong = sum(1 for item in required if item.status == "strong")
    partial = sum(1 for item in required if item.status == "partial")
    missing = sum(1 for item in required if item.status == "missing")
    unknown = sum(1 for item in required if item.status == "unknown")
    unresolved = [item.fact.text for item in required if item.status in {"missing", "unknown"}][:3]
    suffix = f" Unresolved requirements: {', '.join(unresolved)}." if unresolved else ""
    return (
        f"Deterministic decision {decision}: posting={validity}; required support "
        f"strong={strong}, partial={partial}, missing={missing}, unknown={unknown}."
        f"{suffix}"
    )


def _application_angle(strong: list[str], partial: list[str], avoid: list[str]) -> str:
    parts: list[str] = []
    if strong:
        parts.append("Lead with verified support for " + ", ".join(strong[:4]) + ".")
    if partial:
        parts.append("Position adjacent support for " + ", ".join(partial[:3]) + " without overstating it.")
    if avoid:
        parts.append("Do not claim unsupported requirements: " + ", ".join(avoid[:3]) + ".")
    return " ".join(parts) or "Verify the extracted requirements before investing application effort."


def _assessment_terms(
    assessments: tuple[RequirementAssessment, ...],
    statuses: set[MatchStatus],
    *,
    kinds: set[str] | None = None,
) -> list[str]:
    return [
        item.fact.text
        for item in assessments
        if item.status in statuses and (kinds is None or item.fact.kind in kinds)
    ]


def _application_effort_score(level: str) -> int:
    return {"low": 90, "medium": 65, "high": 35, "blocking": 0}.get(level, 65)


def _normalized_values(value: Any) -> set[str]:
    return {_normalize_text(item) for item in _string_list(value) if _normalize_text(item)}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [str(item) for item in value.values() if str(item).strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _normalized_enum(value: Any, allowed: set[str], default: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    return normalized if normalized in allowed else default


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


def _ratio(value: Any, *, default: float) -> float:
    number = _float_value(value)
    if number is None:
        return default
    if number > 1:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _percentage(value: Any, *, default: float) -> float:
    number = _float_value(value)
    if number is None:
        return default
    if 0 <= number <= 1:
        number *= 100.0
    return max(0.0, min(100.0, number))


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_value(value: Any) -> int | None:
    number = _float_value(value)
    if number is None or int(number) != number:
        return None
    return int(number)


def _clamp_score(value: Any) -> int:
    number = _float_value(value)
    if number is None:
        return 0
    return max(0, min(100, int(round(number))))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(str(value))
    return result
