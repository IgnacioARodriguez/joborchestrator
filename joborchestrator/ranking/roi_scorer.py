from __future__ import annotations

from typing import Any, Literal

from joborchestrator.ranking.schemas import JobRequirements
from joborchestrator.scanning.normalization import normalize_text

Effort = Literal["LOW", "MEDIUM", "HIGH"]


def estimate_application_effort(job: Any) -> Effort:
    data = job if isinstance(job, dict) else getattr(job, "__dict__", {})
    url = normalize_text(data.get("apply_url") or data.get("url") or "")
    description = normalize_text(data.get("description_text") or data.get("description") or "")

    if any(x in url for x in ["workday", "myworkdayjobs"]) or any(
        x in description for x in ["case study", "portfolio required", "cover letter required", "long form"]
    ):
        return "HIGH"
    if any(x in url for x in ["greenhouse", "lever", "ashby"]):
        return "LOW"
    if any(x in description for x in ["cover letter", "portfolio", "assessment"]):
        return "MEDIUM"
    return "MEDIUM"


def score_application_roi(
    job: Any,
    requirements: JobRequirements,
    technical_fit: int,
    role_fit: int,
    seniority_fit: int,
    risk_penalty: int,
) -> int:
    effort = estimate_application_effort(job)
    score = 55
    score += int((technical_fit - 50) * 0.25)
    score += int((role_fit - 50) * 0.2)
    score += int((seniority_fit - 50) * 0.15)
    if effort == "LOW":
        score += 15
    elif effort == "HIGH":
        score -= 18
    if requirements.dealbreakers:
        score -= 25
    score -= int(risk_penalty * 0.6)
    return max(0, min(100, score))
