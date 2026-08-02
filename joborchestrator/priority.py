from __future__ import annotations

import json
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
    blocker = _blocker(job, ranking, quality, risk)
    next_action = _next_action(job, ranking, priority, blocker)
    decision = str(ranking.get("decision") or "unranked")
    explanation = (
        f"priority={priority}: decision {decision}, fit {fit_score}, freshness {freshness_score}, "
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
    seen = _freshness_reference(job)
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
    seen = _freshness_reference(job)
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


def _freshness_reference(job: dict[str, Any]) -> datetime | None:
    candidates = [
        parsed
        for parsed in (
            _parse_dt(job.get("posted_at")),
            _parse_dt(job.get("first_seen_at")),
            _parse_dt(job.get("last_seen_at")),
        )
        if parsed is not None
    ]
    return max(candidates) if candidates else None


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
    if str(job.get("source") or "").strip():
        return 35
    return 20


def _effort_score(job: dict[str, Any]) -> int:
    apply_type = str(job.get("apply_type") or "").strip().lower()
    has_direct_apply = bool(job.get("apply_url") or job.get("external_apply_url"))
    score = 62
    if apply_type in {"easy_apply", "one_click", "quick_apply"}:
        score += 22
    elif apply_type in {"external", "redirect"}:
        score -= 8
    if has_direct_apply:
        score += 6
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
    decision = str(ranking.get("decision") or "")
    if decision == "AVOID":
        return 0
    if decision == "SKIP":
        return 15
    evidence = _ranking_evidence(ranking)
    dealbreakers = evidence.get("dealbreakers") or []
    if dealbreakers:
        return 20
    return 82 if job.get("is_active", 1) else 0


def _risk_penalty(job: dict[str, Any], ranking: dict[str, Any]) -> int:
    evidence = _ranking_evidence(ranking)
    scores = ranking.get("scores") if isinstance(ranking.get("scores"), dict) else {}
    risk = _clamp_int(scores.get("risk_penalty") or 0)
    if evidence.get("red_flags"):
        risk = max(risk, 25)
    if evidence.get("dealbreakers"):
        risk = max(risk, 40)
    if _data_quality_score(job) < 55:
        risk += 20
    if str(job.get("pipeline_status") or "") == "discarded":
        risk += 80
    return _clamp_int(risk)


def _ranking_evidence(ranking: dict[str, Any]) -> dict[str, Any]:
    evidence = ranking.get("evidence") or ranking.get("evidence_json") or {}
    if isinstance(evidence, dict):
        return evidence
    try:
        parsed = json.loads(str(evidence))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _estimated_minutes(job: dict[str, Any], effort_score: int) -> int:
    if effort_score >= 85:
        return 4
    if effort_score >= 70:
        return 7
    if effort_score >= 50:
        return 12
    return 18


def _blocker(job: dict[str, Any], ranking: dict[str, Any], quality: int, risk: int) -> str | None:
    profile_status = str((ranking.get("generation") or {}).get("profile_status") or "")
    if profile_status == "stale":
        return "Ranking uses an outdated candidate profile"
    if quality < 60:
        return "Missing job data"
    if risk >= 60:
        return "High application risk"
    return None


def _next_action(
    job: dict[str, Any],
    ranking: dict[str, Any],
    priority: int,
    blocker: str | None,
) -> str:
    profile_status = str((ranking.get("generation") or {}).get("profile_status") or "")
    if profile_status == "stale":
        return "Re-rank"
    decision = str(ranking.get("decision") or "")
    if decision in {"AVOID", "SKIP"}:
        return "Skip"
    if blocker:
        return "Needs input"
    if decision == "MAYBE":
        return "Review"
    status = str(job.get("pipeline_status") or "new")
    if decision == "APPLY_NOW" and status in {"shortlisted", "ready_to_apply"}:
        return "Apply now"
    if status == "ready_to_apply":
        return "Review"
    if decision in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"}:
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
