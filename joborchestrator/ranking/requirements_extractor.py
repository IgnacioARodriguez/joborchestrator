from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from joborchestrator.ranking.schemas import JobRequirements
from joborchestrator.ranking.skill_taxonomy import find_skills
from joborchestrator.scanning.normalization import normalize_text

HARD_MARKERS = ["must have", "required", "requirements", "you have", "minimum qualifications", "qualifications"]
NICE_MARKERS = ["nice to have", "bonus points", "preferred", "plus", "desirable"]
RESP_MARKERS = ["responsibilities", "what you will do", "you will", "day to day", "role"]


def extract_requirements(job: Any) -> JobRequirements:
    data = _job_to_dict(job)
    title = _get(data, "title", "titulo")
    description = _get(data, "description_text", "description", "descripcion", "description_html") or ""
    location = _get(data, "location", "ubicacion") or ""
    workplace = _get(data, "workplace_type", "modalidad") or ""
    company = _get(data, "company", "empresa") or ""
    text = "\n".join(str(x) for x in [title, company, location, workplace, description] if x)
    norm = normalize_text(text)

    sections = _split_sections(description)
    tech_stack = find_skills(text)
    hard_requirements = _extract_section_items(sections, HARD_MARKERS) or tech_stack[:]
    nice_to_have = _extract_section_items(sections, NICE_MARKERS)
    responsibilities = _extract_section_items(sections, RESP_MARKERS)

    required_years = _extract_years(norm)
    seniority = _extract_seniority(norm)
    languages = _extract_languages(norm)
    location_constraints = _extract_location_constraints(norm, location, workplace)
    dealbreakers = _extract_dealbreakers(norm)
    compensation = _extract_compensation(text)
    role_signals = _extract_role_signals(norm, tech_stack)

    return JobRequirements(
        hard_requirements=_dedupe(hard_requirements),
        nice_to_have=_dedupe(nice_to_have),
        responsibilities=_dedupe(responsibilities),
        tech_stack=_dedupe(tech_stack),
        required_years=required_years,
        seniority_level=seniority,
        location_constraints=location_constraints,
        language_requirements=languages,
        dealbreakers=dealbreakers,
        compensation=compensation,
        role_signals=role_signals,
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


def _get(data: dict, *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _split_sections(description: str) -> list[str]:
    return [line.strip(" -*•\t") for line in str(description).splitlines() if line.strip()]


def _extract_section_items(lines: list[str], markers: list[str]) -> list[str]:
    items = []
    active = False
    for line in lines:
        norm = normalize_text(line)
        if any(marker in norm for marker in markers):
            active = True
            if len(line) > 20:
                items.extend(find_skills(line))
            continue
        if active:
            if any(marker in norm for marker in HARD_MARKERS + NICE_MARKERS + RESP_MARKERS if marker not in markers):
                active = False
                continue
            items.extend(find_skills(line) or ([line] if len(line.split()) <= 8 else []))
    return items


def _extract_years(norm: str) -> float | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:\+|\-\s*\d+)?\s*years?", norm)
    if not matches:
        return None
    return max(float(match) for match in matches)


def _extract_seniority(norm: str) -> str | None:
    if any(x in norm for x in ["principal", "staff", "architect"]):
        return "principal/staff"
    if "senior" in norm or "sr " in norm:
        return "senior"
    if any(x in norm for x in ["junior", "entry level", "intern", "graduate"]):
        return "junior"
    if any(x in norm for x in ["mid level", "midweight"]):
        return "mid"
    return None


def _extract_languages(norm: str) -> list[str]:
    languages = []
    if "english" in norm:
        languages.append("English")
    if "spanish" in norm or "español" in norm:
        languages.append("Spanish")
    return languages


def _extract_location_constraints(norm: str, location: str, workplace: str) -> list[str]:
    joined = normalize_text(f"{location} {workplace}") + " " + norm
    constraints = []
    for signal in ["remote", "hybrid", "onsite", "spain", "eu", "europe", "relocation", "visa sponsorship", "uk"]:
        if signal in joined:
            constraints.append(signal)
    return constraints


def _extract_dealbreakers(norm: str) -> list[str]:
    dealbreakers = []
    if "unpaid" in norm or "no salary" in norm:
        dealbreakers.append("unpaid")
    if "commission only" in norm or "commission-only" in norm:
        dealbreakers.append("commission only")
    if "relocation" in norm and not any(x in norm for x in ["remote", "spain", "eu", "europe"]):
        dealbreakers.append("mandatory relocation")
    return dealbreakers


def _extract_compensation(text: str) -> str | None:
    match = re.search(r"([$€£]\s?\d[\d,.kK]*(?:\s?-\s?[$€£]?\s?\d[\d,.kK]*)?)", text)
    return match.group(1) if match else None


def _extract_role_signals(norm: str, skills: list[str]) -> list[str]:
    signals = []
    for signal in ["backend", "frontend", "full stack", "data engineer", "machine learning", "devops", "platform", "qa", "solutions", "consultant", "sales", "product manager", "api", "cloud"]:
        if signal in norm:
            signals.append(signal)
    signals.extend(skills)
    return _dedupe(signals)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
