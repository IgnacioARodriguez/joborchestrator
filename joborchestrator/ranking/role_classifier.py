from __future__ import annotations

from typing import Any

from joborchestrator.ranking.schemas import JobRequirements
from joborchestrator.scanning.normalization import normalize_text


def classify_role(job: Any, requirements: JobRequirements) -> dict:
    data = job if isinstance(job, dict) else getattr(job, "__dict__", {})
    text = normalize_text(
        " ".join(
            str(x)
            for x in [
                data.get("title") or data.get("titulo"),
                data.get("description_text") or data.get("description") or data.get("descripcion"),
                " ".join(requirements.role_signals),
                " ".join(requirements.tech_stack),
            ]
            if x
        )
    )

    scores = {
        "Backend Engineer": 0,
        "Python Developer": 0,
        "Full Stack Engineer": 0,
        "Frontend Engineer": 0,
        "Data Engineer": 0,
        "ML/AI Engineer": 0,
        "DevOps/Platform Engineer": 0,
        "QA/Automation Engineer": 0,
        "Solutions Engineer": 0,
        "Technical Consultant": 0,
        "Product Manager": 0,
        "Sales/Pre-sales": 0,
        "Other": 1,
    }

    if "python" in text:
        scores["Python Developer"] += 30
        scores["Backend Engineer"] += 15
    if any(x in text for x in ["backend", "api", "fastapi", "django", "flask", "rest"]):
        scores["Backend Engineer"] += 35
    if any(x in text for x in ["react", "typescript", "frontend", "vue", "angular"]):
        scores["Frontend Engineer"] += 25
        if any(x in text for x in ["python", "django", "fastapi", "backend"]):
            scores["Full Stack Engineer"] += 35
    if any(x in text for x in ["data engineer", "etl", "pipeline", "airflow", "warehouse"]):
        scores["Data Engineer"] += 35
    if any(x in text for x in ["llm", "machine learning", "ml engineer", "ai engineer", "rag"]):
        scores["ML/AI Engineer"] += 35
    if any(x in text for x in ["devops", "platform", "terraform", "kubernetes", "sre"]):
        scores["DevOps/Platform Engineer"] += 35
    if "qa" in text or "test automation" in text:
        scores["QA/Automation Engineer"] += 35
    if any(x in text for x in ["solutions engineer", "solution engineer", "customer integration", "technical consulting", "implementation"]):
        scores["Solutions Engineer"] += 40
    if "technical consultant" in text or "consultant" in text:
        scores["Technical Consultant"] += 35
    if "product manager" in text:
        scores["Product Manager"] += 40
    if any(x in text for x in ["sales", "account executive", "presales", "pre sales"]):
        scores["Sales/Pre-sales"] += 30

    primary = max(scores, key=scores.get)
    sorted_roles = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    confidence = min(0.95, max(0.35, sorted_roles[0][1] / 70))
    secondary = [role for role, score in sorted_roles[1:4] if score >= 25]

    return {
        "primary_role": primary,
        "secondary_roles": secondary,
        "confidence": round(confidence, 2),
        "reason": f"Detected signals for {primary}: {', '.join(requirements.role_signals[:6]) or 'title/description only'}",
    }
