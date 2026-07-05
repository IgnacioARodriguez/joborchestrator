from __future__ import annotations

from typing import Any

from joborchestrator.ranking.schemas import CandidateProfile, JobRequirements
from joborchestrator.scanning.normalization import normalize_text


def detect_risks(job: Any, requirements: JobRequirements, profile: CandidateProfile) -> tuple[list[str], int]:
    data = job if isinstance(job, dict) else getattr(job, "__dict__", {})
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

    flags.extend(requirements.dealbreakers)
    if requirements.dealbreakers:
        penalty += 25

    return _dedupe(flags), min(40, penalty)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
