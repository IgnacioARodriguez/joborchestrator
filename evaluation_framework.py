from __future__ import annotations

from typing import Dict, Any


def build_af_evaluation(job: Dict[str, Any], profile: str) -> Dict[str, Any]:
    """Build a simple A-F scorecard with a legitimacy block for a job opportunity."""
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    company = (job.get("company") or "").lower()

    score = 0
    if "python" in description or "python" in title:
        score += 15
    if "backend" in description or "backend" in title:
        score += 15
    if len(description) > 120:
        score += 10
    if company and company not in {"unknown", ""}:
        score += 10
    if profile and len(profile) > 20:
        score += 10

    legitimacy = 70
    if any(token in description for token in ["whatsapp", "bitcoin", "easy money", "guaranteed income"]):
        legitimacy = 10
    elif any(token in description for token in ["remote", "team", "salary", "benefits"]):
        legitimacy += 10

    blocks = {
        "A": "Fit técnico",
        "B": "Impacto del rol",
        "C": "Experiencia del equipo",
        "D": "Compensación y contexto",
        "E": "Posicionamiento para entrevista",
        "F": "Siguiente paso",
        "legitimidad": "Legitimidad y señales de riesgo",
    }

    if legitimacy >= 70:
        decision = "go"
    elif legitimacy >= 40:
        decision = "review"
    else:
        decision = "skip"

    return {
        "job": job,
        "profile": profile,
        "blocks": blocks,
        "overall_score": min(score, 100),
        "legitimacy_score": legitimacy,
        "decision": decision,
        "summary": "Evaluación A-F estructurada para priorizar la oportunidad.",
    }
