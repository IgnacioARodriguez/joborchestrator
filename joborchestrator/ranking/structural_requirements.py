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
MIN_REQUIREMENT_BACKED_SIGNALS = 2

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
    "it",
    "its",
    "as",
    "at",
    "in",
    "on",
    "of",
    "to",
    "the",
    "a",
    "an",
    "by",
    "and",
    "or",
    "for",
    "from",
    "this",
    "that",
    "with",
    "using",
    "what",
    "will",
    "do",
    "build",
    "design",
    "maintain",
    "implement",
    "development",
    "job",
    "description",
    "about",
    "company",
    "meet",
    "work",
    "english",
    "spanish",
    "de",
    "del",
    "la",
    "las",
    "el",
    "los",
    "un",
    "una",
    "para",
    "por",
    "con",
    "sin",
    "sobre",
    "como",
    "que",
    "en",
    "te",
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
    raw_coverage: float
    evidence_quality: float
    requirement_backed_signal_count: int
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
    excluded_terms = _source_field_terms(data)
    signals = _extract_requirement_signals(title, description, excluded_terms=excluded_terms)
    _attach_profile_matches(signals, profile)
    central = _select_central_signals(signals)

    total_weight = sum(signal.centrality for signal in central)
    matched_weight = sum(signal.centrality for signal in central if signal.match_type in {"strong", "partial", "weak"})
    raw_coverage = matched_weight / total_weight if total_weight else 0.0
    requirement_backed_count = sum(1 for signal in central if _has_requirement_backing(signal))
    evidence_quality = min(1.0, requirement_backed_count / MIN_REQUIREMENT_BACKED_SIGNALS)
    coverage = round(raw_coverage * evidence_quality, 3)

    reasons: list[str] = []
    if evidence_quality < 1.0:
        reasons.append("insufficient_requirement_backed_evidence")
    if coverage < LOW_COVERAGE_THRESHOLD:
        reasons.append("central_requirement_coverage_below_low_threshold")
    elif coverage < LLM_REVIEW_COVERAGE_THRESHOLD:
        reasons.append("central_requirement_coverage_requires_review")

    return CentralCoverageResult(
        coverage=coverage,
        raw_coverage=round(raw_coverage, 3),
        evidence_quality=round(evidence_quality, 3),
        requirement_backed_signal_count=requirement_backed_count,
        matched_weight=round(matched_weight, 3),
        total_weight=round(total_weight, 3),
        central_signals=central,
        all_signals=signals,
        thresholds={
            "centrality_threshold": CENTRALITY_THRESHOLD,
            "low_coverage_threshold": LOW_COVERAGE_THRESHOLD,
            "llm_review_coverage_threshold": LLM_REVIEW_COVERAGE_THRESHOLD,
            "top_central_requirements": float(TOP_CENTRAL_REQUIREMENTS),
            "min_requirement_backed_signals": float(MIN_REQUIREMENT_BACKED_SIGNALS),
        },
        requires_llm_review=coverage < LLM_REVIEW_COVERAGE_THRESHOLD,
        escalation_reasons=reasons,
    )


def _extract_requirement_signals(
    title: str,
    description: str,
    *,
    excluded_terms: set[str] | None = None,
) -> list[RequirementSignal]:
    excluded_terms = excluded_terms or set()
    accumulator: dict[str, dict[str, Any]] = {}
    position = 0
    for term in _extract_terms(title):
        _add_signal(accumulator, term, 0.48, position, "title", "appears_in_title", excluded_terms=excluded_terms)
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

            _add_signal(
                accumulator,
                term,
                base,
                position,
                active_section,
                *evidence,
                excluded_terms=excluded_terms,
            )
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
    excluded_terms: set[str] | None = None,
) -> None:
    key = normalize_text(term)
    if not key or key in (excluded_terms or set()):
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
    selected = [
        signal
        for signal in signals
        if signal.centrality >= CENTRALITY_THRESHOLD and _has_requirement_backing(signal)
    ]
    if selected:
        return selected[:TOP_CENTRAL_REQUIREMENTS]
    return [signal for signal in signals if signal.centrality > 0.05][:TOP_CENTRAL_REQUIREMENTS]


def _has_requirement_backing(signal: RequirementSignal) -> bool:
    return any(section in {"hard_requirements", "responsibilities", "body"} for section in signal.sections)


def _source_field_terms(data: dict[str, Any]) -> set[str]:
    fields = [
        data.get("company"),
        data.get("location") or data.get("ubicacion"),
        data.get("workplace_type") or data.get("modalidad"),
        data.get("source"),
    ]
    terms: set[str] = set()
    for field in fields:
        for term in _extract_terms(str(field or "")):
            terms.add(normalize_text(term))
        norm = normalize_text(field)
        if norm:
            terms.add(norm)
    return terms


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
