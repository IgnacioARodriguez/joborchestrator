from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_smoke(db_path: Path, *, keep_db: bool = False) -> dict[str, object]:
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(db_path) + suffix)
        if target.exists():
            target.unlink()

    os.environ["JOB_ORCHESTRATOR_SKIP_ENV_FILE"] = "1"
    os.environ.pop("TURSO_DATABASE_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ["JOB_ORCHESTRATOR_DB_PATH"] = str(db_path)
    os.environ["ENABLE_AUTO_SUBMIT_APPROVED"] = "1"
    os.environ["APPLICATION_BROWSER_HEADLESS"] = "1"
    os.environ["APPLICATION_BROWSER_HANDOFF"] = "0"

    from joborchestrator import worker
    from joborchestrator.scanning.models import JobPosting
    from joborchestrator.scanning.normalization import compute_content_hash
    from joborchestrator.storage import db_connection
    from joborchestrator.storage import persistence as db

    logging.getLogger("joborchestrator.worker").setLevel(logging.WARNING)
    db.init_db()
    db.save_candidate_profile_payload({"full_name": "Synthetic Candidate", "email": "candidate@example.test"})

    html = """
<!doctype html>
<html><body><main data-source="boards.greenhouse.io">
<form id="application_form" onsubmit="window.__submitted = true; event.preventDefault(); document.body.setAttribute('data-submitted', 'true')">
<label for="first_name">Full name *</label><input id="first_name" name="first_name" type="text" required>
<label for="email">Email *</label><input id="email" name="email" type="email" required>
<input id="resume" name="resume" type="file" required>
<button type="submit">Submit application</button>
</form></main></body></html>
"""
    apply_url = f"data:text/html,{quote(html)}"
    job = JobPosting(
        external_id="smoke-auto-submit",
        source="greenhouse",
        company="Synthetic Greenhouse",
        title="Backend Engineer",
        location="Remote",
        apply_url=apply_url,
        url=apply_url,
        description_text="Synthetic local smoke test.",
        content_hash=compute_content_hash(
            "Backend Engineer",
            "Synthetic Greenhouse",
            "Remote",
            "Synthetic local smoke test.",
            apply_url,
        ),
        raw_payload={"fixture": True},
    )
    db.upsert_job_posting(job, seen_at="2026-07-28T11:35:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\nSynthetic backend engineer.\n\n"
            "Technical Skills\nPython, FastAPI.\n\n"
            "Professional Experience\nBuilt reliable APIs.\n\n"
            "Education\nSynthetic degree."
        ),
    )
    session = db.create_application_session({"job_id": job_id, "provider": "greenhouse", "mode": "auto_submit_approved"})
    operation_id = db.create_operation(
        "application_execution",
        {
            "session_id": int(session["id"]),
            "job_id": job_id,
            "apply_url": apply_url,
            "provider": "greenhouse",
            "dry_run": False,
        },
    )
    processed = worker.process_once(worker_id="smoke-auto-submit")
    updated = db.get_application_session(int(session["id"]))
    application = db.get_application(int(updated["application_id"])) if updated and updated.get("application_id") else None
    operation = db.get_operation(operation_id)
    auto_submit = (updated.get("artifacts_json") or {}).get("auto_submit") or {}
    result = {
        "db_mode": db_connection.connection_mode(),
        "db_path": str(db_path),
        "processed": processed,
        "operation_status": operation["status"] if operation else None,
        "session_state": updated["state"] if updated else None,
        "application_status": application["status"] if application else None,
        "auto_submit_status": auto_submit.get("status"),
        "auto_submit_reasons": auto_submit.get("reasons"),
        "control_text": auto_submit.get("control_text"),
    }
    expected = {
        "db_mode": "sqlite",
        "processed": True,
        "operation_status": "completed",
        "session_state": "submit_only",
        "application_status": "preparing",
        "auto_submit_status": "blocked",
        "auto_submit_reasons": ["final_submit_reserved_for_user"],
    }
    problems = [f"{key}={result.get(key)!r}" for key, value in expected.items() if result.get(key) != value]
    if not keep_db:
        for suffix in ("", "-wal", "-shm"):
            target = Path(str(db_path) + suffix)
            if target.exists():
                target.unlink()
    if problems:
        raise RuntimeError(f"Auto-submit smoke failed: {', '.join(problems)}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an isolated Greenhouse auto-submit smoke test.")
    parser.add_argument("--db-path", type=Path, default=PROJECT_ROOT / "logs" / "auto-submit-smoke.db")
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args(argv)

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_smoke(args.db_path, keep_db=args.keep_db)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
