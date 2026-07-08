from __future__ import annotations

import argparse
import os
import time

from joborchestrator.ranking.nvidia_ranker import NvidiaRankingError, rank_jobs_with_nvidia
from joborchestrator.storage import persistence as db

DEFAULT_WORKER_CHUNK_SIZE = int(os.getenv("RANKING_WORKER_CHUNK_SIZE", "100"))
DEFAULT_POLL_SECONDS = float(os.getenv("RANKING_WORKER_POLL_SECONDS", "5"))


def run_worker(
    *,
    ranking_job_id: int | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    chunk_size: int = DEFAULT_WORKER_CHUNK_SIZE,
    once: bool = False,
) -> None:
    while True:
        processed_any = run_worker_once(ranking_job_id=ranking_job_id, chunk_size=chunk_size)
        if once:
            return
        if not processed_any:
            time.sleep(poll_seconds)


def run_worker_once(*, ranking_job_id: int | None = None, chunk_size: int = DEFAULT_WORKER_CHUNK_SIZE) -> bool:
    job = db.get_ranking_job(ranking_job_id) if ranking_job_id is not None else db.get_next_ranking_job()
    if not job or job["status"] not in {"queued", "running"}:
        return False

    if job["provider"] != "nvidia":
        db.fail_ranking_job(int(job["id"]), f"Unsupported ranking provider: {job['provider']}")
        return True

    job_id = int(job["id"])
    db.start_ranking_job(job_id)
    current_job = db.get_ranking_job(job_id)
    if current_job is None or current_job["status"] != "running":
        return True

    rows = db.get_queued_ranking_items(job_id, limit=max(1, int(chunk_size)))
    if rows.empty:
        db.complete_ranking_job_if_done(job_id)
        return True

    item_job_ids = [int(row_id) for row_id in rows["id"].tolist()]
    db.mark_ranking_items_running(job_id, item_job_ids)

    try:
        rank_jobs_with_nvidia(
            rows,
            model=str(job["model"]),
            request_batch_size=int(job["request_batch_size"]),
            max_concurrency=int(job["max_concurrency"]),
            ranking_version=str(job["ranking_version"]),
            progress_callback=lambda *_args: None,
        )
        db.sync_ranking_items_from_rankings(job_id, str(job["ranking_version"]), item_job_ids)
        db.complete_ranking_job_if_done(job_id)
    except NvidiaRankingError as exc:
        db.fail_ranking_job(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - keep background worker from crashing silently.
        db.fail_ranking_job(job_id, f"Unexpected worker error: {exc}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run queued NVIDIA ranking jobs.")
    parser.add_argument("--job-id", type=int, default=None, help="Process only this ranking job id.")
    parser.add_argument("--once", action="store_true", help="Process one worker chunk and exit.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_WORKER_CHUNK_SIZE)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)
    run_worker(
        ranking_job_id=args.job_id,
        poll_seconds=args.poll_seconds,
        chunk_size=args.chunk_size,
        once=args.once,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
