from __future__ import annotations

import argparse
import os
import socket
from typing import Any, Callable

from joborchestrator.linkedin_worker import _process_linkedin_scan
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.ranking.worker import run_worker_once as run_ranking_worker_once
from joborchestrator.storage import persistence as db
from joborchestrator.api_dto import latest_rankings_by_job_id
from joborchestrator.intelligence.materials_routing import should_auto_generate_materials
from joborchestrator.worker import _process_job_scan
from joborchestrator.worker import (
    _process_application_materials_generation,
)


def _profile_queries(profile: dict[str, Any]) -> list[str]:
    roles = [
        *list(profile.get("target_roles") or []),
        *list(profile.get("secondary_roles") or []),
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for role in roles:
        value = str(role or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            queries.append(value)
    return queries[:8]


def _profile_location(profile: dict[str, Any]) -> str:
    locations = [str(value).strip() for value in profile.get("preferred_locations") or [] if str(value).strip()]
    return locations[0] if locations else "Spain"


def _profile_remote(profile: dict[str, Any]) -> bool:
    modes = {str(value or "").strip().casefold() for value in profile.get("preferred_work_modes") or []}
    return not modes or bool(modes & {"remote", "remoto", "hybrid", "híbrido", "hibrido"})


def _queue_operation(operation_type: str, payload: dict[str, Any], message: str) -> tuple[int, bool]:
    stale_seconds = int(
        os.getenv(
            "JOB_SCAN_ACTIVE_STALE_SECONDS",
            os.getenv("JOB_WORKER_STALE_SECONDS", "3600"),
        )
    )
    db.requeue_stale_operations([operation_type], stale_seconds=stale_seconds)
    active = db.get_active_operation(operation_type)
    if active:
        operation_id = int(active["id"])
        print(
            f"Using existing {operation_type} operation id={operation_id} "
            f"status={active['status']}."
        )
        return operation_id, False
    operation_id = db.create_operation(operation_type, payload, message)
    print(f"Queued {operation_type} operation id={operation_id}.")
    return operation_id, True


def _process_scoped_operation(
    operation_type: str,
    processor: Callable[[dict[str, Any]], None],
) -> bool:
    worker_id = f"github-actions:{socket.gethostname()}:{os.getpid()}:{operation_type}"
    operation = db.claim_next_operation(worker_id, [operation_type])
    if not operation:
        print(f"No queued {operation_type} operation available to claim.")
        return False
    operation_id = int(operation["id"])
    try:
        processor(operation)
    except Exception as exc:
        db.fail_operation(
            operation_id,
            str(exc),
            f"GitHub Actions {operation_type} execution failed. Check workflow logs.",
        )
        raise
    return True


def run_public_scan(args: argparse.Namespace) -> int:
    db.init_db()
    profile = db.get_candidate_profile_payload() or {}
    queries = _profile_queries(profile)
    payload = {
        "include_ats": True,
        "include_search": bool(queries),
        "include_linkedin": False,
        "source_ids": None,
        "search_providers": [],
        "queries": queries,
        "application_targets": list(profile.get("application_targets") or []),
        "location": _profile_location(profile),
        "remote": _profile_remote(profile),
        "max_pages": args.max_pages,
        "ats_max_concurrency": args.ats_max_concurrency,
        "search_max_concurrency": args.search_max_concurrency,
        "auto_rank_new": True,
        "ranking_limit": args.ranking_limit,
        "ranking_version": NVIDIA_RANKING_VERSION,
        "ranking_model": DEFAULT_NVIDIA_MODEL,
    }
    _queue_operation(
        "job_scan",
        payload,
        "Queued scheduled ATS and public search scan from GitHub Actions.",
    )
    _process_scoped_operation("job_scan", _process_job_scan)
    return 0


def run_linkedin_scan(args: argparse.Namespace) -> int:
    db.init_db()
    profile = db.get_candidate_profile_payload() or {}
    payload = {
        "include_ats": False,
        "include_search": False,
        "include_linkedin": True,
        "linkedin_limit": args.limit,
        "linkedin_resume_from_checkpoint": args.resume_from_checkpoint,
        "application_targets": list(profile.get("application_targets") or []),
        "location": _profile_location(profile),
        "remote": _profile_remote(profile),
        "auto_rank_new": True,
        "ranking_limit": args.ranking_limit,
        "ranking_version": NVIDIA_RANKING_VERSION,
        "ranking_model": DEFAULT_NVIDIA_MODEL,
    }
    _queue_operation(
        "linkedin_scan",
        payload,
        "Queued scheduled LinkedIn scan from GitHub Actions.",
    )
    _process_scoped_operation("linkedin_scan", _process_linkedin_scan)
    return 0


def _queue_unranked_jobs(args: argparse.Namespace) -> int | None:
    active = db.get_next_ranking_job()
    if active:
        print(f"Using existing ranking job id={active['id']} status={active['status']}.")
        return int(active["id"])

    unranked = db.get_unranked_jobs(
        ranking_version=args.ranking_version,
        limit=args.limit,
    )
    job_ids = [int(value) for value in unranked["id"].tolist()]
    if not job_ids:
        print("No unranked jobs found.")
        return None

    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model=args.model,
        ranking_version=args.ranking_version,
        job_ids=job_ids,
        request_batch_size=args.request_batch_size,
        max_concurrency=args.max_concurrency,
    )
    print(f"Queued ranking job id={ranking_job_id} items={len(job_ids)}.")
    return int(ranking_job_id)


def run_rankings(args: argparse.Namespace) -> int:
    db.init_db()
    if not db.get_candidate_profile_payload():
        raise RuntimeError("No candidate profile configured; rankings cannot run.")

    if args.queue_unranked:
        _queue_unranked_jobs(args)

    processed_chunks = 0
    while processed_chunks < args.max_chunks:
        processed = run_ranking_worker_once(chunk_size=args.chunk_size)
        if not processed:
            break
        processed_chunks += 1

    remaining = db.get_next_ranking_job()
    print(
        f"Ranking drain finished chunks={processed_chunks} "
        f"remaining_job_id={remaining['id'] if remaining else None}."
    )
    if remaining and processed_chunks >= args.max_chunks:
        raise RuntimeError(
            "Ranking work remains after reaching --max-chunks. "
            "Increase the limit or let the next scheduled workflow continue it."
        )
    return 0


def run_materials(args: argparse.Namespace) -> int:
    """Drain queued material-generation operations on a hosted runner."""
    db.init_db()
    processed = 0
    while processed < args.max_operations:
        worker_id = f"github-actions:materials:{os.getpid()}"
        operation = db.claim_next_operation(
            worker_id,
            ["application_materials_generation"],
        )
        if not operation:
            break
        operation_id = int(operation["id"])
        job_id = int((operation.get("input_json") or {}).get("job_id") or 0)
        ranking = latest_rankings_by_job_id().get(job_id)
        if not should_auto_generate_materials(ranking):
            db.complete_operation(
                operation_id,
                {"skipped": True, "reason": "ranking_decision_not_apply_now", "job_id": job_id},
                "Materials skipped: ranking decision is not APPLY_NOW.",
            )
            processed += 1
            continue
        try:
            _process_application_materials_generation(operation)
        except Exception as exc:
            db.fail_operation(
                operation_id,
                str(exc),
                "GitHub Actions materials execution failed. Check workflow logs.",
            )
            raise
        processed += 1
    print(f"Materials drain finished operations={processed}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Queue and execute Job Orchestrator scheduled workloads."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    public = subparsers.add_parser("public-scan", help="Run ATS and public search scans.")
    public.add_argument("--max-pages", type=int, default=1)
    public.add_argument("--ats-max-concurrency", type=int, default=6)
    public.add_argument("--search-max-concurrency", type=int, default=4)
    public.add_argument("--ranking-limit", type=int, default=250)
    public.set_defaults(handler=run_public_scan)

    linkedin = subparsers.add_parser("linkedin-scan", help="Run the dedicated LinkedIn scan.")
    linkedin.add_argument("--limit", type=int, default=75)
    linkedin.add_argument("--resume-from-checkpoint", action="store_true")
    linkedin.add_argument("--ranking-limit", type=int, default=250)
    linkedin.set_defaults(handler=run_linkedin_scan)

    rankings = subparsers.add_parser("rankings", help="Queue missing rankings and drain ranking jobs.")
    rankings.add_argument("--limit", type=int, default=250)
    rankings.add_argument("--chunk-size", type=int, default=25)
    rankings.add_argument("--max-chunks", type=int, default=100)
    rankings.add_argument("--model", default=DEFAULT_NVIDIA_MODEL)
    rankings.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    rankings.add_argument("--request-batch-size", type=int, default=DEFAULT_NVIDIA_REQUEST_BATCH_SIZE)
    rankings.add_argument("--max-concurrency", type=int, default=DEFAULT_NVIDIA_MAX_CONCURRENCY)
    rankings.add_argument(
        "--queue-unranked",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    rankings.set_defaults(handler=run_rankings)

    materials = subparsers.add_parser(
        "materials",
        help="Drain queued application-material generation operations.",
    )
    materials.add_argument("--max-operations", type=int, default=25)
    materials.set_defaults(handler=run_materials)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
