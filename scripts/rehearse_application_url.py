from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _prepare_environment(db_path: Path, *, headful: bool) -> None:
    os.environ["JOB_ORCHESTRATOR_SKIP_ENV_FILE"] = "1"
    os.environ.pop("TURSO_DATABASE_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ["JOB_ORCHESTRATOR_DB_PATH"] = str(db_path)
    os.environ["ENABLE_AUTO_SUBMIT_APPROVED"] = "0"
    os.environ["APPLICATION_BROWSER_HEADLESS"] = "0" if headful else "1"
    os.environ["APPLICATION_BROWSER_HANDOFF"] = "0"


def _remove_db(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(db_path) + suffix)
        if target.exists():
            target.unlink()


async def rehearse_application_url(
    url: str,
    *,
    db_path: Path,
    provider: str,
    headful: bool,
    keep_db: bool,
) -> dict[str, object]:
    _remove_db(db_path)
    _prepare_environment(db_path, headful=headful)

    from joborchestrator.automation.executor import run_application_execution
    from joborchestrator.scanning.models import JobPosting
    from joborchestrator.scanning.normalization import compute_content_hash
    from joborchestrator.storage import db_connection
    from joborchestrator.storage import persistence as db

    db.init_db()
    db.save_candidate_profile_payload(
        {
            "full_name": "Synthetic Candidate",
            "email": "candidate@example.test",
            "phone": "+34 000 000 000",
            "linkedin_url": "https://www.linkedin.com/in/synthetic-candidate",
            "portfolio_url": "https://example.test",
        }
    )
    job = JobPosting(
        external_id="rehearsal-application",
        source=provider,
        company="Rehearsal Company",
        title="Rehearsal Role",
        location="Remote",
        apply_url=url,
        url=url,
        description_text="Synthetic rehearsal job. This should never be submitted.",
        content_hash=compute_content_hash(
            "Rehearsal Role",
            "Rehearsal Company",
            "Remote",
            "Synthetic rehearsal job. This should never be submitted.",
            url,
        ),
        raw_payload={"rehearsal": True},
    )
    db.upsert_job_posting(job, seen_at="2026-07-28T12:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\nSynthetic backend engineer for automation rehearsal.\n\n"
            "Technical Skills\nPython, FastAPI, Playwright.\n\n"
            "Professional Experience\nBuilt reliable APIs and automation checks.\n\n"
            "Education\nSynthetic degree."
        ),
    )
    session = db.create_application_session({"job_id": job_id, "provider": provider, "mode": "review_before_submit"})
    execution = await run_application_execution(
        session_id=int(session["id"]),
        job_id=job_id,
        apply_url=url,
        provider_hint=provider,
        dry_run=True,
    )
    updated = db.get_application_session(int(session["id"]))
    artifacts = updated.get("artifacts_json") if updated else {}
    review = (artifacts or {}).get("review") or {}
    result = {
        "db_mode": db_connection.connection_mode(),
        "db_path": str(db_path),
        "provider": execution.get("provider"),
        "session_state": updated.get("state") if updated else None,
        "fields_detected": execution.get("fields_detected"),
        "fields_autofilled": execution.get("fields_autofilled"),
        "unknown_fields": execution.get("unknown_fields"),
        "unknown_field_labels": [
            str(field.get("label") or field.get("name") or "")
            for field in review.get("unknown_fields") or []
            if isinstance(field, dict)
        ],
        "resume_upload": execution.get("resume_upload"),
        "forbidden_submit_controls": execution.get("forbidden_submit_controls"),
        "auto_submit": execution.get("auto_submit"),
        "final_url": (artifacts or {}).get("final_url"),
    }
    if not keep_db:
        _remove_db(db_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe review-before-submit rehearsal against an application URL.")
    parser.add_argument("url", help="Application URL to rehearse. No final submit is clicked.")
    parser.add_argument("--provider", default="greenhouse")
    parser.add_argument("--db-path", type=Path, default=PROJECT_ROOT / "logs" / "application-rehearsal.db")
    parser.add_argument("--headful", action="store_true", help="Show Chromium while the rehearsal runs.")
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args(argv)

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(
        rehearse_application_url(
            args.url,
            db_path=args.db_path,
            provider=args.provider,
            headful=args.headful,
            keep_db=args.keep_db,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
