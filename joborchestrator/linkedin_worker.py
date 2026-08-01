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

from joborchestrator.scanning.orchestrator import (
    run_unified_job_scan,
)
from joborchestrator.scanning.post_scan_ranking import (
    queue_post_scan_ranking,
)
from joborchestrator.storage import (
    persistence as db,
)

WORKER_ID = (
    f"{socket.gethostname()}:"
    f"{os.getpid()}:linkedin"
)

DEFAULT_POLL_SECONDS = float(
    os.getenv(
        "LINKEDIN_WORKER_POLL_SECONDS",
        "5",
    )
)

DEFAULT_STALE_SECONDS = int(
    os.getenv(
        "LINKEDIN_WORKER_STALE_SECONDS",
        os.getenv(
            "JOB_WORKER_STALE_SECONDS",
            "3600",
        ),
    )
)

OPERATION_TYPES = [
    "linkedin_scan",
]


def configure_logging() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(
        "joborchestrator.linkedin_worker"
    )

    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s "
        "%(message)s"
    )

    stream = logging.StreamHandler(
        sys.stdout
    )
    stream.setFormatter(formatter)

    file_handler = logging.FileHandler(
        log_dir / "linkedin_worker.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(stream)
    logger.addHandler(file_handler)

    return logger


logger = configure_logging()


def process_once(
    worker_id: str = WORKER_ID,
) -> bool:
    requeued = (
        db.requeue_stale_operations(
            OPERATION_TYPES,
            stale_seconds=(
                DEFAULT_STALE_SECONDS
            ),
        )
    )

    if requeued:
        logger.warning(
            (
                "Requeued stale LinkedIn "
                "operations count=%s "
                "stale_seconds=%s"
            ),
            requeued,
            DEFAULT_STALE_SECONDS,
        )

    operation = db.claim_next_operation(
        worker_id,
        OPERATION_TYPES,
    )

    if not operation:
        return False

    operation_id = int(operation["id"])

    logger.info(
        "Claimed LinkedIn operation id=%s",
        operation_id,
    )

    try:
        _process_linkedin_scan(operation)
    except Exception as exc:
        logger.exception(
            "LinkedIn operation failed id=%s",
            operation_id,
        )

        db.fail_operation(
            operation_id,
            str(exc),
            (
                "LinkedIn worker failed. "
                "Check local logs."
            ),
        )

    return True


def run_poll_loop(
    poll_seconds: float = (
        DEFAULT_POLL_SECONDS
    ),
) -> None:
    logger.info(
        (
            "LinkedIn worker started "
            "id=%s poll_seconds=%s"
        ),
        WORKER_ID,
        poll_seconds,
    )

    db.init_db()

    while True:
        processed = process_once()

        if not processed:
            time.sleep(poll_seconds)


def _process_linkedin_scan(
    operation: dict[str, Any],
) -> None:
    operation_id = int(operation["id"])

    input_payload = {
        **(operation.get("input_json") or {}),
        "operation_id": operation_id,
        "include_ats": False,
        "include_search": False,
        "include_linkedin": True,
    }

    scan_started_at = str(
        operation.get("started_at")
        or operation.get("created_at")
        or ""
    )

    logger.info(
        (
            "Processing LinkedIn scan "
            "operation=%s"
        ),
        operation_id,
    )

    def progress(message: str) -> None:
        logger.info(
            (
                "LinkedIn scan operation=%s "
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

    linkedin_error = (output.get("errors") or {}).get("linkedin")
    if linkedin_error:
        raise RuntimeError(f"LinkedIn scan failed: {linkedin_error}")

    output["ranking_job"] = (
        queue_post_scan_ranking(
            input_payload,
            scan_started_at,
            summary,
            progress,
            included_sources=[
                "linkedin_scraper"
            ],
        )
    )

    db.complete_operation(
        operation_id,
        output,
        (
            "LinkedIn scan completed: "
            f"{summary.get('new', 0)} new, "
            f"{summary.get('updated', 0)} "
            "updated, "
            f"{summary.get('errors', 0)} "
            "errors."
        ),
    )

    logger.info(
        (
            "Completed LinkedIn scan "
            "operation=%s summary=%s"
        ),
        operation_id,
        summary,
    )


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the dedicated Job "
            "Orchestrator LinkedIn worker."
        )
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Process one queued LinkedIn "
            "operation and exit."
        ),
    )

    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=DEFAULT_POLL_SECONDS,
    )

    args = parser.parse_args(argv)

    if args.once:
        db.init_db()
        processed = process_once()

        logger.info(
            (
                "LinkedIn worker once "
                "finished processed=%s"
            ),
            processed,
        )

        return 0

    run_poll_loop(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
