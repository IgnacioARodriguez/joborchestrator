from __future__ import annotations

import json
from typing import Any

from joborchestrator.intelligence.ats_autofill import build_autofill_plan
from joborchestrator.intelligence.cover_letter_generator import build_professional_cover_letter
from joborchestrator.storage import persistence as db


class ApplicationMaterialsError(RuntimeError):
    pass


def build_recruiter_message(
    job: dict[str, Any],
    profile: dict[str, Any],
    keywords: list[str] | None = None,
) -> str:
    title = job.get("title") or "the role"
    company = job.get("company") or "your team"
    headline = str(profile.get("headline") or "my background").strip()
    keyword_text = ", ".join(_truthful_keywords(profile, keywords, limit=4)) or "relevant experience"
    return (
        f"Hi, I saw the {title} opportunity at {company} and it looks closely aligned with my background. "
        f"My profile focuses on {headline}, with experience around {keyword_text}. "
        "I would be happy to share how I could contribute to the team. Thanks for considering my profile."
    )


def build_ats_cv_text(
    job: dict[str, Any],
    profile: dict[str, Any],
    keywords: list[str] | None = None,
) -> str:
    title = job.get("title") or "Target role"
    company = job.get("company") or "Target company"
    headline = str(profile.get("headline") or "Candidate profile").strip()
    keyword_text = ", ".join(_truthful_keywords(profile, keywords, limit=10)) or "profile-backed skills"
    angle = job.get("recommended_application_angle") or f"Position around {headline}."
    base_cv = str(profile.get("base_cv_text") or "").strip()
    if base_cv:
        return (
            f"{base_cv}\n\n"
            "ATS KEYWORDS\n"
            f"{keyword_text}\n\n"
            "TARGETED POSITIONING\n"
            f"{angle}\n\n"
            f"Target role: {title} at {company}"
        )
    return (
        f"ATS optimized CV draft for {title} at {company}\n\n"
        f"Headline: {headline}\n\n"
        f"Profile-backed keywords to naturally include: {keyword_text}.\n\n"
        f"Positioning angle: {angle}\n\n"
        "Experience bullets to adapt from the user's real profile:\n"
        f"{_profile_bullets(profile)}\n\n"
        "Do not add skills or tools that are not true in your experience."
    )


def build_application_kit(job: dict[str, Any], keywords: list[str] | None = None) -> dict[str, str]:
    profile = db.get_candidate_profile_payload()
    if not profile:
        raise ApplicationMaterialsError("No candidate profile configured. Upload a CV in Profile before generating materials.")

    enriched_job = {
        **job,
        "description": job.get("description_text") or job.get("description") or "",
    }
    autofill = build_autofill_plan(enriched_job, profile=profile, ats_type=str(job.get("source") or "portal"))
    return {
        "recruiter_message": build_recruiter_message(job, profile, keywords),
        "cover_letter": build_professional_cover_letter(enriched_job, profile),
        "ats_cv_text": build_ats_cv_text(job, profile, keywords),
        "autofill_notes": json.dumps(autofill, ensure_ascii=False, indent=2),
    }


def _truthful_keywords(profile: dict[str, Any], keywords: list[str] | None, limit: int) -> list[str]:
    profile_skills = [
        str(skill.get("name") or "").strip()
        for skill in profile.get("skills") or []
        if isinstance(skill, dict) and str(skill.get("name") or "").strip()
    ]
    profile_skill_keys = {skill.lower() for skill in profile_skills}
    safe = [str(keyword) for keyword in (keywords or []) if str(keyword).lower() in profile_skill_keys]
    for skill in profile_skills:
        if skill not in safe:
            safe.append(skill)
    return safe[:limit]


def _profile_bullets(profile: dict[str, Any]) -> str:
    headline = str(profile.get("headline") or "").strip()
    roles = [*profile.get("target_roles", []), *profile.get("secondary_roles", [])]
    skills = _truthful_keywords(profile, None, limit=6)
    bullets = []
    if headline:
        bullets.append(f"- {headline}.")
    if roles:
        bullets.append(f"- Target role alignment: {', '.join(str(role) for role in roles[:4])}.")
    if skills:
        bullets.append(f"- Relevant skills to evidence truthfully: {', '.join(skills)}.")
    return "\n".join(bullets or ["- Add concrete, truthful achievements from the user's profile."])
