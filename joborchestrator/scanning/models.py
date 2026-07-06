from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class JobPosting:
    external_id: str
    source: str
    company: str
    title: str | None = None
    location: str | None = None
    workplace_type: str | None = None
    department: str | None = None
    url: str | None = None
    apply_url: str | None = None
    description_html: str | None = None
    description_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    posted_at: str | None = None
    scraped_at: str | None = None
    posted_at_raw: str | None = None
    posted_at_estimated: str | None = None
    posted_at_confidence: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    times_seen: int = 0
    is_active: bool = True
    content_hash: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    status: str = "seen"
    parse_confidence: float | None = None
    data_quality_flags: list[str] = field(default_factory=list)
    repost_key: str | None = None
    soft_identity_key: str | None = None

    @property
    def stable_key(self) -> tuple[str, str, str]:
        return (self.source, self.company, self.external_id)


@dataclass(slots=True)
class ScanError:
    source: str
    company_ref: str
    message: str


@dataclass(slots=True)
class ScanResult:
    source_type: str
    company_name: str
    company_ref: str
    jobs: list[JobPosting] = field(default_factory=list)
    new_jobs: list[JobPosting] = field(default_factory=list)
    updated_jobs: list[JobPosting] = field(default_factory=list)
    unchanged_jobs: list[JobPosting] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def found_count(self) -> int:
        return len(self.jobs)
