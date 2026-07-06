from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Decision = Literal["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"]

VALID_DECISIONS = {"APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"}


def clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


@dataclass(slots=True)
class CandidateProfile:
    target_roles: list[str] = field(default_factory=list)
    secondary_roles: list[str] = field(default_factory=list)
    strong_skills: list[str] = field(default_factory=list)
    medium_skills: list[str] = field(default_factory=list)
    weak_skills: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    preferred_work_modes: list[str] = field(default_factory=list)
    min_salary: int | None = None
    dealbreakers: list[str] = field(default_factory=list)
    avoid_roles: list[str] = field(default_factory=list)
    real_experience_years: float = 0.0
    notes: str | None = None


@dataclass(slots=True)
class JobRequirements:
    hard_requirements: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    required_years: float | None = None
    seniority_level: str | None = None
    location_constraints: list[str] = field(default_factory=list)
    language_requirements: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    compensation: str | None = None
    role_signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankingScores:
    technical_fit: int
    seniority_fit: int
    role_fit: int
    opportunity_quality: int
    application_roi: int
    market_alignment: int
    risk_penalty: int
    speed_signal: float | None = None
    technical_readiness: float | None = None
    central_requirement_coverage: float | None = None
    role_confidence: float | None = None
    application_effort_signal: float | None = None
    data_quality_signal: float | None = None
    source_reliability_signal: float | None = None

    def __post_init__(self) -> None:
        self.technical_fit = clamp(self.technical_fit)
        self.seniority_fit = clamp(self.seniority_fit)
        self.role_fit = clamp(self.role_fit)
        self.opportunity_quality = clamp(self.opportunity_quality)
        self.application_roi = clamp(self.application_roi)
        self.market_alignment = clamp(self.market_alignment)
        self.risk_penalty = clamp(self.risk_penalty, 0, 40)
        for name in [
            "speed_signal",
            "technical_readiness",
            "central_requirement_coverage",
            "role_confidence",
            "application_effort_signal",
            "data_quality_signal",
            "source_reliability_signal",
        ]:
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, max(0.0, min(100.0, float(value))))


@dataclass(slots=True)
class RankingEvidence:
    strong_matches: list[str] = field(default_factory=list)
    partial_matches: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    nice_to_have_matches: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    central_requirement_coverage: float | None = None
    central_requirement_raw_coverage: float | None = None
    central_requirement_evidence_quality: float | None = None
    requirement_backed_signal_count: int | None = None
    central_requirement_thresholds: dict[str, float] = field(default_factory=dict)
    central_requirements: list[dict[str, Any]] = field(default_factory=list)
    requires_llm_review: bool = False
    llm_escalation_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankingResult:
    final_score: int
    decision: Decision
    confidence: float
    scores: RankingScores
    evidence: RankingEvidence
    reasoning_summary: str
    recommended_application_angle: str
    cv_keywords_to_emphasize: list[str]
    cv_keywords_to_avoid_overclaiming: list[str]
    ranking_version: str

    def __post_init__(self) -> None:
        self.final_score = clamp(self.final_score)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.decision not in VALID_DECISIONS:
            raise ValueError(f"Invalid decision: {self.decision}")
