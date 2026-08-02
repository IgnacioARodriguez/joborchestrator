from __future__ import annotations

from typing import Any


def candidate_profile_status(stored_hash: Any, current_hash: Any) -> str:
    stored = str(stored_hash or "").strip()
    current = str(current_hash or "").strip()
    if not stored or not current:
        return "unknown"
    return "current" if stored == current else "stale"


def job_work_mode_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(value).strip().casefold()
        for value in (job.get("location"), job.get("workplace_type"))
        if str(value or "").strip()
    )


def is_remote_job(job: dict[str, Any]) -> bool:
    text = job_work_mode_text(job)
    return any(marker in text for marker in ("remote", "remoto", "remota"))
