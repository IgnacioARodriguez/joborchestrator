from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from joborchestrator.ranking.risk_detector import detect_risks
from joborchestrator.ranking.role_classifier import classify_role
from joborchestrator.ranking.roi_scorer import score_application_roi
from joborchestrator.ranking.schemas import CandidateProfile, JobRequirements, RankingEvidence, RankingScores
from joborchestrator.ranking.skill_taxonomy import expand_skills, skill_match
from joborchestrator.scanning.normalization import normalize_text


def score_fit(
    job: Any,
    requirements: JobRequirements,
    profile: CandidateProfile,
) -> tuple[RankingScores, RankingEvidence, dict]:
    strong = set(profile.strong_skills)
    medium = set(profile.medium_skills)
    weak = set(profile.weak_skills)
    strong_expanded = expand_skills(profile.strong_skills)
    medium_expanded = expand_skills(profile.medium_skills)

    evidence = RankingEvidence()
    hard_skills = requirements.tech_stack or requirements.hard_requirements
    hard_weight = 0
    achieved = 0.0
    for req in hard_skills:
        match_type, matched = skill_match(req, strong | strong_expanded, medium | medium_expanded, weak)
        hard_weight += 1
        if match_type == "strong":
            achieved += 1.0
            evidence.strong_matches.append(req)
        elif match_type == "partial":
            achieved += 0.55
            evidence.partial_matches.append(f"{req}: adjacent to {matched}")
        elif match_type == "weak":
            achieved += 0.35
            evidence.partial_matches.append(f"{req}: weak/background exposure")
        else:
            evidence.missing_requirements.append(req)

    nice_weight = 0
    nice_achieved = 0.0
    for req in requirements.nice_to_have:
        match_type, matched = skill_match(req, strong | strong_expanded, medium | medium_expanded, weak)
        if match_type in {"strong", "partial", "weak"}:
            nice_achieved += 1.0 if match_type == "strong" else 0.6
            evidence.nice_to_have_matches.append(req if match_type == "strong" else f"{req}: adjacent to {matched}")
        nice_weight += 1

    if hard_weight:
        technical_fit = int((achieved / hard_weight) * 82)
        if nice_weight:
            technical_fit += int((nice_achieved / nice_weight) * 12)
        technical_fit += 6 if any(normalize_text(skill) == "python" for skill in evidence.strong_matches) else 0
    else:
        technical_fit = 52
    if evidence.missing_requirements:
        central_missing = [x for x in evidence.missing_requirements if normalize_text(x) in {"python", "backend", "api", "rest apis"}]
        technical_fit -= 25 if central_missing else min(18, len(evidence.missing_requirements) * 4)
    technical_fit = _clamp(technical_fit)

    seniority_fit = _score_seniority(requirements, profile)
    role_info = classify_role(job, requirements)
    role_fit = _score_role(role_info["primary_role"], role_info["secondary_roles"], requirements)
    market_alignment = _score_market_alignment(requirements, role_info)
    opportunity_quality = _score_opportunity_quality(job, requirements)
    red_flags, risk_penalty = detect_risks(job, requirements, profile)
    evidence.red_flags = red_flags
    evidence.dealbreakers = requirements.dealbreakers[:]
    application_roi = score_application_roi(job, requirements, technical_fit, role_fit, seniority_fit, risk_penalty)

    return (
        RankingScores(
            technical_fit=technical_fit,
            seniority_fit=seniority_fit,
            role_fit=role_fit,
            opportunity_quality=opportunity_quality,
            application_roi=application_roi,
            market_alignment=market_alignment,
            risk_penalty=risk_penalty,
        ),
        evidence,
        role_info,
    )


def _score_seniority(requirements: JobRequirements, profile: CandidateProfile) -> int:
    years = requirements.required_years
    level = requirements.seniority_level
    if years is None:
        base = 72
    elif years <= profile.real_experience_years + 0.5:
        base = 88
    elif years <= 5:
        base = 68
    elif years < 7:
        base = 52
    else:
        base = 25
    if level == "principal/staff":
        base -= 28
    elif level == "senior" and profile.real_experience_years < 5:
        base -= 8
    elif level == "junior":
        base -= 22
    return _clamp(base)


def _score_role(primary: str, secondary: list[str], requirements: JobRequirements) -> int:
    mapping = {
        "Backend Engineer": 92,
        "Python Developer": 90,
        "Full Stack Engineer": 78,
        "ML/AI Engineer": 64 if "Python" in requirements.tech_stack else 50,
        "Data Engineer": 62,
        "Solutions Engineer": 62,
        "Technical Consultant": 58,
        "DevOps/Platform Engineer": 36,
        "Frontend Engineer": 28,
        "QA/Automation Engineer": 34,
        "Product Manager": 22,
        "Sales/Pre-sales": 24,
        "Other": 45,
    }
    score = mapping.get(primary, 45)
    if primary == "Frontend Engineer" and any(role in secondary for role in ["Full Stack Engineer", "Backend Engineer"]):
        score = 66
    return _clamp(score)


def _score_market_alignment(requirements: JobRequirements, role_info: dict) -> int:
    text = normalize_text(" ".join(requirements.tech_stack + requirements.role_signals + [role_info["primary_role"]]))
    score = 50
    for signal in ["python", "backend", "api", "cloud", "aws", "llm", "ai", "automation", "saas", "platform"]:
        if signal in text:
            score += 6
    for bad in ["frontend", "mobile", "manual qa", "sales"]:
        if bad in text:
            score -= 10
    return _clamp(score)


def _score_opportunity_quality(job: Any, requirements: JobRequirements) -> int:
    data = _job_to_dict(job)
    score = 45
    if data.get("source") in {"greenhouse", "lever", "ashby"}:
        score += 15
    elif data.get("source") == "linkedin_scraper":
        score += 6
    if data.get("company"):
        score += 8
    if data.get("location"):
        score += 7
    if data.get("workplace_type") or requirements.location_constraints:
        score += 5
    if requirements.compensation or data.get("salary_min") or data.get("salary_max"):
        score += 8
    if requirements.tech_stack:
        score += 7
    if requirements.responsibilities:
        score += 5
    parse_confidence = data.get("parse_confidence")
    if parse_confidence is not None:
        confidence = float(parse_confidence)
        if confidence >= 0.8:
            score += 4
        elif confidence < 0.5:
            score -= 12
    return _clamp(score)


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


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))
