from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import clean_display_text, compute_content_hash, first_value
from joborchestrator.storage import persistence as db

LINKEDIN_SOURCE = "linkedin_scraper"

_JOB_ID_PATTERNS = [
    re.compile(r"/jobs/view/(\d+)", re.IGNORECASE),
    re.compile(r"[?&](?:currentJobId|jobId)=(\d+)", re.IGNORECASE),
    re.compile(r"[?&]jk=([A-Za-z0-9_-]+)", re.IGNORECASE),
]


def linkedin_dataframe_to_job_postings(df: pd.DataFrame) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for _, row in df.iterrows():
        job = linkedin_row_to_job_posting(row.to_dict())
        if job:
            jobs.append(job)
    return jobs


def import_linkedin_dataframe_to_job_postings(df: pd.DataFrame) -> dict[str, Any]:
    jobs = linkedin_dataframe_to_job_postings(df)
    buckets = db.upsert_job_postings(jobs)
    return {
        "jobs": jobs,
        "new": len(buckets.get("new", [])),
        "updated": len(buckets.get("updated", [])),
        "seen": len(buckets.get("seen", [])),
        "total": len(jobs),
    }


def linkedin_row_to_job_posting(row: dict[str, Any]) -> JobPosting | None:
    normalized = {str(k).strip(): _clean_value(v) for k, v in row.items()}
    title = _text(first_value(normalized.get("title"), normalized.get("titulo"), normalized.get("puesto")))
    company = _text(first_value(normalized.get("company"), normalized.get("empresa")))
    url = _text(first_value(normalized.get("url"), normalized.get("job_url"), normalized.get("link")))
    apply_url = _text(
        first_value(
            normalized.get("apply_url"),
            normalized.get("application_url"),
            normalized.get("portal_url"),
            normalized.get("url_portal"),
            normalized.get("solicitud_url"),
            url,
        )
    )
    external_id = extract_linkedin_external_id(normalized, url=url, title=title, company=company)

    if not external_id or not title or not company:
        return None

    location = _text(first_value(normalized.get("location"), normalized.get("ubicacion")))
    workplace_type = _text(first_value(normalized.get("workplace_type"), normalized.get("modalidad")))
    description = _text(first_value(normalized.get("description_text"), normalized.get("description"), normalized.get("descripcion")))
    posted_at = _text(first_value(normalized.get("posted_at"), normalized.get("fecha_publicacion"), normalized.get("fecha_publicada"), normalized.get("fecha")))
    parse_confidence, flags = parse_quality(normalized, title=title, company=company, url=url, location=location, description=description)

    raw_payload = {key: _json_safe(value) for key, value in normalized.items()}
    raw_payload["source_adapter"] = LINKEDIN_SOURCE

    return JobPosting(
        external_id=external_id,
        source=LINKEDIN_SOURCE,
        company=company,
        title=title,
        location=location,
        workplace_type=workplace_type,
        department=None,
        url=url,
        apply_url=apply_url,
        description_text=description,
        posted_at=posted_at,
        content_hash=compute_content_hash(title, company, location, description, apply_url),
        raw_payload=raw_payload,
        parse_confidence=parse_confidence,
        data_quality_flags=flags,
    )


def extract_linkedin_external_id(
    row: dict[str, Any] | None = None,
    *,
    url: str | None = None,
    title: str | None = None,
    company: str | None = None,
) -> str:
    row = row or {}
    explicit_id = _text(first_value(row.get("external_id"), row.get("id"), row.get("job_id"), row.get("linkedin_id")))
    if explicit_id and explicit_id.lower() not in {"nan", "none"}:
        return explicit_id

    candidate_url = url or _text(first_value(row.get("url"), row.get("job_url"), row.get("link")))
    for pattern in _JOB_ID_PATTERNS:
        match = pattern.search(candidate_url or "")
        if match:
            return match.group(1)

    seed = "|".join(str(x or "") for x in [title, company, candidate_url])
    return f"hash:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}" if seed.strip("|") else ""


def parse_quality(
    row: dict[str, Any],
    *,
    title: str | None,
    company: str | None,
    url: str | None,
    location: str | None,
    description: str | None,
) -> tuple[float, list[str]]:
    flags: list[str] = []
    score = 0.25

    extraction_ok = _boolish(first_value(row.get("extraccion_ok"), row.get("extraction_ok")))
    if extraction_ok is False:
        flags.append("LinkedIn extraction marked as failed")
    elif extraction_ok is True:
        score += 0.18

    if title:
        score += 0.12
    else:
        flags.append("Missing title")
    if company:
        score += 0.12
    else:
        flags.append("Missing company")
    if url:
        score += 0.12
    else:
        flags.append("Missing job URL")
    if location:
        score += 0.08
    else:
        flags.append("Missing location")

    description_len = len(description or "")
    if description_len >= 600:
        score += 0.22
    elif description_len >= 250:
        score += 0.14
    elif description_len >= 80:
        score += 0.06
        flags.append("Short description")
    else:
        flags.append("Very short or missing description")

    if extraction_ok is False:
        score = min(score, 0.45)

    return round(max(0.0, min(1.0, score)), 2), _dedupe(flags)


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _text(value: Any) -> str | None:
    text = clean_display_text(value)
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    return text


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "si", "sí", "ok"}:
        return True
    if text in {"false", "0", "no", "fail", "failed", "error"}:
        return False
    return None


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    return str(value)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out
