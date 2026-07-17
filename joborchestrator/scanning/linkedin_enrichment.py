from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from playwright.async_api import async_playwright

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.scanning import linkedin
from joborchestrator.scanning.hiring_contacts import parse_hiring_contacts_value
from joborchestrator.storage import persistence as db

ProgressCallback = Callable[[str], None]


async def run_linkedin_enrichment(
    *,
    operation_id: int | None = None,
    limit: int = 25,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    decisions: list[str] | None = None,
    job_ids: list[int] | None = None,
    force: bool = False,
    resolve_external_apply: bool = True,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    decisions = decisions or ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]
    candidates = db.get_linkedin_enrichment_candidates(
        ranking_version=ranking_version,
        decisions=decisions,
        limit=limit,
        job_ids=job_ids,
        force=force,
    )
    jobs = candidates.to_dict("records")
    summary = {
        "queued": len(jobs),
        "processed": 0,
        "saved": 0,
        "failed": 0,
        "external_apply_urls": 0,
        "easy_apply": 0,
        "recruiters": 0,
        "applicant_counts": 0,
    }
    if not jobs:
        return {"summary": summary, "items": []}

    items: list[dict[str, Any]] = []
    async with async_playwright() as p:
        context, page = await linkedin.crear_contexto_linkedin(p)
        try:
            await linkedin.asegurar_sesion_manual(page)
            for index, job in enumerate(jobs, start=1):
                if progress:
                    progress(f"Enriching LinkedIn job {index}/{len(jobs)}: {job.get('title') or job.get('external_id')}.")
                item = await enrich_linkedin_job(
                    page,
                    job,
                    operation_id=operation_id,
                    resolve_external_apply=resolve_external_apply,
                )
                items.append(item)
                summary["processed"] += 1
                if item["status"] == "completed":
                    summary["saved"] += 1
                    if item.get("external_apply_url"):
                        summary["external_apply_urls"] += 1
                    if item.get("easy_apply_available"):
                        summary["easy_apply"] += 1
                    if item.get("recruiter_name") or item.get("recruiter_profile_url"):
                        summary["recruiters"] += 1
                    if item.get("applicant_count") is not None:
                        summary["applicant_counts"] += 1
                else:
                    summary["failed"] += 1
        finally:
            await context.close()
    return {"summary": summary, "items": items}


async def enrich_linkedin_job(
    page,
    job: dict[str, Any],
    *,
    operation_id: int | None,
    resolve_external_apply: bool,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    timer = time.perf_counter()
    job_id = int(job["id"])
    external_id = str(job.get("external_id") or "")
    url = str(job.get("url") or f"https://www.linkedin.com/jobs/view/{external_id}/")
    item: dict[str, Any] = {
        "job_posting_id": job_id,
        "linkedin_external_id": external_id,
        "status": "failed",
        "apply_type": _clean(job.get("apply_type")),
        "external_apply_url": _clean(job.get("external_apply_url")),
        "easy_apply_available": False,
        "applicant_count": _clean(job.get("applicant_count")),
        "applicant_count_raw": _clean(job.get("applicant_count_raw")),
        "recruiter_name": _clean(job.get("recruiter_name")),
        "recruiter_profile_url": _clean(job.get("recruiter_profile_url")),
        "hiring_contacts_json": "[]",
        "error": None,
    }
    try:
        await linkedin.navegar_estable(page, url)
        await page.wait_for_timeout(linkedin.jitter_ms(1200))
        if await linkedin.linkedin_pide_verificacion(page):
            raise RuntimeError("LinkedIn requested verification during enrichment.")

        data = await linkedin.extraer_datos_job_desde_panel(page)
        item.update(
            {
                "apply_type": data.get("apply_type") or item.get("apply_type"),
                "external_apply_url": data.get("external_apply_url") or item.get("external_apply_url"),
                "applicant_count": data.get("cantidad_solicitantes"),
                "applicant_count_raw": data.get("cantidad_solicitantes_raw"),
                "recruiter_name": data.get("recruiter_name"),
                "recruiter_profile_url": data.get("recruiter_profile_url"),
                "hiring_contacts_json": data.get("hiring_contacts") or "[]",
            }
        )
        item["easy_apply_available"] = item.get("apply_type") == "easy_apply"
        if (
            resolve_external_apply
            and item.get("apply_type") == "external"
            and not item.get("external_apply_url")
            and external_id
        ):
            item["external_apply_url"] = await linkedin.resolve_external_apply_url(page, external_id)

        contacts = parse_hiring_contacts_value(item.get("hiring_contacts_json"))
        if contacts and not item.get("recruiter_name"):
            primary = contacts[0]
            item["recruiter_name"] = primary.name
            item["recruiter_profile_url"] = primary.profile_url
        item["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - enrichments are best-effort per job.
        item["error"] = str(exc)
    finally:
        finished_at = datetime.now().isoformat(timespec="seconds")
        duration = round(time.perf_counter() - timer, 3)
        db.upsert_linkedin_job_enrichment(
            operation_id=operation_id,
            job_posting_id=job_id,
            linkedin_external_id=external_id,
            started_at=started_at,
            finished_at=finished_at,
            status=str(item["status"]),
            apply_type=_clean(item.get("apply_type")),
            external_apply_url=_clean(item.get("external_apply_url")),
            easy_apply_available=bool(item.get("easy_apply_available")),
            applicant_count=_clean(item.get("applicant_count")),
            applicant_count_raw=_clean(item.get("applicant_count_raw")),
            recruiter_name=_clean(item.get("recruiter_name")),
            recruiter_profile_url=_clean(item.get("recruiter_profile_url")),
            hiring_contacts_json=_clean(item.get("hiring_contacts_json")),
            error=_clean(item.get("error")),
            duration_seconds=duration,
            raw={key: _clean(value) for key, value in item.items()},
        )
        item["duration_seconds"] = duration
    return item


def run_linkedin_enrichment_sync(**kwargs) -> dict[str, Any]:
    return asyncio.run(run_linkedin_enrichment(**kwargs))


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none"}:
        return None
    return value
