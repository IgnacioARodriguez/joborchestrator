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
)
from joborchestrator.scanning.orchestrator import run_unified_job_scan
from joborchestrator.storage import persistence as db

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
DEFAULT_POLL_SECONDS = float(os.getenv("JOB_WORKER_POLL_SECONDS", "5"))


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
    operation = db.claim_next_operation(worker_id, ["cv_profile_import", "application_materials_generation", "job_scan"])
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
    provider = str(input_payload.get("provider") or "openai")
    model = str(input_payload.get("model") or "")
    shortlist = bool(input_payload.get("shortlist", True))
    if not job_id:
        raise RuntimeError("application_materials_generation requires job_id.")

    job, ranking = _job_for_materials(job_id)
    logger.info("Generating application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)
    db.update_operation_progress(operation_id, f"Generating {provider} application materials.")

    keywords = parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []) if ranking else []
    if provider == "openai":
        kit = build_application_kit_with_llm(job, ranking=ranking, model=model or DEFAULT_MATERIALS_MODEL)
    elif provider == "nvidia":
        kit = build_application_kit_with_nvidia(
            job,
            ranking=ranking,
            model=model if model and model != DEFAULT_MATERIALS_MODEL else DEFAULT_NVIDIA_MATERIALS_MODEL,
        )
    elif provider == "heuristic":
        kit = build_application_kit(job, keywords=keywords)
    else:
        raise RuntimeError(f"Unsupported materials provider: {provider}")

    db.update_operation_progress(operation_id, "Saving generated application materials.")
    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted" if shortlist else None,
        recruiter_message=kit.get("recruiter_message"),
        cover_letter=kit.get("cover_letter"),
        ats_cv_text=kit.get("ats_cv_text") or kit.get("ats_cv_notes"),
        autofill_notes=kit.get("autofill_notes"),
    )
    db.complete_operation(
        operation_id,
        {"job_id": job_id, "provider": provider, "materials_saved": True},
        "Application materials ready.",
    )
    logger.info("Completed application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)


def _process_job_scan(operation: dict[str, Any]) -> None:
    operation_id = int(operation["id"])
    input_payload = operation.get("input_json") or {}
    logger.info("Processing job scan operation=%s", operation_id)

    def progress(message: str) -> None:
        db.update_operation_progress(operation_id, message)

    output = asyncio.run(run_unified_job_scan(input_payload, progress=progress))
    summary = output.get("summary") or {}
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
