from __future__ import annotations

import time
import asyncio
from datetime import datetime
from typing import Any

from joborchestrator.scanning.models import ScanResult
from joborchestrator.scanning.providers import ProviderError, list_jobs_for_source
from joborchestrator.storage import persistence as db

DEFAULT_SCAN_CONCURRENCY = 6


async def scan_company_source(
    source_type: str,
    company_ref: str,
    company_name: str | None = None,
    source_id: int | None = None,
) -> ScanResult:
    started = datetime.now().isoformat(timespec="seconds")
    started_timer = time.perf_counter()
    display_name = company_name or company_ref
    result = ScanResult(
        source_type=source_type,
        company_name=display_name,
        company_ref=company_ref,
    )

    try:
        jobs = await list_jobs_for_source(source_type, company_ref, display_name)
        seen_at = datetime.now().isoformat(timespec="seconds")
        buckets = db.upsert_job_postings(jobs, seen_at=seen_at)
        db.mark_jobs_inactive_for_source(
            source_type,
            display_name,
            {job.external_id for job in jobs if job.external_id},
        )

        result.jobs = jobs
        result.new_jobs = buckets.get("new", [])
        result.updated_jobs = buckets.get("updated", [])
        result.unchanged_jobs = buckets.get("seen", [])
        status = "success"
        error = None
    except ProviderError as exc:
        result.errors.append(str(exc))
        status = "error"
        error = str(exc)
    except Exception as exc:  # keep one broken source from killing the scan
        result.errors.append(f"Unexpected scan error: {exc}")
        status = "error"
        error = str(exc)

    finished = datetime.now().isoformat(timespec="seconds")
    result.duration_seconds = round(time.perf_counter() - started_timer, 3)
    db.record_scan_event(
        source_id=source_id,
        provider=source_type,
        company_name=display_name,
        company_ref=company_ref,
        started_at=started,
        finished_at=finished,
        status=status,
        found_count=len(result.jobs),
        new_count=len(result.new_jobs),
        updated_count=len(result.updated_jobs),
        unchanged_count=len(result.unchanged_jobs),
        error=error,
        duration_seconds=result.duration_seconds,
    )
    if source_id is not None:
        db.update_source_scan_state(source_id, status, error)

    return result


async def scan_source_row(source: dict[str, Any]) -> ScanResult:
    return await scan_company_source(
        source_type=source["provider"],
        company_ref=source["company_ref"],
        company_name=source["company_name"],
        source_id=int(source["id"]),
    )


async def scan_sources_concurrently(
    sources: list[dict[str, Any]],
    max_concurrency: int = DEFAULT_SCAN_CONCURRENCY,
) -> list[ScanResult]:
    concurrency = max(1, int(max_concurrency or DEFAULT_SCAN_CONCURRENCY))
    semaphore = asyncio.Semaphore(concurrency)

    async def _run(source: dict[str, Any]) -> ScanResult:
        async with semaphore:
            return await scan_source_row(source)

    return await asyncio.gather(*[_run(source) for source in sources])


async def scan_enabled_sources(max_concurrency: int = DEFAULT_SCAN_CONCURRENCY) -> list[ScanResult]:
    sources = db.list_company_sources(enabled_only=True)
    return await scan_sources_concurrently(
        sources.to_dict("records"),
        max_concurrency=max_concurrency,
    )
