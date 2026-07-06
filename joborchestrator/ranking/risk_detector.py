from __future__ import annotations

from typing import Any
from dataclasses import asdict, is_dataclass

from joborchestrator.ranking.schemas import CandidateProfile, JobRequirements
from joborchestrator.scanning.normalization import normalize_text


def detect_risks(job: Any, requirements: JobRequirements, profile: CandidateProfile) -> tuple[list[str], int]:
    data = _job_to_dict(job)
    title = data.get("title") or data.get("titulo") or ""
    company = data.get("company") or data.get("empresa") or ""
    description = data.get("description_text") or data.get("description") or data.get("descripcion") or ""
    location = data.get("location") or data.get("ubicacion") or ""
    text = normalize_text(f"{title} {company} {description} {location}")
    flags: list[str] = []
    penalty = 0

    if len(description) < 180:
        flags.append("Description is too generic or short")
        penalty += 8
    if not company or normalize_text(company) in {"unknown", "confidential"}:
        flags.append("Company is unclear")
        penalty += 7
    if not requirements.compensation:
        flags.append("No salary range")
        penalty += 3
    if "commission only" in text:
        flags.append("Commission-only compensation")
        penalty += 35
    if "unpaid" in text:
        flags.append("Unpaid role")
        penalty += 40
    if "relocation" in text and not any(x in text for x in ["remote", "spain", "eu", "europe"]):
        flags.append("Mandatory relocation outside preferred area")
        penalty += 30
    if "visa sponsorship" in text and "not" in text:
        flags.append("Visa constraint")
        penalty += 12
    if "remote" in text and "onsite" in text:
        flags.append("Contradictory work mode")
        penalty += 8
    if any(x in text for x in ["rockstar", "ninja", "work hard play hard"]):
        flags.append("Cultural red flag wording")
        penalty += 8
    if len(requirements.tech_stack) >= 12:
        flags.append("Too many disconnected technologies")
        penalty += 8
    if requirements.required_years and requirements.required_years >= 8:
        flags.append("Inflated seniority requirement")
        penalty += 18
    if not requirements.responsibilities and len(description) > 0:
        flags.append("No clear responsibilities")
        penalty += 6
    if not requirements.tech_stack and any(x in text for x in ["engineer", "developer", "technical"]):
        flags.append("No clear technical stack")
        penalty += 7
    parse_confidence = data.get("parse_confidence")
    if parse_confidence is not None and float(parse_confidence) < 0.5:
        flags.append("Low extraction confidence")
        penalty += 10

    flags.extend(requirements.dealbreakers)
    if requirements.dealbreakers:
        penalty += 25

    return _dedupe(flags), min(40, penalty)


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
