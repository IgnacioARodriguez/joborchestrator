from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SYNTHETIC_PROFILE = {
    "full_name": "Synthetic Candidate",
    "email": "candidate@example.test",
    "phone": "+34 000 000 000",
    "linkedin_url": "https://www.linkedin.com/in/synthetic-candidate",
    "portfolio_url": "https://example.test",
}


def _prepare_environment(db_path: Path, *, headful: bool, timeout_ms: int) -> None:
    os.environ["JOB_ORCHESTRATOR_SKIP_ENV_FILE"] = "1"
    os.environ.pop("TURSO_DATABASE_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ["JOB_ORCHESTRATOR_DB_PATH"] = str(db_path)
    os.environ["ENABLE_AUTO_SUBMIT_APPROVED"] = "0"
    os.environ["APPLICATION_BROWSER_HEADLESS"] = "0" if headful else "1"
    os.environ["APPLICATION_BROWSER_HANDOFF"] = "0"
    os.environ["APPLICATION_BROWSER_TIMEOUT_MS"] = str(timeout_ms)


def _remove_db(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(db_path) + suffix)
        if target.exists():
            target.unlink()


def read_urls(*, urls: list[str], urls_file: Path | None, limit: int | None) -> list[str]:
    collected: list[str] = []
    collected.extend(url.strip() for url in urls if url.strip())
    if urls_file:
        for line in urls_file.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                collected.append(value)
    deduped = list(dict.fromkeys(collected))
    if limit is not None:
        return deduped[:limit]
    return deduped


async def audit_application_url(url: str, *, provider: str, index: int) -> dict[str, object]:
    from joborchestrator.automation.executor import run_application_execution
    from joborchestrator.scanning.models import JobPosting
    from joborchestrator.scanning.normalization import compute_content_hash
    from joborchestrator.storage import persistence as db

    started = time.monotonic()
    external_id = f"coverage-audit-{index}"
    job = JobPosting(
        external_id=external_id,
        source=provider,
        company="Coverage Audit Company",
        title="Coverage Audit Role",
        location="Remote",
        apply_url=url,
        url=url,
        description_text="Synthetic coverage audit job. This should never be submitted.",
        content_hash=compute_content_hash(
            "Coverage Audit Role",
            "Coverage Audit Company",
            "Remote",
            "Synthetic coverage audit job. This should never be submitted.",
            url,
        ),
        raw_payload={"coverage_audit": True, "index": index},
    )
    db.upsert_job_posting(job, seen_at="2026-07-28T12:00:00")
    jobs = db.get_job_postings(limit=None)
    matching_jobs = jobs[jobs["external_id"] == external_id]
    if matching_jobs.empty:
        raise RuntimeError(f"Could not reload coverage audit job {external_id}.")
    job_id = int(matching_jobs.iloc[0]["id"])
    db.update_job_application_materials(job_id, ats_cv_text=_synthetic_cv_text())
    session = db.create_application_session({"job_id": job_id, "provider": provider, "mode": "review_before_submit"})

    try:
        execution = await run_application_execution(
            session_id=int(session["id"]),
            job_id=job_id,
            apply_url=url,
            provider_hint=provider,
            dry_run=True,
        )
        updated = db.get_application_session(int(session["id"])) or {}
        artifacts = updated.get("artifacts_json") or {}
        review = artifacts.get("review") or {}
        unknown_fields = [
            str(field.get("label") or field.get("name") or "").strip()
            for field in review.get("unknown_fields") or []
            if isinstance(field, dict)
        ]
        submit_controls = execution.get("forbidden_submit_controls") or []
        fields_detected = int(execution.get("fields_detected") or 0)
        unknown_count = int(execution.get("unknown_fields") or len(unknown_fields))
        state = str(updated.get("state") or "")
        reason = str(execution.get("reason") or "")
        score = coverage_score(
            state=state,
            reason=reason,
            fields_detected=fields_detected,
            fields_autofilled=int(execution.get("fields_autofilled") or 0),
            unknown_fields=unknown_count,
            submit_controls_count=len(submit_controls),
            blocked=bool(execution.get("blocked")),
        )
        return {
            "url": url,
            "provider_hint": provider,
            "provider_detected": execution.get("provider"),
            "state": state,
            "coverage_score": score,
            "fields_detected": fields_detected,
            "fields_autofilled": execution.get("fields_autofilled"),
            "unknown_fields": unknown_count,
            "unknown_field_labels": unknown_fields,
            "resume_upload_status": (execution.get("resume_upload") or {}).get("status"),
            "submit_controls_count": len(submit_controls),
            "submit_control_texts": [str(control.get("text") or "") for control in submit_controls if isinstance(control, dict)],
            "auto_submit_status": (execution.get("auto_submit") or {}).get("status"),
            "blocked": bool(execution.get("blocked")),
            "reason": reason or None,
            "last_error": updated.get("last_error"),
            "final_url": artifacts.get("final_url"),
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    except Exception as exc:
        return {
            "url": url,
            "provider_hint": provider,
            "provider_detected": None,
            "state": "failed",
            "coverage_score": "failed",
            "fields_detected": 0,
            "fields_autofilled": 0,
            "unknown_fields": 0,
            "unknown_field_labels": [],
            "resume_upload_status": None,
            "submit_controls_count": 0,
            "submit_control_texts": [],
            "auto_submit_status": None,
            "blocked": True,
            "reason": exc.__class__.__name__,
            "last_error": str(exc),
            "final_url": None,
            "duration_seconds": round(time.monotonic() - started, 2),
        }


def coverage_score(
    *,
    state: str,
    reason: str = "",
    fields_detected: int,
    fields_autofilled: int,
    unknown_fields: int,
    submit_controls_count: int,
    blocked: bool,
) -> str:
    if reason == "posting_unavailable":
        return "posting_unavailable"
    if blocked or state == "failed":
        return "blocked"
    if fields_detected == 0:
        return "no_form_detected"
    if unknown_fields == 0 and submit_controls_count == 1:
        return "ready_no_human_input"
    if fields_autofilled > 0:
        return "partial_needs_answers"
    return "manual"


async def audit_application_coverage(
    urls: list[str],
    *,
    db_path: Path,
    provider: str,
    answers_file: Path | None,
    headful: bool,
    timeout_ms: int,
    keep_db: bool,
) -> dict[str, object]:
    _remove_db(db_path)
    _prepare_environment(db_path, headful=headful, timeout_ms=timeout_ms)

    from joborchestrator.storage import db_connection
    from joborchestrator.storage import persistence as db

    db.init_db()
    db.save_candidate_profile_payload(SYNTHETIC_PROFILE)
    if answers_file:
        for answer in json.loads(answers_file.read_text(encoding="utf-8")):
            if isinstance(answer, dict):
                db.upsert_answer_definition(answer)

    results: list[dict[str, object]] = []
    for index, url in enumerate(urls, start=1):
        results.append(await audit_application_url(url, provider=provider, index=index))

    summary = summarize_results(results)
    report = {
        "db_mode": db_connection.connection_mode(),
        "db_path": str(db_path),
        "dry_run": True,
        "auto_submit_enabled": False,
        "urls_requested": len(urls),
        "summary": summary,
        "results": results,
    }
    if not keep_db:
        _remove_db(db_path)
    return report


def summarize_results(results: list[dict[str, object]]) -> dict[str, object]:
    by_score: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    for result in results:
        score = str(result.get("coverage_score") or "unknown")
        provider = str(result.get("provider_detected") or result.get("provider_hint") or "unknown")
        by_score[score] = by_score.get(score, 0) + 1
        by_provider[provider] = by_provider.get(provider, 0) + 1
    total = len(results)
    low_friction = by_score.get("ready_no_human_input", 0)
    return {
        "total": total,
        "low_friction_count": low_friction,
        "low_friction_ratio": round(low_friction / total, 3) if total else 0,
        "by_score": by_score,
        "by_provider": by_provider,
    }


def write_json_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def write_csv_report(path: Path, results: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "url",
        "provider_detected",
        "state",
        "coverage_score",
        "fields_detected",
        "fields_autofilled",
        "unknown_fields",
        "resume_upload_status",
        "submit_controls_count",
        "reason",
        "last_error",
        "final_url",
        "duration_seconds",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for result in results:
            writer.writerow({column: result.get(column) for column in columns})


def write_markdown_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    assert isinstance(summary, dict)
    lines = [
        "# Application Automation Coverage Audit",
        "",
        f"- Dry run: `{report['dry_run']}`",
        f"- Auto submit enabled: `{report['auto_submit_enabled']}`",
        f"- URLs: `{summary.get('total')}`",
        f"- Low-friction ready: `{summary.get('low_friction_count')}` (`{summary.get('low_friction_ratio')}`)",
        f"- By score: `{json.dumps(summary.get('by_score'), sort_keys=True)}`",
        f"- By provider: `{json.dumps(summary.get('by_provider'), sort_keys=True)}`",
        "",
        "| URL | Provider | State | Score | Fields | Filled | Unknown | Resume | Submit controls |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for result in report["results"]:
        assert isinstance(result, dict)
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(str(result.get("url") or "")),
                    _md_cell(str(result.get("provider_detected") or "")),
                    _md_cell(str(result.get("state") or "")),
                    _md_cell(str(result.get("coverage_score") or "")),
                    str(result.get("fields_detected") or 0),
                    str(result.get("fields_autofilled") or 0),
                    str(result.get("unknown_fields") or 0),
                    _md_cell(str(result.get("resume_upload_status") or "")),
                    str(result.get("submit_controls_count") or 0),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:180]


def _synthetic_cv_text() -> str:
    return (
        "Professional Summary\nSynthetic backend engineer for automation coverage audit.\n\n"
        "Technical Skills\nPython, FastAPI, Playwright, SQL.\n\n"
        "Professional Experience\nBuilt reliable APIs and automation checks.\n\n"
        "Education\nSynthetic degree."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit application automation coverage across URLs without submitting.")
    parser.add_argument("--url", action="append", default=[], help="Application URL to audit. Can be provided more than once.")
    parser.add_argument("--urls-file", type=Path, help="Text file with one application URL per line.")
    parser.add_argument("--provider", default="generic", help="Provider hint passed to the automation registry.")
    parser.add_argument("--answers-file", type=Path, help="JSON file with approved answer definitions to seed into the isolated audit DB.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--db-path", type=Path, default=PROJECT_ROOT / "logs" / "application-coverage-audit.db")
    parser.add_argument("--json-out", type=Path, default=PROJECT_ROOT / "logs" / "application-coverage-audit.json")
    parser.add_argument("--csv-out", type=Path, default=PROJECT_ROOT / "logs" / "application-coverage-audit.csv")
    parser.add_argument("--md-out", type=Path, default=PROJECT_ROOT / "logs" / "application-coverage-audit.md")
    parser.add_argument("--headful", action="store_true", help="Show Chromium while the audit runs.")
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args(argv)

    urls = read_urls(urls=args.url, urls_file=args.urls_file, limit=args.limit)
    if not urls:
        parser.error("Provide at least one --url or --urls-file.")

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(
        audit_application_coverage(
            urls,
            db_path=args.db_path,
            provider=args.provider,
            answers_file=args.answers_file,
            headful=args.headful,
            timeout_ms=args.timeout_ms,
            keep_db=args.keep_db,
        )
    )
    write_json_report(args.json_out, report)
    results = [item for item in report["results"] if isinstance(item, dict)]
    write_csv_report(args.csv_out, results)
    write_markdown_report(args.md_out, report)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"JSON: {args.json_out}")
    print(f"CSV: {args.csv_out}")
    print(f"Markdown: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
