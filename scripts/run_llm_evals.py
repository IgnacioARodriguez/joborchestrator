from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.evals.semantic import (
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ranking_result,
)
from joborchestrator.storage import persistence as db


DEFAULT_CASES_PATH = Path("tests/fixtures/llm_eval_cases.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline semantic evals for LLM ranking/material outputs.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case-id")
    parser.add_argument("--artifact", choices=["application_materials", "ranking"])
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--output", type=Path, help="JSON file with the model output to evaluate.")
    source_group.add_argument("--job-id", type=int, help="Load ranking/materials output for this DB job id.")
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--save-db", action="store_true", help="Persist the eval result in llm_eval_runs.")
    parser.add_argument("--provider", help="Provider/model owner label for saved eval metadata.")
    parser.add_argument("--model", help="Model label for saved eval metadata.")
    parser.add_argument("--notes", help="Free-form note for saved eval metadata.")
    parser.add_argument("--list-runs", action="store_true", help="List recent persisted eval runs and exit.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--judge-payload",
        type=Path,
        help="Optional path to write a structured payload for a future LLM judge.",
    )
    args = parser.parse_args()

    if args.list_runs:
        _print_runs(args.limit, args.case_id, args.artifact)
        return 0

    if not args.case_id or not args.artifact:
        parser.error("--case-id and --artifact are required unless --list-runs is used")
    if not args.output and not args.job_id:
        parser.error("one of --output or --job-id is required")

    cases = _load_cases(args.cases)
    if args.case_id not in cases:
        available = ", ".join(sorted(cases))
        raise SystemExit(f"Unknown case_id {args.case_id!r}. Available: {available}")

    candidate_output = _load_candidate_output(args)
    case = cases[args.case_id]
    if args.artifact == "application_materials":
        result = evaluate_application_materials(case, candidate_output)
    else:
        result = evaluate_ranking_result(case, candidate_output)

    judge_payload = build_llm_judge_payload(case, candidate_output, args.artifact)
    if args.judge_payload:
        args.judge_payload.write_text(json.dumps(judge_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    saved_id = None
    if args.save_db:
        saved = db.save_llm_eval_run(
            {
                "case_id": args.case_id,
                "artifact_type": args.artifact,
                "job_id": args.job_id,
                "ranking_version": args.ranking_version if args.artifact == "ranking" else None,
                "provider": args.provider,
                "model": args.model,
                "passed": result.passed,
                "score": result.score,
                "issues": result.issues,
                "metrics": result.metrics,
                "output": candidate_output,
                "judge_payload": judge_payload,
                "notes": args.notes,
            }
        )
        saved_id = saved["id"]

    response = _result_to_dict(result)
    if saved_id is not None:
        response["saved_eval_run_id"] = saved_id
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    return {case["id"]: case for case in loaded}


def _load_candidate_output(args: argparse.Namespace) -> dict[str, Any]:
    if args.output:
        return json.loads(args.output.read_text(encoding="utf-8-sig"))
    if args.artifact == "application_materials":
        job = db.get_job_posting(int(args.job_id))
        if not job:
            raise SystemExit(f"Job id {args.job_id} was not found.")
        return {
            "recruiter_message": job.get("recruiter_message") or "",
            "cover_letter": job.get("cover_letter") or "",
            "ats_cv_text": job.get("ats_cv_text") or "",
            "autofill_notes": job.get("autofill_notes") or "",
        }
    rows = db.get_rankings_for_job_ids(args.ranking_version, [int(args.job_id)])
    if rows.empty:
        raise SystemExit(f"No ranking found for job id {args.job_id} and version {args.ranking_version!r}.")
    row = rows.iloc[0].to_dict()
    return {
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row["confidence"] or 0),
        "scores": _loads_json(row.get("scores_json"), {}),
        "evidence": _loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": _loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": _loads_json(
            row.get("cv_keywords_to_avoid_overclaiming_json"),
            [],
        ),
    }


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
        "metrics": result.metrics,
    }


def _print_runs(limit: int, case_id: str | None, artifact_type: str | None) -> None:
    rows = db.list_llm_eval_runs(limit=limit, case_id=case_id, artifact_type=artifact_type)
    records = []
    for row in rows.to_dict(orient="records"):
        records.append(
            {
                "id": int(row["id"]),
                "case_id": row["case_id"],
                "artifact_type": row["artifact_type"],
                "job_id": row.get("job_id"),
                "ranking_version": row.get("ranking_version"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "passed": bool(row["passed"]),
                "score": int(row["score"]),
                "issues": _loads_json(row.get("issues_json"), []),
                "created_at": row["created_at"],
            }
        )
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
