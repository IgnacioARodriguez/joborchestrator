from __future__ import annotations

import asyncio
import time
from datetime import datetime

from joborchestrator.scanning.models import ScanResult
from joborchestrator.scanning.providers import ProviderError
from joborchestrator.scanning.search_providers import get_search_provider
from joborchestrator.storage import persistence as db

DEFAULT_SEARCH_CONCURRENCY = 4


async def search_provider_jobs(
    provider_name: str,
    query: str,
    location: str | None = None,
    *,
    remote: bool = True,
    max_pages: int = 1,
) -> ScanResult:
    started = datetime.now().isoformat(timespec="seconds")
    started_timer = time.perf_counter()
    display_ref = f"{query} / {location or 'anywhere'}"
    result = ScanResult(
        source_type=provider_name,
        company_name=query,
        company_ref=display_ref,
    )
    provider = get_search_provider(provider_name)
    if provider is None:
        result.errors.append(f"Unsupported search provider: {provider_name}")
        return result

    try:
        jobs = []
        for page in range(1, max(1, max_pages) + 1):
            jobs.extend(await provider.search_jobs(query, location, remote=remote, page=page))
        seen_at = datetime.now().isoformat(timespec="seconds")
        buckets = db.upsert_job_postings(jobs, seen_at=seen_at)
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
    except Exception as exc:
        result.errors.append(f"Unexpected search error: {exc}")
        status = "error"
        error = str(exc)

    finished = datetime.now().isoformat(timespec="seconds")
    result.duration_seconds = round(time.perf_counter() - started_timer, 3)
    db.record_scan_event(
        source_id=None,
        provider=provider_name,
        company_name=query,
        company_ref=display_ref,
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
    return result


async def search_jobs_concurrently(
    providers: list[str],
    queries: list[str],
    location: str | None = None,
    *,
    remote: bool = True,
    max_pages: int = 1,
    max_concurrency: int = DEFAULT_SEARCH_CONCURRENCY,
) -> list[ScanResult]:
    semaphore = asyncio.Semaphore(max(1, int(max_concurrency or DEFAULT_SEARCH_CONCURRENCY)))

    async def _run(provider_name: str, query: str) -> ScanResult:
        async with semaphore:
            return await search_provider_jobs(
                provider_name,
                query,
                location,
                remote=remote,
                max_pages=max_pages,
            )

    tasks = [_run(provider, query) for provider in providers for query in queries if query.strip()]
    return await asyncio.gather(*tasks) if tasks else []
