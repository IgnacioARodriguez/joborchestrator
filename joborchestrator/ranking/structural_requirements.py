from __future__ import annotations

import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.ranking.skill_taxonomy import expand_skills, find_skills, skill_match
from joborchestrator.scanning.normalization import normalize_text

CENTRALITY_THRESHOLD = 0.65
LOW_COVERAGE_THRESHOLD = 0.20
LLM_REVIEW_COVERAGE_THRESHOLD = 0.35
TOP_CENTRAL_REQUIREMENTS = 8

HARD_MARKERS = [
    "required",
    "requirements",
    "must have",
    "you have",
    "minimum qualifications",
    "strong experience",
    "proven experience",
    "hands-on",
    "solid experience",
]
NICE_MARKERS = ["nice to have", "bonus", "preferred", "familiarity", "plus", "optional", "desirable"]
RESP_MARKERS = ["responsibilities", "what you will do", "you will", "day to day", "role"]
STOP_TERMS = {
    "engineer",
    "developer",
    "administrator",
    "consultant",
    "specialist",
    "manager",
    "senior",
    "junior",
    "mid",
    "lead",
    "software",
    "systems",
    "system",
    "team",
    "role",
    "experience",
    "knowledge",
    "skills",
    "requirement",
    "requirements",
    "responsibility",
    "responsibilities",
    "required",
    "must",
    "have",
    "you",
    "your",
    "our",
    "we",
    "by",
    "and",
    "or",
    "for",
    "from",
    "this",
    "that",
    "with",
    "using",
    "build",
    "design",
    "maintain",
    "implement",
    "development",
    "work",
    "english",
    "spanish",
}


@dataclass(slots=True)
class RequirementSignal:
    term: str
    centrality: float
    frequency: int
    first_position: int
    sections: list[str]
    evidence: list[str]
    match_type: str = "missing"
    matched_skill: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CentralCoverageResult:
    coverage: float
    matched_weight: float
    total_weight: float
    central_signals: list[RequirementSignal]
    all_signals: list[RequirementSignal]
    thresholds: dict[str, float]
    requires_llm_review: bool
    escalation_reasons: list[str]


def analyze_central_requirements(job: Any, profile: CandidateProfile) -> CentralCoverageResult:
    data = _job_to_dict(job)
    title = str(data.get("title") or data.get("titulo") or "")
    description = str(data.get("description_text") or data.get("description") or data.get("descripcion") or "")
    signals = _extract_requirement_signals(title, description)
    _attach_profile_matches(signals, profile)
    central = _select_central_signals(signals)

    total_weight = sum(signal.centrality for signal in central)
    matched_weight = sum(signal.centrality for signal in central if signal.match_type in {"strong", "partial", "weak"})
    coverage = round(matched_weight / total_weight, 3) if total_weight else 0.0

    reasons: list[str] = []
    if coverage < LOW_COVERAGE_THRESHOLD:
        reasons.append("central_requirement_coverage_below_low_threshold")
    elif coverage < LLM_REVIEW_COVERAGE_THRESHOLD:
        reasons.append("central_requirement_coverage_requires_review")

    return CentralCoverageResult(
        coverage=coverage,
        matched_weight=round(matched_weight, 3),
        total_weight=round(total_weight, 3),
        central_signals=central,
        all_signals=signals,
        thresholds={
            "centrality_threshold": CENTRALITY_THRESHOLD,
            "low_coverage_threshold": LOW_COVERAGE_THRESHOLD,
            "llm_review_coverage_threshold": LLM_REVIEW_COVERAGE_THRESHOLD,
            "top_central_requirements": float(TOP_CENTRAL_REQUIREMENTS),
        },
        requires_llm_review=coverage < LLM_REVIEW_COVERAGE_THRESHOLD,
        escalation_reasons=reasons,
    )


def _extract_requirement_signals(title: str, description: str) -> list[RequirementSignal]:
    accumulator: dict[str, dict[str, Any]] = {}
    position = 0
    for term in _extract_terms(title):
        _add_signal(accumulator, term, 0.66, position, "title", "appears_in_title")
        position += 1

    active_section = "body"
    for line in _split_lines(description):
        norm = normalize_text(line)
        if any(marker in norm for marker in HARD_MARKERS):
            active_section = "hard_requirements"
        elif any(marker in norm for marker in NICE_MARKERS):
            active_section = "nice_to_have"
        elif any(marker in norm for marker in RESP_MARKERS):
            active_section = "responsibilities"

        terms = _extract_terms(line)
        for index, term in enumerate(terms):
            base = 0.16
            evidence = [f"section:{active_section}"]
            if active_section == "hard_requirements":
                base += 0.24
            elif active_section == "responsibilities":
                base += 0.12
            elif active_section == "nice_to_have":
                base -= 0.14

            if any(marker in norm for marker in HARD_MARKERS):
                base += 0.18
                evidence.append("mandatory_language")
            if any(marker in norm for marker in NICE_MARKERS):
                base -= 0.18
                evidence.append("optional_language")
            if index < 5 and active_section in {"hard_requirements", "responsibilities"}:
                base += 0.10
                evidence.append("early_in_section")
            if _usage_context(term, norm):
                base += 0.08
                evidence.append("usage_context")

            _add_signal(accumulator, term, base, position, active_section, *evidence)
            position += 1

    signals = []
    for term, data in accumulator.items():
        frequency_bonus = min(0.20, (data["frequency"] - 1) * 0.05)
        centrality = round(max(0.0, min(1.0, data["score"] + frequency_bonus)), 3)
        signals.append(
            RequirementSignal(
                term=term,
                centrality=centrality,
                frequency=data["frequency"],
                first_position=data["first_position"],
                sections=sorted(data["sections"]),
                evidence=sorted(data["evidence"]),
            )
        )
    return sorted(signals, key=lambda signal: (-signal.centrality, signal.first_position, signal.term))


def _extract_terms(text: str) -> list[str]:
    terms = []
    terms.extend(find_skills(text))
    for raw in re.findall(r"\b[A-Za-z][A-Za-z0-9+#./-]{1,}\b", text):
        cleaned = _clean_term(raw)
        if cleaned:
            terms.append(cleaned)
    return _dedupe(terms)


def _clean_term(term: str) -> str | None:
    cleaned = term.strip(".,;:()[]{}").replace("\\", "/")
    norm = normalize_text(cleaned)
    if not norm or norm in STOP_TERMS:
        return None
    if len(norm) < 2:
        return None
    if cleaned.lower() in STOP_TERMS:
        return None
    is_technical_shape = (
        cleaned.isupper()
        or any(char.isdigit() for char in cleaned)
        or any(char in cleaned for char in ["+", "#", "/", ".", "-"])
        or cleaned[:1].isupper()
    )
    return cleaned if is_technical_shape else None


def _add_signal(
    accumulator: dict[str, dict[str, Any]],
    term: str,
    score: float,
    position: int,
    section: str,
    *evidence: str,
) -> None:
    key = normalize_text(term)
    if not key:
        return
    data = accumulator.setdefault(
        key,
        {
            "term": term,
            "score": 0.0,
            "frequency": 0,
            "first_position": position,
            "sections": set(),
            "evidence": set(),
        },
    )
    data["score"] = max(data["score"], score)
    data["frequency"] += 1
    data["first_position"] = min(data["first_position"], position)
    data["sections"].add(section)
    data["evidence"].update(evidence)


def _attach_profile_matches(signals: list[RequirementSignal], profile: CandidateProfile) -> None:
    strong = set(profile.strong_skills) | expand_skills(profile.strong_skills)
    medium = set(profile.medium_skills) | expand_skills(profile.medium_skills)
    weak = set(profile.weak_skills)
    for signal in signals:
        match_type, matched = skill_match(signal.term, strong, medium, weak)
        signal.match_type = match_type
        signal.matched_skill = matched


def _select_central_signals(signals: list[RequirementSignal]) -> list[RequirementSignal]:
    selected = [signal for signal in signals if signal.centrality >= CENTRALITY_THRESHOLD]
    if selected:
        return selected[:TOP_CENTRAL_REQUIREMENTS]
    return signals[:TOP_CENTRAL_REQUIREMENTS]


def _split_lines(text: str) -> list[str]:
    return [line.strip(" -*•\t") for line in str(text).splitlines() if line.strip()]


def _usage_context(term: str, norm_line: str) -> bool:
    norm_term = normalize_text(term)
    return any(
        f"{verb} {norm_term}" in norm_line or f"{verb} with {norm_term}" in norm_line
        for verb in ["develop", "build", "maintain", "design", "implement", "using", "use", "program"]
    )


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
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
