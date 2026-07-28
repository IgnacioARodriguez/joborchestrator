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


def _seed_warp_answers(db: object) -> None:
    answers = [
        {
            "canonical_key": "warp_based_in_us_canada",
            "question_patterns": ["If hired by Warp, will you be based in the U.S. or Canada?"],
            "answer_type": "select",
            "value": "No",
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
        {
            "canonical_key": "work_authorization",
            "question_patterns": ["Do you have permanent authorization to work for Warp in the U.S. or Canada?"],
            "answer_type": "select",
            "value": "No",
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
        {
            "canonical_key": "sponsorship",
            "question_patterns": ["Do you require work authorization?"],
            "answer_type": "select",
            "value": "Yes",
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
    ]
    for answer in answers:
        db.upsert_answer_definition(answer)


async def rehearse_application_url(
    url: str,
    *,
    db_path: Path,
    resume_out: Path,
    provider: str,
    headful: bool,
    keep_db: bool,
    warp_answers: bool,
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
    if warp_answers:
        _seed_warp_answers(db)
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
        ats_cv_text=_rehearsal_cv_text(),
    )
    _write_resume_preview(resume_out, db.get_job_posting(job_id), _rehearsal_cv_text())
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
        "blocked": execution.get("blocked"),
        "reason": execution.get("reason"),
        "last_error": updated.get("last_error") if updated else None,
        "resume_upload": execution.get("resume_upload"),
        "resume_preview_path": str(resume_out),
        "resume_preview_lines": [line for line in _rehearsal_cv_text().splitlines() if line.strip()][:8],
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
    parser.add_argument("--resume-out", type=Path, default=PROJECT_ROOT / "logs" / "application-rehearsal-resume.pdf")
    parser.add_argument("--headful", action="store_true", help="Show Chromium while the rehearsal runs.")
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--warp-answers", action="store_true", help="Seed the confirmed Warp work authorization answers.")
    args = parser.parse_args(argv)

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(
        rehearse_application_url(
            args.url,
            db_path=args.db_path,
            resume_out=args.resume_out,
            provider=args.provider,
            headful=args.headful,
            keep_db=args.keep_db,
            warp_answers=args.warp_answers,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _rehearsal_cv_text() -> str:
    return (
        "Professional Summary\nSynthetic backend engineer for automation rehearsal.\n\n"
        "Technical Skills\nPython, FastAPI, Playwright.\n\n"
        "Professional Experience\nBuilt reliable APIs and automation checks.\n\n"
        "Education\nSynthetic degree."
    )


def _write_resume_preview(path: Path, job: dict | None, ats_cv_text: str) -> None:
    from joborchestrator.intelligence.llm_application_materials import export_ats_cv_pdf_bytes

    path.parent.mkdir(parents=True, exist_ok=True)
    content = export_ats_cv_pdf_bytes(job or {"company": "Rehearsal Company", "title": "Rehearsal Role"}, ats_cv_text)
    path.write_bytes(content)


if __name__ == "__main__":
    raise SystemExit(main())
