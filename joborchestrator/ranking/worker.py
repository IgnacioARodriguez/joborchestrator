from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import time

from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
    NvidiaRankingError,
    rank_jobs_with_nvidia,
)
from joborchestrator.storage import persistence as db

DEFAULT_WORKER_CHUNK_SIZE = int(os.getenv("RANKING_WORKER_CHUNK_SIZE", "25"))
DEFAULT_POLL_SECONDS = float(os.getenv("RANKING_WORKER_POLL_SECONDS", "5"))
DEFAULT_STALE_SECONDS = int(os.getenv("RANKING_WORKER_STALE_SECONDS", "60"))
LOG_PATH = Path("logs/ranking-worker.log")

logger = logging.getLogger("joborchestrator.ranking.worker")


def configure_logging(log_path: Path = LOG_PATH) -> None:
    if logging.getLogger().handlers:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])


def run_worker(
    *,
    ranking_job_id: int | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    chunk_size: int = DEFAULT_WORKER_CHUNK_SIZE,
    once: bool = False,
) -> None:
    logger.info(
        "Starting NVIDIA ranking worker job_id=%s chunk_size=%s poll_seconds=%s stale_seconds=%s once=%s",
        ranking_job_id or "any",
        chunk_size,
        poll_seconds,
        DEFAULT_STALE_SECONDS,
        once,
    )
    while True:
        processed_any = run_worker_once(ranking_job_id=ranking_job_id, chunk_size=chunk_size)
        if once:
            logger.info("Ranking worker one-shot finished processed_any=%s", processed_any)
            return
        if not processed_any:
            time.sleep(poll_seconds)


def run_worker_once(*, ranking_job_id: int | None = None, chunk_size: int = DEFAULT_WORKER_CHUNK_SIZE) -> bool:
    job = db.get_ranking_job(ranking_job_id) if ranking_job_id is not None else db.get_next_ranking_job()
    if not job or job["status"] not in {"queued", "running"}:
        logger.debug("No queued/running NVIDIA ranking job found job_id=%s", ranking_job_id or "any")
        return False

    if job["provider"] != "nvidia":
        logger.error("Unsupported ranking provider job_id=%s provider=%s", job["id"], job["provider"])
        db.fail_ranking_job(int(job["id"]), f"Unsupported ranking provider: {job['provider']}")
        return True

    job_id = int(job["id"])
    logger.info("Claiming ranking job #%s status=%s", job_id, job["status"])
    db.start_ranking_job(job_id)
    current_job = db.get_ranking_job(job_id)
    if current_job is None or current_job["status"] != "running":
        logger.info("Ranking job #%s was not claimable after start attempt", job_id)
        return True

    db.requeue_stale_ranking_items(job_id, stale_seconds=DEFAULT_STALE_SECONDS)
    rows = db.get_queued_ranking_items(job_id, limit=max(1, int(chunk_size)))
    if rows.empty:
        logger.info("Ranking job #%s has no queued items; checking completion", job_id)
        db.complete_ranking_job_if_done(job_id)
        return True

    item_job_ids = [int(row_id) for row_id in rows["id"].tolist()]
    request_batch_size = min(int(job["request_batch_size"]), DEFAULT_NVIDIA_REQUEST_BATCH_SIZE)
    max_concurrency = min(int(job["max_concurrency"]), DEFAULT_NVIDIA_MAX_CONCURRENCY)
    logger.info(
        "Processing ranking job #%s chunk_items=%s model=%s request_batch_size=%s max_concurrency=%s stored_request_batch_size=%s stored_max_concurrency=%s",
        job_id,
        len(item_job_ids),
        job["model"],
        request_batch_size,
        max_concurrency,
        job["request_batch_size"],
        job["max_concurrency"],
    )
    db.mark_ranking_items_running(job_id, item_job_ids)

    try:
        summary = rank_jobs_with_nvidia(
            rows,
            model=str(job["model"]),
            request_batch_size=request_batch_size,
            max_concurrency=max_concurrency,
            ranking_version=str(job["ranking_version"]),
            progress_callback=lambda completed, total, progress: logger.info(
                "Ranking job #%s NVIDIA batches %s/%s progress=%s",
                job_id,
                completed,
                total,
                progress,
            ),
        )
        logger.info("NVIDIA ranking job #%s chunk summary=%s", job_id, summary)
        missing_error = (
            "NVIDIA did not return a valid ranking for this job. "
            "Try rerunning with a smaller batch size if this repeats."
            if summary.get("failed", 0)
            else "NVIDIA did not save a ranking for this job."
        )
        db.sync_ranking_items_from_rankings(job_id, str(job["ranking_version"]), item_job_ids, missing_error)
        db.complete_ranking_job_if_done(job_id)
    except NvidiaRankingError as exc:
        logger.exception("NVIDIA ranking job #%s failed", job_id)
        db.fail_ranking_job(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - keep background worker from crashing silently.
        logger.exception("Unexpected ranking worker error job_id=%s", job_id)
        db.fail_ranking_job(job_id, f"Unexpected worker error: {exc}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run queued NVIDIA ranking jobs.")
    parser.add_argument("--job-id", type=int, default=None, help="Process only this ranking job id.")
    parser.add_argument("--once", action="store_true", help="Process one worker chunk and exit.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_WORKER_CHUNK_SIZE)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)
    configure_logging()
    run_worker(
        ranking_job_id=args.job_id,
        poll_seconds=args.poll_seconds,
        chunk_size=args.chunk_size,
        once=args.once,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
