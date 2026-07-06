from __future__ import annotations

from typing import Any

from joborchestrator.ranking.schemas import JobRequirements
from joborchestrator.scanning.normalization import normalize_text


def classify_role(job: Any, requirements: JobRequirements) -> dict:
    data = job if isinstance(job, dict) else getattr(job, "__dict__", {})
    title_text = normalize_text(data.get("title") or data.get("titulo"))
    body_text = normalize_text(data.get("description_text") or data.get("description") or data.get("descripcion"))
    signal_text = normalize_text(" ".join(requirements.role_signals + requirements.tech_stack))
    text = normalize_text(" ".join(x for x in [title_text, body_text, signal_text] if x))

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

    _score_if(scores, title_text, ["python"], "Python Developer", 34)
    _score_if(scores, title_text, ["python"], "Backend Engineer", 18)
    if "python" in body_text or "python" in signal_text:
        scores["Python Developer"] += 30
        scores["Backend Engineer"] += 15

    _score_if(scores, title_text, ["backend", "api", "fastapi", "django", "flask", "rest"], "Backend Engineer", 44)
    _score_if(scores, body_text + " " + signal_text, ["backend", "api", "fastapi", "django", "flask", "rest"], "Backend Engineer", 28)

    if any(x in title_text for x in ["react", "typescript", "frontend", "vue", "angular"]):
        scores["Frontend Engineer"] += 36
        if any(x in text for x in ["python", "django", "fastapi", "backend"]):
            scores["Full Stack Engineer"] += 38
    elif any(x in body_text or x in signal_text for x in ["react", "typescript", "frontend", "vue", "angular"]):
        scores["Frontend Engineer"] += 25
        if any(x in text for x in ["python", "django", "fastapi", "backend"]):
            scores["Full Stack Engineer"] += 35

    _score_if(scores, title_text, ["data engineer", "etl", "pipeline", "airflow", "warehouse"], "Data Engineer", 44)
    _score_if(scores, body_text + " " + signal_text, ["data engineer", "etl", "pipeline", "airflow", "warehouse"], "Data Engineer", 28)
    _score_if(scores, title_text, ["llm", "machine learning", "ml engineer", "ai engineer", "rag"], "ML/AI Engineer", 44)
    _score_if(scores, body_text + " " + signal_text, ["llm", "machine learning", "ml engineer", "ai engineer", "rag"], "ML/AI Engineer", 28)
    _score_if(scores, title_text, ["devops", "platform", "terraform", "kubernetes", "sre"], "DevOps/Platform Engineer", 44)
    _score_if(scores, body_text + " " + signal_text, ["devops", "platform", "terraform", "kubernetes", "sre"], "DevOps/Platform Engineer", 28)
    _score_if(scores, title_text, ["qa", "test automation"], "QA/Automation Engineer", 44)
    _score_if(scores, body_text + " " + signal_text, ["qa", "test automation"], "QA/Automation Engineer", 28)
    _score_if(scores, title_text, ["solutions engineer", "solution engineer", "customer integration", "technical consulting", "implementation"], "Solutions Engineer", 50)
    _score_if(scores, body_text + " " + signal_text, ["solutions engineer", "solution engineer", "customer integration", "technical consulting", "implementation"], "Solutions Engineer", 28)
    _score_if(scores, title_text, ["technical consultant", "consultant"], "Technical Consultant", 46)
    _score_if(scores, body_text + " " + signal_text, ["technical consultant", "consultant"], "Technical Consultant", 24)
    _score_if(scores, title_text, ["product manager"], "Product Manager", 52)
    _score_if(scores, body_text, ["product manager"], "Product Manager", 10)
    _score_if(scores, title_text, ["sales", "account executive", "presales", "pre sales"], "Sales/Pre-sales", 44)
    _score_if(scores, body_text + " " + signal_text, ["sales", "account executive", "presales", "pre sales"], "Sales/Pre-sales", 24)

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


def _score_if(scores: dict[str, int], text: str, needles: list[str], role: str, points: int) -> None:
    if any(needle in text for needle in needles):
        scores[role] += points
