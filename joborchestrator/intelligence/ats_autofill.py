from __future__ import annotations

from typing import Any


def build_ats_form_responses(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    ats_type: str = "greenhouse",
) -> dict[str, Any]:
    """Generate conservative answers for common ATS application questions."""
    title = job.get("title") or "the role"
    company = job.get("company") or "the company"
    description = job.get("description") or ""
    profile_summary = _profile_summary(profile)

    return {
        "ats_type": ats_type.lower(),
        "responses": [
            {
                "field": "why_work_here",
                "question": f"Why do you want to work at {company}?",
                "answer": f"I am interested in {company} because this role appears aligned with {profile_summary}.",
            },
            {
                "field": "tell_us_about_yourself",
                "question": "Tell us about yourself",
                "answer": f"My profile is focused on {profile_summary}, and I am interested in roles where that experience can create practical impact.",
            },
            {
                "field": "relevant_experience",
                "question": "What experience is most relevant to this role?",
                "answer": _relevant_experience_answer(description, profile),
            },
            {
                "field": "motivation",
                "question": "What motivates you in this role?",
                "answer": "I am motivated by work where I can apply my documented strengths, learn quickly, and contribute reliably to the team.",
            },
        ],
    }


def build_autofill_plan(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    ats_type: str = "greenhouse",
) -> dict[str, Any]:
    """Build a lightweight autofill plan for supported ATS providers."""
    title = job.get("title") or "Role"
    company = job.get("company") or "the company"
    profile_summary = _profile_summary(profile)

    questions = [
        {
            "field": "why_join",
            "question": f"Why are you interested in {title} at {company}?",
            "answer": f"This role appears aligned with {profile_summary}, and I would tailor my application around evidence-backed fit.",
        },
        {
            "field": "experience",
            "question": "What experience is most relevant to this position?",
            "answer": _relevant_experience_answer(str(job.get("description") or ""), profile),
        },
    ]

    if _has_leadership_profile(profile):
        questions.append(
            {
                "field": "leadership",
                "question": "How have you led others or influenced delivery?",
                "answer": "My profile includes leadership or mentoring signals; I would answer with a concrete example from my real experience.",
            }
        )

    responses = build_ats_form_responses(job, profile=profile, ats_type=ats_type)

    return {
        "ats_type": ats_type.lower(),
        "company": company,
        "title": title,
        "questions": questions,
        "field_mappings": {
            "resume": "Upload latest resume",
            "cover_letter": "Paste tailored cover letter",
            "linkedin": "Paste LinkedIn profile URL",
        },
        "form_responses": responses["responses"],
        "copy_paste_block": "\n".join(f"{q['field']}: {q['answer']}" for q in questions),
    }


def _profile_summary(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "the experience documented in my candidate profile"
    headline = str(profile.get("headline") or "").strip()
    skills = [
        str(skill.get("name") or "").strip()
        for skill in profile.get("skills") or []
        if isinstance(skill, dict) and str(skill.get("name") or "").strip()
    ]
    if headline and skills:
        return f"{headline}, especially {', '.join(skills[:4])}"
    if headline:
        return headline
    if skills:
        return ", ".join(skills[:4])
    return "the experience documented in my candidate profile"


def _relevant_experience_answer(description: str, profile: dict[str, Any] | None) -> str:
    summary = _profile_summary(profile)
    if description:
        return f"I would connect this role's requirements to {summary}, using only examples I can support from my real experience."
    return f"I would highlight concrete examples from {summary}, without adding unsupported claims."


def _has_leadership_profile(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False
    text = " ".join(
        [
            str(profile.get("headline") or ""),
            str(profile.get("notes") or ""),
            " ".join(str(skill.get("name") or "") for skill in profile.get("skills") or [] if isinstance(skill, dict)),
        ]
    ).lower()
    return any(term in text for term in ["lead", "leader", "leadership", "mentor", "mentoring", "manager"])
