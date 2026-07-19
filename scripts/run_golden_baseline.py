from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.evals.semantic import (  # noqa: E402
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ats_cv_result,
    evaluate_ranking_result,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402
from scripts.run_evals_loop import (  # noqa: E402
    DEFAULT_GOLDEN_CASES_DIR,
    fixture_surface,
    golden_fixture_case,
    load_golden_fixtures,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic golden evals against persisted DB outputs.")
    parser.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES_DIR)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument(
        "--artifact",
        choices=["ranking", "application_materials", "ats_cv", "all"],
        default="all",
    )
    parser.add_argument("--include-records", action="store_true")
    parser.add_argument("--save-db", action="store_true")
    parser.add_argument("--fail-on-issues", action="store_true")
    parser.add_argument("--provider", default="golden-baseline")
    parser.add_argument("--model", default="deterministic")
    parser.add_argument("--notes")
    return parser.parse_args(argv)


def run_golden_baseline(args: argparse.Namespace) -> dict[str, Any]:
    fixtures = [
        fixture
        for fixture in load_golden_fixtures(args.golden_cases)
        if args.artifact == "all" or fixture_surface(fixture) == args.artifact
    ]
    records = []
    skipped = []
    for fixture in fixtures:
        try:
            record = evaluate_fixture(args, fixture)
        except MissingGoldenOutput as exc:
            skipped.append({"case_id": fixture.get("case_id"), "reason": str(exc)})
            continue
        records.append(record)
    summary = summarize(records)
    response: dict[str, Any] = {
        **summary,
        "fixtures": len(fixtures),
        "skipped": skipped,
        "ranking_version": args.ranking_version,
    }
    if args.include_records:
        response["records"] = records
    return response


def evaluate_fixture(args: argparse.Namespace, fixture: dict[str, Any]) -> dict[str, Any]:
    surface = fixture_surface(fixture)
    source = fixture.get("source") or {}
    job_id = int(source.get("job_id") or 0)
    if job_id <= 0:
        raise MissingGoldenOutput("fixture has no DB job_id")
    case = golden_fixture_case(fixture)
    if surface == "ranking":
        output = ranking_output(job_id, args.ranking_version)
        result = evaluate_ranking_result(case, output)
    elif surface == "application_materials":
        output = materials_output(job_id)
        result = evaluate_application_materials(case, output)
    elif surface == "ats_cv":
        output = ats_cv_output(job_id)
        result = evaluate_ats_cv_result(case, output)
    else:
        raise MissingGoldenOutput(f"unsupported fixture surface: {surface}")
    return record_for_result(args, fixture, case, job_id, surface, output, result)


def ranking_output(job_id: int, ranking_version: str) -> dict[str, Any]:
    rows = db.get_rankings_for_job_ids(ranking_version, [job_id])
    if rows.empty:
        raise MissingGoldenOutput(f"no stored ranking for job_id={job_id}")
    row = rows.iloc[0].to_dict()
    return {
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row.get("confidence") or 0),
        "scores": loads_json(row.get("scores_json"), {}),
        "evidence": loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": clean_cell(row.get("reasoning_summary")),
        "recommended_application_angle": clean_cell(row.get("recommended_application_angle")),
        "cv_keywords_to_emphasize": loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": loads_json(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
    }


def materials_output(job_id: int) -> dict[str, Any]:
    job = db.get_job_posting(job_id)
    if not job:
        raise MissingGoldenOutput(f"job_id={job_id} was not found")
    output = {
        "recruiter_message": clean_cell(job.get("recruiter_message")),
        "cover_letter": clean_cell(job.get("cover_letter")),
        "ats_cv_text": clean_cell(job.get("ats_cv_text")),
        "autofill_notes": clean_cell(job.get("autofill_notes")),
    }
    if not any(value.strip() for value in output.values()):
        raise MissingGoldenOutput(f"no stored application materials for job_id={job_id}")
    return output


def ats_cv_output(job_id: int) -> dict[str, Any]:
    job = db.get_job_posting(job_id)
    if not job:
        raise MissingGoldenOutput(f"job_id={job_id} was not found")
    ats_cv_text = clean_cell(job.get("ats_cv_text"))
    if not ats_cv_text.strip():
        raise MissingGoldenOutput(f"no stored ATS CV for job_id={job_id}")
    return {"ats_cv_text": ats_cv_text}


def record_for_result(
    args: argparse.Namespace,
    fixture: dict[str, Any],
    case: dict[str, Any],
    job_id: int,
    artifact_type: str,
    output: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    record = {
        "case_id": fixture.get("case_id"),
        "artifact_type": artifact_type,
        "job_id": job_id,
        "review_status": fixture.get("review_status"),
        "critical": bool(fixture.get("critical")),
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
    }
    if args.save_db:
        saved = db.save_llm_eval_run(
            {
                "case_id": str(fixture.get("case_id") or case.get("id")),
                "artifact_type": artifact_type,
                "job_id": job_id,
                "ranking_version": args.ranking_version if artifact_type == "ranking" else None,
                "provider": args.provider,
                "model": args.model,
                "passed": result.passed,
                "score": result.score,
                "issues": result.issues,
                "metrics": result.metrics,
                "output": output,
                "judge_payload": build_llm_judge_payload(case, output, artifact_type),
                "notes": args.notes,
            }
        )
        record["saved_eval_run_id"] = saved["id"]
    return record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [record for record in records if not record["passed"]]
    critical_failures = [record for record in failed if record.get("critical")]
    issue_counts: dict[str, int] = {}
    by_surface: dict[str, dict[str, int]] = {}
    for record in records:
        surface = str(record["artifact_type"])
        by_surface.setdefault(surface, {"evaluated": 0, "passed": 0, "failed": 0})
        by_surface[surface]["evaluated"] += 1
        by_surface[surface]["passed" if record["passed"] else "failed"] += 1
    for record in failed:
        for issue in record.get("issues") or []:
            key = str(issue).split(":", 1)[0]
            issue_counts[key] = issue_counts.get(key, 0) + 1
    evaluated = len(records)
    return {
        "evaluated": evaluated,
        "passed": evaluated - len(failed),
        "failed": len(failed),
        "pass_rate": round((evaluated - len(failed)) / evaluated, 4) if evaluated else 0,
        "critical_failures": len(critical_failures),
        "average_score": round(sum(int(record["score"]) for record in records) / evaluated, 2) if evaluated else 0,
        "by_surface": by_surface,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        "failures": failed[:20],
    }


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text


def loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


class MissingGoldenOutput(RuntimeError):
    pass


def main() -> int:
    args = parse_args()
    summary = run_golden_baseline(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if args.fail_on_issues and summary["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
