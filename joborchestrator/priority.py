from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class PriorityBreakdown:
    priority_score: int
    fit_score: int
    eligibility_score: int
    freshness_score: int
    freshness_bucket: str
    freshness_age_days: int | None
    application_effort_score: int
    recruiter_advantage_score: int
    data_quality_score: int
    competition_signal: int
    risk_penalty: int
    estimated_minutes: int
    next_action: str
    blocker: str | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_priority(job: dict[str, Any], ranking: dict[str, Any] | None = None, now: datetime | None = None) -> PriorityBreakdown:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    ranking = ranking or {}
    fit_score = _clamp_int(ranking.get("final_score") or 0)
    eligibility_score = _eligibility_score(job, ranking)
    freshness_score = _freshness_score(job, now)
    freshness_bucket, freshness_age_days = _freshness_bucket(job, now)
    effort = _effort_score(job)
    recruiter = _recruiter_advantage_score(job)
    quality = _data_quality_score(job)
    competition = _competition_signal(job)
    risk = _risk_penalty(job, ranking)
    staleness = _staleness_penalty(freshness_bucket)
    estimated_minutes = _estimated_minutes(job, effort)
    priority = round(
        fit_score * 0.34
        + eligibility_score * 0.12
        + freshness_score * 0.14
        + effort * 0.14
        + recruiter * 0.10
        + quality * 0.10
        + competition * 0.06
        - risk * 0.20
        - staleness
    )
    priority = _clamp_int(priority)
    blocker = _blocker(job, quality, risk)
    next_action = _next_action(job, priority, blocker)
    explanation = (
        f"priority={priority}: fit {fit_score}, freshness {freshness_score}, "
        f"effort {effort}, recruiter {recruiter}, data {quality}, risk -{risk}."
    )
    return PriorityBreakdown(
        priority_score=priority,
        fit_score=fit_score,
        eligibility_score=eligibility_score,
        freshness_score=freshness_score,
        freshness_bucket=freshness_bucket,
        freshness_age_days=freshness_age_days,
        application_effort_score=effort,
        recruiter_advantage_score=recruiter,
        data_quality_score=quality,
        competition_signal=competition,
        risk_penalty=risk,
        estimated_minutes=estimated_minutes,
        next_action=next_action,
        blocker=blocker,
        explanation=explanation,
    )


def _freshness_score(job: dict[str, Any], now: datetime) -> int:
    raw = job.get("posted_at") or job.get("first_seen_at") or job.get("last_seen_at")
    seen = _parse_dt(raw)
    if not seen:
        return 35
    age_hours = max(0, (now - seen).total_seconds() / 3600)
    if age_hours <= 24:
        return 100
    if age_hours <= 72:
        return 85
    if age_hours <= 24 * 7:
        return 68
    if age_hours <= 24 * 21:
        return 42
    return 18


def _freshness_bucket(job: dict[str, Any], now: datetime) -> tuple[str, int | None]:
    raw = job.get("posted_at") or job.get("first_seen_at") or job.get("last_seen_at")
    seen = _parse_dt(raw)
    if not seen:
        return "archival", None
    age_days = max(0, int((now - seen).total_seconds() // 86400))
    if age_days <= 3:
        return "fresh", age_days
    if age_days <= 7:
        return "recent", age_days
    if age_days <= 21:
        return "stale", age_days
    return "archival", age_days


def _staleness_penalty(bucket: str) -> int:
    if bucket == "stale":
        return 14
    if bucket == "archival":
        return 26
    return 0


def _recruiter_advantage_score(job: dict[str, Any]) -> int:
    contacts = job.get("hiring_contacts") or []
    if contacts:
        return 100
    if job.get("recruiter_profile_url"):
        return 90
    if job.get("recruiter_name"):
        return 70
    if str(job.get("source") or "").lower() == "linkedin_scraper":
        return 35
    return 20


def _effort_score(job: dict[str, Any]) -> int:
    source = str(job.get("source") or "").lower()
    apply_type = str(job.get("apply_type") or "").lower()
    url = str(job.get("apply_url") or job.get("external_apply_url") or job.get("url") or "").lower()
    score = 62
    if "greenhouse" in source or "greenhouse.io" in url:
        score += 22
    if "lever" in source or "lever.co" in url:
        score += 14
    if apply_type == "easy_apply":
        score += 18
    if apply_type == "external":
        score -= 8
    if not job.get("ats_cv_text"):
        score -= 8
    if not job.get("cover_letter"):
        score += 4
    return _clamp_int(score)


def _data_quality_score(job: dict[str, Any]) -> int:
    required = ["title", "company", "url"]
    optional = ["description_text", "apply_url", "location"]
    score = 100
    for key in required:
        if not str(job.get(key) or "").strip():
            score -= 25
    for key in optional:
        if not str(job.get(key) or "").strip():
            score -= 10
    flags = job.get("data_quality_flags")
    if flags and str(flags) not in {"[]", ""}:
        score -= 12
    return _clamp_int(score)


def _competition_signal(job: dict[str, Any]) -> int:
    count = job.get("applicant_count")
    try:
        applicants = int(count)
    except (TypeError, ValueError):
        return 55
    if applicants <= 25:
        return 95
    if applicants <= 100:
        return 72
    if applicants <= 250:
        return 45
    return 20


def _eligibility_score(job: dict[str, Any], ranking: dict[str, Any]) -> int:
    evidence = ranking.get("evidence") or ranking.get("evidence_json") or {}
    if isinstance(evidence, str):
        evidence = {}
    dealbreakers = evidence.get("dealbreakers") or []
    if dealbreakers:
        return 20
    return 82 if job.get("is_active", 1) else 0


def _risk_penalty(job: dict[str, Any], ranking: dict[str, Any]) -> int:
    risk = 0
    evidence = ranking.get("evidence") or {}
    if isinstance(evidence, dict) and evidence.get("red_flags"):
        risk += 25
    if _data_quality_score(job) < 55:
        risk += 20
    if str(job.get("pipeline_status") or "") == "discarded":
        risk += 80
    return _clamp_int(risk)


def _estimated_minutes(job: dict[str, Any], effort_score: int) -> int:
    if effort_score >= 85:
        return 4
    if effort_score >= 70:
        return 7
    if effort_score >= 50:
        return 12
    return 18


def _blocker(job: dict[str, Any], quality: int, risk: int) -> str | None:
    if quality < 60:
        return "Missing job data"
    if risk >= 60:
        return "High application risk"
    return None


def _next_action(job: dict[str, Any], priority: int, blocker: str | None) -> str:
    if blocker:
        return "Needs input"
    status = str(job.get("pipeline_status") or "new")
    if status == "ready_to_apply":
        return "Review"
    if status == "shortlisted":
        return "Apply now"
    if priority >= 70:
        return "Prepare"
    if priority < 35:
        return "Skip"
    return "Review"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _clamp_int(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))
