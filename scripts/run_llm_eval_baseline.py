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
    build_auto_eval_case,
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ats_cv_result,
    evaluate_ranking_result,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline semantic eval baseline against real DB outputs.")
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-score", type=int)
    parser.add_argument(
        "--artifact",
        choices=["ranking", "application_materials", "ats_cv", "both", "all"],
        default="both",
    )
    parser.add_argument("--save-db", action="store_true")
    parser.add_argument("--fail-on-issues", action="store_true")
    parser.add_argument("--provider", default="baseline")
    parser.add_argument("--model", default="deterministic")
    parser.add_argument("--notes")
    parser.add_argument("--include-records", action="store_true", help="Include every case record in JSON output.")
    return parser.parse_args(argv)


def run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    profile = db.get_candidate_profile_payload() or {}
    ranked = db.get_ranked_jobs(ranking_version=args.ranking_version, min_score=args.min_score)
    if ranked.empty:
        summary = {"evaluated": 0, "message": "No ranked jobs found."}
        if getattr(args, "include_records", False):
            summary["records"] = []
        return summary

    records = []
    for row in ranked.head(args.limit).to_dict(orient="records"):
        case = build_auto_eval_case(_job_from_ranked_row(row), profile)
        if args.artifact in {"ranking", "both", "all"}:
            records.append(_evaluate_ranking_row(row, case, args))
        if args.artifact in {"application_materials", "both", "all"} and _has_materials(row):
            records.append(_evaluate_materials_row(row, case, args))
        if args.artifact in {"ats_cv", "all"} and _has_ats_cv(row):
            records.append(_evaluate_ats_cv_row(row, case, args))

    summary = _summary(records)
    if getattr(args, "include_records", False):
        summary["records"] = records
    return summary


def main() -> int:
    args = parse_args()
    summary = run_baseline(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if args.fail_on_issues and summary["failed"] > 0 else 0


def _evaluate_ranking_row(row: dict[str, Any], case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output = {
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row.get("confidence") or 0),
        "scores": _loads_json(row.get("scores_json"), {}),
        "evidence": _loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": _loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": _loads_json(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
    }
    result = evaluate_ranking_result(case, output)
    return _record(row, case, "ranking", output, result, args)


def _evaluate_materials_row(row: dict[str, Any], case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output = {
        "recruiter_message": _clean_cell(row.get("recruiter_message")),
        "cover_letter": _clean_cell(row.get("cover_letter")),
        "ats_cv_text": _clean_cell(row.get("ats_cv_text")),
        "autofill_notes": _clean_cell(row.get("autofill_notes")),
    }
    result = evaluate_application_materials(case, output)
    return _record(row, case, "application_materials", output, result, args)


def _evaluate_ats_cv_row(row: dict[str, Any], case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output = {"ats_cv_text": _clean_cell(row.get("ats_cv_text"))}
    result = evaluate_ats_cv_result(case, output)
    return _record(row, case, "ats_cv", output, result, args)


def _record(
    row: dict[str, Any],
    case: dict[str, Any],
    artifact_type: str,
    output: dict[str, Any],
    result: Any,
    args: argparse.Namespace,
) -> dict[str, Any]:
    judge_payload = build_llm_judge_payload(case, output, artifact_type)
    record = {
        "case_id": case["id"],
        "artifact_type": artifact_type,
        "job_id": int(row["job_id"]),
        "title": row.get("title"),
        "company": row.get("company"),
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
    }
    if args.save_db:
        saved = db.save_llm_eval_run(
            {
                "case_id": case["id"],
                "artifact_type": artifact_type,
                "job_id": int(row["job_id"]),
                "ranking_version": args.ranking_version if artifact_type == "ranking" else None,
                "provider": args.provider,
                "model": args.model,
                "passed": result.passed,
                "score": result.score,
                "issues": result.issues,
                "metrics": result.metrics,
                "output": output,
                "judge_payload": judge_payload,
                "notes": args.notes,
            }
        )
        record["saved_eval_run_id"] = saved["id"]
    return record


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    failed_records = [record for record in records if not record["passed"]]
    issue_counts: dict[str, int] = {}
    for record in failed_records:
        for issue in record["issues"]:
            key = str(issue).split(":", 1)[0]
            issue_counts[key] = issue_counts.get(key, 0) + 1
    return {
        "evaluated": len(records),
        "passed": len(records) - len(failed_records),
        "failed": len(failed_records),
        "average_score": round(sum(record["score"] for record in records) / len(records), 2) if records else 0,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        "failures": failed_records[:20],
    }


def _job_from_ranked_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("job_id"),
        "title": row.get("title"),
        "company": row.get("company"),
        "description_text": row.get("description_text"),
        "location": row.get("location"),
    }


def _has_materials(row: dict[str, Any]) -> bool:
    return any(_clean_cell(row.get(field)).strip() for field in ["recruiter_message", "ats_cv_text", "autofill_notes"])


def _has_ats_cv(row: dict[str, Any]) -> bool:
    return bool(_clean_cell(row.get("ats_cv_text")).strip())


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


if __name__ == "__main__":
    sys.exit(main())
