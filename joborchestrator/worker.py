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
    LLMMaterialsError,
    build_application_kit_with_llm,
    build_application_kit_with_nvidia,
    build_application_kit_with_provider,
    materials_prompt_versions,
)
from joborchestrator.intelligence.materials_validation import issues_to_dicts, validation_feedback_to_issues
from joborchestrator.intelligence.profile_trace import profile_trace
from joborchestrator.llm.provider import ProviderRegistry
from joborchestrator.material_review import next_material_review_states, normalize_material_targets
from joborchestrator.automation.executor import run_application_execution
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.scanning.orchestrator import run_unified_job_scan
from joborchestrator.scanning.post_scan_ranking import queue_post_scan_ranking
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


def _generate_materials(provider: str, job: Any, **kwargs: Any) -> dict[str, Any]:
    """Worker seam: provider selection is isolated from operation handling."""
    if provider == "nvidia":
        return build_application_kit_with_nvidia(
            job,
            ranking=kwargs.get("ranking"),
            model=kwargs.get("model"),
            cv_strategy=kwargs.get("cv_strategy"),
            **({"targets": kwargs["targets"]} if "targets" in kwargs else {}),
        )
    if provider == "openai":
        return build_application_kit_with_llm(job, ranking=kwargs.get("ranking"), model=kwargs.get("model"))
    if provider == "openrouter":
        return build_application_kit_with_nvidia(
            job, ranking=kwargs.get("ranking"), model=kwargs.get("model"),
            cv_strategy=kwargs.get("cv_strategy"), provider_name="openrouter",
            **({"targets": kwargs["targets"]} if "targets" in kwargs else {}),
        )
    if provider == "heuristic":
        return build_application_kit_with_provider(provider, job, **kwargs)
    return build_application_kit_with_provider(provider, job, **kwargs)


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
    cv_strategy = str(input_payload.get("cv_strategy") or "auto")
    shortlist = bool(input_payload.get("shortlist", True))
    targets = normalize_material_targets(input_payload.get("targets"))
    if not job_id:
        raise RuntimeError("application_materials_generation requires job_id.")

    job, ranking = _job_for_materials(job_id)
    logger.info("Generating application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)
    db.update_operation_progress(operation_id, f"Generating {provider} application materials.")

    keywords = parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []) if ranking else []
    selected_model = model or DEFAULT_MATERIALS_MODEL
    prompt_versions = materials_prompt_versions() if provider in {"openai", "openrouter", "nvidia"} else {}
    if provider == "nvidia":
        selected_model = model if model and model != DEFAULT_MATERIALS_MODEL else DEFAULT_NVIDIA_MATERIALS_MODEL
    elif provider == "heuristic":
        selected_model = "heuristic"
    try:
        generation_kwargs = {
            "ranking": ranking,
            "model": selected_model,
            "cv_strategy": cv_strategy,
            "keywords": keywords,
        }
        if "targets" in input_payload:
            generation_kwargs["targets"] = targets
        kit = _generate_materials(provider, job, **generation_kwargs)
    except LLMMaterialsError as exc:
        _record_failed_materials_attempt(operation_id, job_id, provider, selected_model, prompt_versions, exc)
        raise

    db.update_operation_progress(operation_id, "Saving generated application materials.")
    ats_cv_text = kit.get("ats_cv_text") or kit.get("ats_cv_notes")
    generation_metadata = kit.get("_generation_metadata") if isinstance(kit.get("_generation_metadata"), dict) else {}
    partial_success = bool(generation_metadata.get("partial_success"))
    material_statuses = generation_metadata.get("material_statuses") if isinstance(generation_metadata.get("material_statuses"), dict) else {}
    failed_materials = [str(value) for value in generation_metadata.get("failed_materials") or []]

    def ready_material_value(material: str, value: Any) -> Any:
        if material_statuses and material_statuses.get(material) != "ready":
            return None
        return value

    selected_review_targets = targets
    if material_statuses:
        selected = targets or ["ats_cv", "cover_letter", "recruiter_message", "autofill"]
        selected_review_targets = [
            target
            for target in selected
            if material_statuses.get(target) == "ready"
        ]
    profile_metadata = profile_trace(db.get_candidate_profile_payload())
    generated_values = {
        "recruiter_message": kit.get("recruiter_message"),
        "cover_letter": kit.get("cover_letter"),
        "ats_cv": ats_cv_text,
        "autofill": kit.get("autofill_notes"),
    }
    review_states = next_material_review_states(
        parse_json_value(job.get("materials_review_states_json"), {}),
        selected_review_targets,
        generated_values,
    )
    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted" if shortlist else None,
        recruiter_message=ready_material_value("recruiter_message", kit.get("recruiter_message")) if not targets or "recruiter_message" in targets else None,
        cover_letter=ready_material_value("cover_letter", kit.get("cover_letter")) if not targets or "cover_letter" in targets else None,
        ats_cv_text=ready_material_value("ats_cv", ats_cv_text) if not targets or "ats_cv" in targets else None,
        autofill_notes=ready_material_value("autofill", kit.get("autofill_notes")) if not targets or "autofill" in targets else None,
        materials_provider=provider,
        materials_model=selected_model,
        materials_prompt_versions=prompt_versions,
        materials_validation_attempts=int(generation_metadata.get("validation_attempts") or 1),
        materials_validation_errors=list(generation_metadata.get("validation_errors") or []),
        materials_candidate_profile_hash=profile_metadata.get("hash"),
        materials_candidate_profile_snapshot=profile_metadata.get("snapshot"),
        materials_review_states=review_states,
    )
    _record_successful_materials_attempt(
        operation_id,
        job_id,
        provider,
        selected_model,
        prompt_versions,
        kit,
        generation_metadata,
    )
    resume_variant = None
    if ats_cv_text and (not targets or "ats_cv" in targets):
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
            "partial_success": partial_success,
            "material_statuses": material_statuses,
            "failed_materials": failed_materials,
            "resume_variant_id": resume_variant.get("id") if resume_variant else None,
        },
        (
            "ATS CV ready; some requested materials need regeneration."
            if partial_success
            else "Application materials ready."
        ),
    )
    logger.info("Completed application materials operation=%s job_id=%s provider=%s", operation_id, job_id, provider)


def _record_failed_materials_attempt(
    operation_id: int,
    job_id: int,
    provider: str,
    model: str,
    prompt_versions: dict[str, str],
    exc: LLMMaterialsError,
) -> None:
    metadata = exc.generation_metadata if isinstance(exc.generation_metadata, dict) else {}
    errors = [str(error) for error in metadata.get("validation_errors") or [str(exc)]]
    issues = [
        issue
        for error in errors
        for issue in validation_feedback_to_issues(error)
    ]
    db.record_materials_generation_attempt(
        operation_id=operation_id,
        job_id=job_id,
        stage=str(metadata.get("stage") or "fallback"),
        attempt_number=int(metadata.get("validation_attempts") or 1),
        provider=provider,
        model=model,
        prompt_version=_materials_prompt_versions_text(prompt_versions, metadata),
        input_hash=str(metadata.get("input_hash") or "") or None,
        output_text=str(metadata.get("output_text") or ""),
        validation_issues=issues_to_dicts(issues),
        accepted=False,
    )


def _record_successful_materials_attempt(
    operation_id: int,
    job_id: int,
    provider: str,
    model: str,
    prompt_versions: dict[str, str],
    kit: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    stage_attempts = metadata.get("stage_attempts")
    if isinstance(stage_attempts, list) and stage_attempts:
        for stage_attempt in stage_attempts:
            if isinstance(stage_attempt, dict):
                enriched_attempt = {
                    **{
                        key: metadata.get(key)
                        for key in (
                            "requested_cv_strategy",
                            "selected_pipeline",
                            "effective_flags",
                            "input_hash",
                        )
                        if metadata.get(key) is not None
                    },
                    **stage_attempt,
                }
                _record_successful_materials_stage_attempt(
                    operation_id,
                    job_id,
                    provider,
                    model,
                    prompt_versions,
                    kit,
                    enriched_attempt,
                )
        return
    _record_successful_materials_stage_attempt(
        operation_id,
        job_id,
        provider,
        model,
        prompt_versions,
        kit,
        {
            "stage": str(metadata.get("stage") or metadata.get("pipeline") or "materials_generation"),
            "attempt_number": int(metadata.get("validation_attempts") or 1),
            "validation_errors": [str(error) for error in metadata.get("validation_errors") or []],
            "accepted": True,
            "requested_cv_strategy": metadata.get("requested_cv_strategy"),
            "selected_pipeline": metadata.get("selected_pipeline"),
            "effective_flags": metadata.get("effective_flags"),
            "input_hash": metadata.get("input_hash"),
        },
    )


def _record_successful_materials_stage_attempt(
    operation_id: int,
    job_id: int,
    provider: str,
    model: str,
    prompt_versions: dict[str, str],
    kit: dict[str, Any],
    stage_attempt: dict[str, Any],
) -> None:
    errors = [str(error) for error in stage_attempt.get("validation_errors") or []]
    issues = [
        issue
        for error in errors
        for issue in validation_feedback_to_issues(error)
    ]
    stage = str(stage_attempt.get("stage") or "materials_generation")
    db.record_materials_generation_attempt(
        operation_id=operation_id,
        job_id=job_id,
        stage=stage,
        attempt_number=int(stage_attempt.get("attempt_number") or 1),
        provider=provider,
        model=model,
        prompt_version=_materials_prompt_versions_text(prompt_versions, stage_attempt),
        input_hash=str(stage_attempt.get("input_hash") or "") or None,
        output_text=_materials_stage_output_text(kit, stage),
        validation_issues=issues_to_dicts(issues),
        accepted=bool(stage_attempt.get("accepted", True)),
    )


def _materials_stage_output_text(kit: dict[str, Any], stage: str) -> str:
    if stage.startswith("cv") or stage == "fallback":
        fields = ["ats_cv_text"]
    elif stage.startswith("kit"):
        fields = ["recruiter_message", "cover_letter", "autofill_notes"]
    else:
        fields = ["recruiter_message", "cover_letter", "ats_cv_text", "autofill_notes"]
    return "\n\n".join(
        str(kit.get(field) or "")
        for field in fields
        if str(kit.get(field) or "").strip()
    )


def _materials_prompt_versions_text(
    prompt_versions: dict[str, str],
    metadata: dict[str, Any] | None = None,
) -> str | None:
    values = [f"{key}={value}" for key, value in sorted(prompt_versions.items())]
    metadata = metadata or {}
    for key in ("requested_cv_strategy", "selected_pipeline"):
        value = metadata.get(key)
        if value:
            values.append(f"{key}={value}")
    flags = metadata.get("effective_flags")
    if isinstance(flags, dict):
        for key, value in sorted(flags.items()):
            values.append(f"flag.{key}={int(bool(value))}")
    return ",".join(values) or None


def _process_job_scan(
    operation: dict[str, Any],
) -> None:
    operation_id = int(operation["id"])

    input_payload = {
        **(operation.get("input_json") or {}),
        "operation_id": operation_id,
    }

    scan_started_at = str(
        operation.get("started_at")
        or operation.get("created_at")
        or ""
    )

    logger.info(
        "Processing job scan operation=%s",
        operation_id,
    )

    # Compatibilidad con operaciones creadas
    # antes de separar los workers.
    linkedin_operation_id = None

    if input_payload.get(
        "include_linkedin"
    ):
        active_linkedin = (
            db.get_active_operation(
                "linkedin_scan"
            )
        )

        if active_linkedin:
            linkedin_operation_id = int(
                active_linkedin["id"]
            )
        else:
            linkedin_payload = {
                **input_payload,
                "include_ats": False,
                "include_search": False,
                "include_linkedin": True,
            }

            linkedin_payload.pop(
                "operation_id",
                None,
            )

            linkedin_operation_id = (
                db.create_operation(
                    "linkedin_scan",
                    linkedin_payload,
                    (
                        "Queued LinkedIn scan. "
                        "Waiting for dedicated "
                        "local worker."
                    ),
                )
            )

        input_payload[
            "include_linkedin"
        ] = False

        logger.warning(
            (
                "Moved legacy LinkedIn lane "
                "from job_scan=%s to "
                "linkedin_scan=%s"
            ),
            operation_id,
            linkedin_operation_id,
        )

    def progress(message: str) -> None:
        logger.info(
            (
                "Job scan operation=%s "
                "progress=%s"
            ),
            operation_id,
            message,
        )

        db.update_operation_progress(
            operation_id,
            message,
        )

    output = asyncio.run(
        run_unified_job_scan(
            input_payload,
            progress=progress,
        )
    )

    summary = output.get("summary") or {}

    output[
        "linkedin_operation_id"
    ] = linkedin_operation_id

    output["ranking_job"] = (
        queue_post_scan_ranking(
            input_payload,
            scan_started_at,
            summary,
            progress,
            excluded_sources=[
                "linkedin_scraper"
            ],
        )
    )

    db.complete_operation(
        operation_id,
        output,
        (
            "Job scan completed: "
            f"{summary.get('new', 0)} new, "
            f"{summary.get('updated', 0)} "
            "updated, "
            f"{summary.get('errors', 0)} "
            "errors."
        ),
    )

    logger.info(
        (
            "Completed job scan "
            "operation=%s summary=%s"
        ),
        operation_id,
        summary,
    )


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
    message = "Application execution completed." if not dry_run else "Application dry-run completed."
    db.complete_operation(operation_id, output, message)
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
