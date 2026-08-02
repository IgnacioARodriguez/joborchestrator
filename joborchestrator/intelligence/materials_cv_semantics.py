from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict

from joborchestrator.intelligence.materials_cv_ir import (
    CandidateCvIR,
    ExperienceRole,
    parse_candidate_cv_ir,
)
from joborchestrator.intelligence.materials_cv_policy import (
    required_bullets_for_role,
    technology_difference,
)


def candidate_ir_snapshot(cv_ir: CandidateCvIR) -> dict:
    return {
        "candidate": asdict(cv_ir.candidate),
        "skills": [asdict(skill) for skill in cv_ir.skills],
        "roles": [asdict(role) for role in cv_ir.roles],
        "education": [asdict(entry) for entry in cv_ir.education],
        "parse_warnings": list(cv_ir.parse_warnings),
        "human_review_required": bool(cv_ir.human_review_required),
    }


def validate_rendered_cv_against_ir(
    source_ir: CandidateCvIR,
    ats_cv_text: str,
) -> list[str]:
    supported_terms = _source_terms(source_ir)
    generated_ir = parse_candidate_cv_ir(
        ats_cv_text,
        supported_terms,
        canonical_skills=[skill.name for skill in source_ir.skills],
    )
    problems: list[str] = []

    if generated_ir.human_review_required or not generated_ir.roles:
        return [
            "ats_cv_text semantic round-trip could not parse generated experience roles. "
            "Use the canonical inline role header format and preserve source role structure."
        ]

    if len(generated_ir.roles) != len(source_ir.roles):
        problems.append(
            "ats_cv_text omitted base CV experience entries: "
            f"expected {len(source_ir.roles)} roles, parsed {len(generated_ir.roles)}"
        )

    compressed: list[str] = []
    for role_index, source_role in enumerate(source_ir.roles):
        generated_role = _matching_role(source_role, generated_ir.roles, role_index)
        if generated_role is None:
            problems.append(
                f"ats_cv_text omitted base CV experience entries: {source_role.title} at {source_role.company}"
            )
            continue

        if _normalize(source_role.title) != _normalize(generated_role.title):
            problems.append(
                f"ats_cv_text changed source role title for {source_role.company}: "
                f"{source_role.title!r} -> {generated_role.title!r}"
            )
        if _normalize(source_role.dates) != _normalize(generated_role.dates):
            problems.append(
                f"ats_cv_text changed source role dates for {source_role.company}: "
                f"{source_role.dates!r} -> {generated_role.dates!r}"
            )

        required = required_bullets_for_role(role_index, len(source_role.bullets))
        if len(generated_role.bullets) < required:
            compressed.append(
                f"{source_role.company} kept {len(generated_role.bullets)}/{len(source_role.bullets)} "
                f"bullets; expected at least {required}"
            )

        unsupported = technology_difference(
            generated_role.canonical_technologies,
            source_role.canonical_technologies,
        )
        missing = technology_difference(
            source_role.canonical_technologies,
            generated_role.canonical_technologies,
        )
        if unsupported:
            problems.append(
                f"{source_role.company} has unsupported role-specific technologies: "
                f"{', '.join(unsupported[:6])}. Remove those technologies from that employer block."
            )
        if missing:
            problems.append(
                f"{source_role.company} is missing canonical role technologies: "
                f"{', '.join(missing[:6])}. Restore the source-backed Technologies line."
            )

    if compressed:
        problems.append(
            "ats_cv_text is overcompressed for base CV experience roles: "
            + "; ".join(compressed[:4])
            + ". Preserve proportionally more truthful bullets for recent or substantial roles."
        )

    if source_ir.skills and not generated_ir.skills:
        problems.append("ats_cv_text is missing standard ATS sections: skills")
    if source_ir.education and not generated_ir.education:
        problems.append("ats_cv_text is missing standard ATS sections: education")

    return _dedupe(problems)


def _matching_role(
    source_role: ExperienceRole,
    generated_roles: list[ExperienceRole],
    fallback_index: int,
) -> ExperienceRole | None:
    source_company = _normalize(source_role.company)
    for generated in generated_roles:
        if _normalize(generated.company) == source_company:
            return generated
    if fallback_index < len(generated_roles):
        return generated_roles[fallback_index]
    return None


def _source_terms(cv_ir: CandidateCvIR) -> list[str]:
    values = [skill.name for skill in cv_ir.skills]
    values.extend(
        technology
        for role in cv_ir.roles
        for technology in role.canonical_technologies
    )
    return _dedupe(values)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", ascii_text.casefold())).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
