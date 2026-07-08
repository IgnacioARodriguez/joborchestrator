from __future__ import annotations

from typing import Any

from joborchestrator.ranking.role_catalog import classify_profile_role
from joborchestrator.ranking.schemas import CandidateProfile, JobRequirements
from joborchestrator.scanning.normalization import normalize_text


def classify_role(job: Any, requirements: JobRequirements, profile: CandidateProfile) -> dict:
    data = job if isinstance(job, dict) else getattr(job, "__dict__", {})
    text = normalize_text(
        " ".join(
            str(value or "")
            for value in [
                data.get("title") or data.get("titulo"),
                data.get("description_text") or data.get("description") or data.get("descripcion"),
                " ".join(requirements.role_signals + requirements.tech_stack),
            ]
        )
    )
    return classify_profile_role(text, profile)
