from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

from joborchestrator.intelligence.cv_profile_extractor import CVProfileError, build_profile_from_cv_text
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
    operation = db.claim_next_operation(worker_id, ["cv_profile_import"])
    if not operation:
        return False
    operation_id = int(operation["id"])
    operation_type = str(operation["type"])
    logger.info("Claimed operation id=%s type=%s", operation_id, operation_type)
    try:
        if operation_type == "cv_profile_import":
            _process_cv_profile_import(operation)
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
