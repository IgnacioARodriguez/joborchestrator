from __future__ import annotations

import json
from typing import Any

from joborchestrator.intelligence.ats_autofill import build_autofill_plan
from joborchestrator.intelligence.cover_letter_generator import build_professional_cover_letter

CANDIDATE_PROFILE_SUMMARY = """\
PERFIL DEL CANDIDATO:
- 4+ años como backend/full stack developer con Python, Django, FastAPI, Flask,
  PostgreSQL, MongoDB, Redis, Docker, AWS, React, TypeScript y Three.js.
- Experiencia client-facing en cuentas grandes vía consultoras.
- Base en Málaga, España; abierto a remoto en España/UE.
- Inglés y español.
"""


def build_recruiter_message(job: dict[str, Any], keywords: list[str] | None = None) -> str:
    title = job.get("title") or "the role"
    company = job.get("company") or "your team"
    keyword_text = ", ".join((keywords or [])[:4]) or "backend systems, APIs and product delivery"
    return (
        f"Hi, I saw the {title} opportunity at {company} and it looks closely aligned with my background. "
        f"I have hands-on experience around {keyword_text}, and I would be happy to share how I could contribute "
        f"to the team. Thanks for considering my profile."
    )


def build_ats_cv_text(job: dict[str, Any], keywords: list[str] | None = None) -> str:
    title = job.get("title") or "Target role"
    company = job.get("company") or "Target company"
    keyword_text = ", ".join((keywords or [])[:10]) or "Python, backend engineering, APIs, cloud, delivery ownership"
    angle = job.get("recommended_application_angle") or (
        "Position as a pragmatic software engineer focused on backend systems, integrations and product impact."
    )
    return (
        f"ATS CV targeting notes for {title} at {company}\n\n"
        f"Headline: Software Engineer focused on backend systems, APIs, integrations and product delivery.\n\n"
        f"Keywords to naturally include: {keyword_text}.\n\n"
        f"Positioning angle: {angle}\n\n"
        "Experience bullets to adapt:\n"
        "- Built and maintained backend services and API integrations with attention to reliability and maintainability.\n"
        "- Collaborated with product and business stakeholders to translate requirements into shipped software.\n"
        "- Improved delivery quality through pragmatic engineering practices, documentation and ownership.\n\n"
        "Do not add skills or tools that are not true in your experience."
    )


def build_application_kit(job: dict[str, Any], keywords: list[str] | None = None) -> dict[str, str]:
    enriched_job = {
        **job,
        "description": job.get("description_text") or job.get("description") or "",
    }
    autofill = build_autofill_plan(enriched_job, ats_type=str(job.get("source") or "portal"))
    return {
        "recruiter_message": build_recruiter_message(job, keywords),
        "cover_letter": build_professional_cover_letter(enriched_job, CANDIDATE_PROFILE_SUMMARY),
        "ats_cv_text": build_ats_cv_text(job, keywords),
        "autofill_notes": json.dumps(autofill, ensure_ascii=False, indent=2),
    }
