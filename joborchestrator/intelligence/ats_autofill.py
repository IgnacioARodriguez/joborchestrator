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

    responses = [
        {
            "field": "why_work_here",
            "question": f"Why do you want to work at {company}?",
            "answer": f"I am interested in {company} because this role appears aligned with {profile_summary}.",
            "confidence": "medium",
            "needs_review": True,
        },
        {
            "field": "tell_us_about_yourself",
            "question": "Tell us about yourself",
            "answer": f"My profile is focused on {profile_summary}, and I am interested in roles where that experience can create practical impact.",
            "confidence": "high" if profile else "medium",
            "needs_review": False,
        },
        {
            "field": "relevant_experience",
            "question": "What experience is most relevant to this role?",
            "answer": _relevant_experience_answer(description, profile),
            "confidence": "medium",
            "needs_review": True,
        },
        {
            "field": "motivation",
            "question": "What motivates you in this role?",
            "answer": "I am motivated by work where I can apply my documented strengths, learn quickly, and contribute reliably to the team.",
            "confidence": "medium",
            "needs_review": True,
        },
        {
            "field": "work_authorization",
            "question": "Are you legally authorized to work in this location?",
            "answer": "Review manually. Do not auto-fill unless your current work authorization for this location is confirmed.",
            "confidence": "low",
            "needs_review": True,
        },
        {
            "field": "salary_expectation",
            "question": "What are your salary expectations?",
            "answer": "Review manually based on role, location, seniority, and your current compensation target.",
            "confidence": "low",
            "needs_review": True,
        },
    ]
    return {
        "ats_type": ats_type.lower(),
        "responses": responses,
    }


def build_autofill_plan(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    ats_type: str = "greenhouse",
) -> dict[str, Any]:
    """Build a lightweight autofill plan for supported ATS providers."""
    title = job.get("title") or "Role"
    company = job.get("company") or "the company"
    apply_url = job.get("apply_url") or job.get("url") or ""
    profile_summary = _profile_summary(profile)
    ats_key = ats_type.lower()

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
    form_responses = responses["responses"]

    return {
        "automation_mode": "assisted_copy_paste",
        "ats_type": ats_key,
        "company": company,
        "title": title,
        "apply_url": apply_url,
        "preflight_checklist": _preflight_checklist(job),
        "browser_steps": _browser_steps(ats_key),
        "questions": questions,
        "field_mappings": _field_mappings(ats_key),
        "form_responses": form_responses,
        "copy_paste_block": "\n\n".join(
            f"{item['question']}\n{item['answer']}" for item in [*questions, *form_responses]
        ),
        "extension_payload": {
            "mode": "assist_only",
            "title": title,
            "company": company,
            "apply_url": apply_url,
            "ats_type": ats_key,
            "responses": form_responses,
            "field_mappings": _field_mappings(ats_key),
        },
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


def _preflight_checklist(job: dict[str, Any]) -> list[str]:
    title = job.get("title") or "role"
    company = job.get("company") or "company"
    return [
        f"Confirm the posting is still open for {title} at {company}.",
        "Open the application URL in a browser session where you are logged in.",
        "Generate or review the ATS CV text before uploading/pasting anything.",
        "Review low-confidence answers such as salary, visa, relocation, availability, and work authorization.",
        "Submit manually only after verifying every claim is true.",
    ]


def _browser_steps(ats_type: str) -> list[str]:
    common = [
        "Open the apply page.",
        "Upload or paste the tailored CV material.",
        "Paste prepared answers into matching form questions.",
        "Review required fields that contain legal, salary, location, or visa information.",
        "Submit manually after final review.",
    ]
    if ats_type in {"linkedin", "LinkedIn".lower()}:
        return [
            "Open the LinkedIn apply flow.",
            "Prefer Easy Apply only when the form is short and the generated answers match the fields.",
            *common[1:],
        ]
    if ats_type in {"greenhouse", "lever", "ashby"}:
        return common
    return common


def _field_mappings(ats_type: str) -> dict[str, dict[str, str]]:
    base = {
        "resume": {"semantic": "resume_upload", "action": "upload_latest_tailored_cv"},
        "cover_letter": {"semantic": "cover_letter_text", "action": "paste_cover_letter_when_available"},
        "linkedin": {"semantic": "linkedin_profile_url", "action": "paste_profile_url"},
        "email": {"semantic": "email", "action": "use_browser_or_profile_value"},
        "phone": {"semantic": "phone", "action": "use_browser_or_profile_value"},
    }
    if ats_type == "linkedin":
        base["resume"] = {"semantic": "linkedin_resume_selector", "action": "select_latest_tailored_cv"}
    return base
