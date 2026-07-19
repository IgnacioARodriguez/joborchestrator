from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

from joborchestrator.api_dto import latest_rankings_by_job_id, parse_json_value
from joborchestrator.intelligence.application_materials import build_application_kit
from joborchestrator.intelligence.cv_profile_extractor import CVProfileError, build_profile_from_cv_text
from joborchestrator.intelligence.llm_application_materials import (
    DEFAULT_MATERIALS_MODEL,
    DEFAULT_NVIDIA_MATERIALS_MODEL,
    build_application_kit_with_llm,
    build_application_kit_with_nvidia,
    materials_prompt_versions,
)
from joborchestrator.llm.provider import ProviderRegistry
from joborchestrator.automation.executor import run_application_execution
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.scanning.orchestrator import run_unified_job_scan
from joborchestrator.scanning.linkedin_enrichment import run_linkedin_enrichment_sync
from joborchestrator.storage import persistence as db

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
DEFAULT_POLL_SECONDS = float(os.getenv("JOB_WORKER_POLL_SECONDS", "5"))
DEFAULT_STALE_SECONDS = int(os.getenv("JOB_WORKER_STALE_SECONDS", "3600"))
OPERATION_TYPES = [
    "cv_profile_import",
    "application_materials_generation",
    "job_scan",
    "linkedin_enrichment",
    "application_execution",
]


def configure_logging() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("joborchestrator.worker")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    file_handler = logging.FileHandler(log_dir / "worker.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    return logger


logger = configure_logging()


def process_once(worker_id: str = WORKER_ID) -> bool:
    requeued = db.requeue_stale_operations(OPERATION_TYPES, stale_seconds=DEFAULT_STALE_SECONDS)
    if requeued:
        logger.warning("Requeued stale operations count=%s stale_seconds=%s", requeued, DEFAULT_STALE_SECONDS)
    operation = db.claim_next_operation(worker_id, OPERATION_TYPES)
    if not operation:
        return False
    operation_id = int(operation["id"])
    operation_type = str(operation["type"])
    logger.info("Claimed operation id=%s type=%s", operation_id, operation_type)
    try:
        if operation_type == "cv_profile_import":
            _process_cv_profile_import(operation)
        elif operation_type == "application_materials_generation":
            _process_application_materials_generation(operation)
        elif operation_type == "job_scan":
            _process_job_scan(operation)
        elif operation_type == "linkedin_enrichment":
            _process_linkedin_enrichment(operation)
        elif operation_type == "application_execution":
            _process_application_execution(operation)
        else:
            raise RuntimeError(f"Unsupported operation type: {operation_type}")
    except Exception as exc:  # noqa: BLE001 - worker must persist failures.
        logger.exception("Operation failed id=%s", operation_id)
        db.fail_operation(operation_id, str(exc), "Worker failed. Check local logs.")
    return True


def run_poll_loop(poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
    logger.info("Worker started id=%s poll_seconds=%s", WORKER_ID, poll_seconds)
    db.init_db()
    while True:
        processed = process_once()
        if not processed:
            time.sleep(poll_seconds)


def _process_cv_profile_import(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = operation.get("input_json") or {}
    filename = str(input_payload.get("filename") or "cv")
    cv_text = str(input_payload.get("cv_text") or "")
    logger.info("Processing CV profile import id=%s file=%s chars=%s", operation_id, filename, len(cv_text))
    db.update_operation_progress(operation_id, "Calling NVIDIA to analyze your CV.")
    try:
        profile = build_profile_from_cv_text(cv_text, timeout=180.0)
    except CVProfileError:
        raise
    profile["base_cv_text"] = cv_text
    profile["base_cv_filename"] = filename
    db.update_operation_progress(operation_id, "Saving extracted profile.")
    db.save_candidate_profile_payload(profile)
    db.complete_operation(
        operation_id,
        {
            "profile_saved": True,
            "skill_count": len(profile.get("skills") or []),
            "target_role_count": len(profile.get("target_roles") or []),
        },
        "Profile ready.",
    )
    logger.info(
        "Completed CV profile import id=%s skills=%s roles=%s",
        operation_id,
        len(profile.get("skills") or []),
        len(profile.get("target_roles") or []),
    )


def _process_application_materials_generation(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = operation.get("input_json") or {}
    job_id = int(input_payload.get("job_id") or 0)
    provider = str(input_payload.get("provider") or ProviderRegistry().provider_name_for_role("materials"))
    model = str(input_payload.get("model") or "")
    shortlist = bool(input_payload.get("shortlist", True))
    if not job_id:
        raise RuntimeError("application_materials_generation requires job_id.")

    job, ranking = _job_for_materials(job_id)
    logger.info("Generating application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)
    db.update_operation_progress(operation_id, f"Generating {provider} application materials.")

    keywords = parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []) if ranking else []
    selected_model = model or DEFAULT_MATERIALS_MODEL
    prompt_versions = materials_prompt_versions() if provider in {"openai", "nvidia"} else {}
    if provider == "openai":
        kit = build_application_kit_with_llm(job, ranking=ranking, model=selected_model)
    elif provider == "nvidia":
        selected_model = model if model and model != DEFAULT_MATERIALS_MODEL else DEFAULT_NVIDIA_MATERIALS_MODEL
        kit = build_application_kit_with_nvidia(
            job,
            ranking=ranking,
            model=selected_model,
        )
    elif provider == "heuristic":
        selected_model = "heuristic"
        kit = build_application_kit(job, keywords=keywords)
    else:
        raise RuntimeError(f"Unsupported materials provider: {provider}")

    db.update_operation_progress(operation_id, "Saving generated application materials.")
    ats_cv_text = kit.get("ats_cv_text") or kit.get("ats_cv_notes")
    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted" if shortlist else None,
        recruiter_message=kit.get("recruiter_message"),
        cover_letter=kit.get("cover_letter"),
        ats_cv_text=ats_cv_text,
        autofill_notes=kit.get("autofill_notes"),
        materials_provider=provider,
        materials_model=selected_model,
        materials_prompt_versions=prompt_versions,
    )
    resume_variant = None
    if ats_cv_text:
        resume_variant = db.register_generated_resume_variant(
            job_id,
            f"{job.get('company') or 'Company'} - {job.get('title') or 'Role'} ATS CV",
            str(ats_cv_text),
        )
    db.complete_operation(
        operation_id,
        {
            "job_id": job_id,
            "provider": provider,
            "materials_saved": True,
            "resume_variant_id": resume_variant.get("id") if resume_variant else None,
        },
        "Application materials ready.",
    )
    logger.info("Completed application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)


def _process_job_scan(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = {**(operation.get("input_json") or {}), "operation_id": operation_id}
    scan_started_at = str(operation.get("started_at") or operation.get("created_at") or "")
    logger.info("Processing job scan operation=%s", operation_id)

    def progress(message: str) -> None:
        logger.info("Job scan operation=%s progress=%s", operation_id, message)
        db.update_operation_progress(operation_id, message)

    output = asyncio.run(run_unified_job_scan(input_payload, progress=progress))
    summary = output.get("summary") or {}
    output["ranking_job"] = _queue_post_scan_ranking(input_payload, scan_started_at, summary, progress)
    db.complete_operation(
        operation_id,
        output,
        (
            "Job scan completed: "
            f"{summary.get('new', 0)} new, "
            f"{summary.get('updated', 0)} updated, "
            f"{summary.get('errors', 0)} errors."
        ),
    )
    logger.info("Completed job scan operation=%s summary=%s", operation_id, summary)


def _queue_post_scan_ranking(
    input_payload: dict[str, Any],
    scan_started_at: str,
    summary: dict[str, Any],
    progress: Any,
) -> dict[str, Any]:
    if not input_payload.get("auto_rank_new", True):
        return {"queued": 0, "skipped": "disabled"}
    if not db.get_candidate_profile_payload():
        return {"queued": 0, "skipped": "missing_candidate_profile"}
    if int(summary.get("new") or 0) + int(summary.get("updated") or 0) <= 0:
        return {"queued": 0, "skipped": "no_new_or_updated_jobs"}

    ranking_version = str(input_payload.get("ranking_version") or NVIDIA_RANKING_VERSION)
    limit = max(1, min(int(input_payload.get("ranking_limit") or 250), 2000))
    candidates = db.get_jobs_for_post_scan_ranking(
        seen_since=scan_started_at,
        ranking_version=ranking_version,
        limit=limit,
    )
    job_ids = [int(value) for value in candidates["id"].tolist()]
    if not job_ids:
        return {"queued": 0, "skipped": "no_unranked_scan_jobs"}

    progress(f"Queueing NVIDIA ranking for {len(job_ids)} new or updated job(s).")
    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model=str(input_payload.get("ranking_model") or DEFAULT_NVIDIA_MODEL),
        ranking_version=ranking_version,
        job_ids=job_ids,
        request_batch_size=int(input_payload.get("ranking_request_batch_size") or DEFAULT_NVIDIA_REQUEST_BATCH_SIZE),
        max_concurrency=int(input_payload.get("ranking_max_concurrency") or DEFAULT_NVIDIA_MAX_CONCURRENCY),
    )
    return {
        "ranking_job_id": ranking_job_id,
        "queued": len(job_ids),
        "ranking_version": ranking_version,
    }


def _process_linkedin_enrichment(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = operation.get("input_json") or {}
    logger.info("Processing LinkedIn enrichment operation=%s", operation_id)

    def progress(message: str) -> None:
        logger.info("LinkedIn enrichment operation=%s progress=%s", operation_id, message)
        db.update_operation_progress(operation_id, message)

    output = run_linkedin_enrichment_sync(
        operation_id=operation_id,
        limit=max(1, min(int(input_payload.get("limit") or 25), 250)),
        ranking_version=str(input_payload.get("ranking_version") or NVIDIA_RANKING_VERSION),
        decisions=list(input_payload.get("decisions") or ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]),
        job_ids=[int(value) for value in input_payload.get("job_ids") or []] or None,
        force=bool(input_payload.get("force", False)),
        resolve_external_apply=bool(input_payload.get("resolve_external_apply", True)),
        progress=progress,
    )
    summary = output.get("summary") or {}
    db.complete_operation(
        operation_id,
        output,
        (
            "LinkedIn enrichment completed: "
            f"{summary.get('saved', 0)} saved, "
            f"{summary.get('failed', 0)} failed."
        ),
    )
    logger.info("Completed LinkedIn enrichment operation=%s summary=%s", operation_id, summary)


def _process_application_execution(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = operation.get("input_json") or {}
    session_id = int(input_payload.get("session_id") or 0)
    job_id = int(input_payload.get("job_id") or 0)
    apply_url = str(input_payload.get("apply_url") or "")
    provider = str(input_payload.get("provider") or "generic")
    dry_run = bool(input_payload.get("dry_run", True))
    if not session_id or not job_id or not apply_url:
        raise RuntimeError("application_execution requires session_id, job_id and apply_url.")

    logger.info("Executing application operation=%s session=%s job=%s provider=%s", operation_id, session_id, job_id, provider)

    def progress(message: str) -> None:
        logger.info("Application execution operation=%s progress=%s", operation_id, message)
        db.update_operation_progress(operation_id, message)

    output = asyncio.run(
        run_application_execution(
            session_id=session_id,
            job_id=job_id,
            apply_url=apply_url,
            provider_hint=provider,
            dry_run=dry_run,
            progress=progress,
        )
    )
    db.complete_operation(operation_id, output, "Application dry-run completed.")
    logger.info("Completed application execution operation=%s output=%s", operation_id, output)


def _job_for_materials(job_id: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    job = db.get_job_posting(job_id)
    if not job:
        raise RuntimeError(f"Job not found: {job_id}")
    ranking = latest_rankings_by_job_id().get(job_id)
    if ranking:
        job.update(
            {
                "final_score": ranking.get("final_score"),
                "decision": ranking.get("decision"),
                "reasoning_summary": ranking.get("reasoning_summary"),
                "recommended_application_angle": ranking.get("recommended_application_angle"),
                "cv_keywords_to_emphasize": parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []),
            }
        )
    return job, ranking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Job Orchestrator local worker.")
    parser.add_argument("--once", action="store_true", help="Process one queued operation and exit.")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)
    if args.once:
        db.init_db()
        processed = process_once()
        logger.info("Worker once finished processed=%s", processed)
        return 0
    run_poll_loop(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
