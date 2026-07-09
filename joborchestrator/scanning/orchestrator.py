from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from joborchestrator.api_dto import scan_result_dto
from joborchestrator.scanning import linkedin
from joborchestrator.scanning import scanner as source_scanner
from joborchestrator.scanning import search_scanner
from joborchestrator.scanning.linkedin_importer import import_linkedin_dataframe_to_job_postings
from joborchestrator.scanning.search_providers import SEARCH_PROVIDERS
from joborchestrator.storage import persistence as db

ProgressCallback = Callable[[str], None]


async def run_unified_job_scan(input_payload: dict[str, Any], progress: ProgressCallback | None = None) -> dict[str, Any]:
    payload = normalize_job_scan_payload(input_payload)
    tasks: dict[str, Any] = {}

    if payload["include_ats"]:
        sources = db.list_company_sources(enabled_only=True).to_dict("records")
        if payload["source_ids"]:
            wanted = {int(source_id) for source_id in payload["source_ids"]}
            sources = [source for source in sources if int(source["id"]) in wanted]
        if sources:
            _progress(progress, f"Launching ATS scans for {len(sources)} source(s).")
            tasks["ats"] = source_scanner.scan_sources_concurrently(
                sources,
                max_concurrency=payload["ats_max_concurrency"],
            )

    if payload["include_search"]:
        providers = payload["search_providers"] or sorted(SEARCH_PROVIDERS.keys())
        bad = [provider for provider in providers if provider not in SEARCH_PROVIDERS]
        if bad:
            raise ValueError(f"Unsupported search providers: {bad}")
        queries = [query.strip() for query in payload["queries"] if str(query).strip()]
        if providers and queries:
            _progress(progress, f"Launching search APIs for {len(queries)} query(s).")
            tasks["search"] = search_scanner.search_jobs_concurrently(
                providers,
                queries,
                payload["location"],
                remote=payload["remote"],
                max_pages=payload["max_pages"],
                max_concurrency=payload["search_max_concurrency"],
            )

    if payload["include_linkedin"]:
        _progress(progress, "Launching LinkedIn scraper with the selected browser profile.")
        tasks["linkedin"] = _run_linkedin_scan()

    if not tasks:
        return {"ats": [], "search": [], "linkedin": None, "errors": {}, "summary": _summary([], [], None, {})}

    _progress(progress, f"Waiting for {', '.join(tasks.keys())} scan lane(s).")
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    output: dict[str, Any] = {"ats": [], "search": [], "linkedin": None, "errors": {}}
    for name, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            output["errors"][name] = str(result)
        elif name in {"ats", "search"}:
            output[name] = [scan_result_dto(item) for item in result]
        else:
            output[name] = result
    output["summary"] = _summary(output["ats"], output["search"], output["linkedin"], output["errors"])
    _progress(progress, "Job scan completed.")
    return output


def normalize_job_scan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "include_ats": bool(payload.get("include_ats", True)),
        "include_search": bool(payload.get("include_search", True)),
        "include_linkedin": bool(payload.get("include_linkedin", False)),
        "source_ids": payload.get("source_ids") or None,
        "search_providers": list(payload.get("search_providers") or []),
        "queries": list(payload.get("queries") or []),
        "location": payload.get("location") or "Spain",
        "remote": bool(payload.get("remote", True)),
        "max_pages": max(1, min(int(payload.get("max_pages") or 1), 10)),
        "ats_max_concurrency": max(1, min(int(payload.get("ats_max_concurrency") or 6), 20)),
        "search_max_concurrency": max(1, min(int(payload.get("search_max_concurrency") or 4), 20)),
    }


async def _run_linkedin_scan() -> dict[str, Any]:
    scraped = await linkedin.run_linkedin_scrape()
    import_stats = import_linkedin_dataframe_to_job_postings(scraped) if not scraped.empty else {
        "new": 0,
        "updated": 0,
        "seen": 0,
        "total": 0,
    }
    inactive = db.mark_jobs_inactive_by_last_seen(
        "linkedin_scraper",
        linkedin.FRESHNESS_WINDOW_SECONDS,
    )
    return {"import_stats": import_stats, "inactive": inactive}


def _summary(ats: list[dict], search: list[dict], linkedin: dict[str, Any] | None, errors: dict[str, str]) -> dict[str, int]:
    scan_results = [*ats, *search]
    linkedin_stats = (linkedin or {}).get("import_stats") or {}
    return {
        "lanes": len(scan_results) + (1 if linkedin else 0),
        "found": sum(int(result.get("found_count") or 0) for result in scan_results) + int(linkedin_stats.get("total") or 0),
        "new": sum(int(result.get("new_count") or 0) for result in scan_results) + int(linkedin_stats.get("new") or 0),
        "updated": sum(int(result.get("updated_count") or 0) for result in scan_results) + int(linkedin_stats.get("updated") or 0),
        "errors": len(errors),
    }


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)
