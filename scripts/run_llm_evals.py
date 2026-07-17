from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from joborchestrator.evals.semantic import (
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ranking_result,
)


DEFAULT_CASES_PATH = Path("tests/fixtures/llm_eval_cases.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline semantic evals for LLM ranking/material outputs.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--artifact", choices=["application_materials", "ranking"], required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSON file with the model output to evaluate.")
    parser.add_argument(
        "--judge-payload",
        type=Path,
        help="Optional path to write a structured payload for a future LLM judge.",
    )
    args = parser.parse_args()

    cases = _load_cases(args.cases)
    if args.case_id not in cases:
        available = ", ".join(sorted(cases))
        raise SystemExit(f"Unknown case_id {args.case_id!r}. Available: {available}")

    candidate_output = json.loads(args.output.read_text(encoding="utf-8"))
    case = cases[args.case_id]
    if args.artifact == "application_materials":
        result = evaluate_application_materials(case, candidate_output)
    else:
        result = evaluate_ranking_result(case, candidate_output)

    if args.judge_payload:
        payload = build_llm_judge_payload(case, candidate_output, args.artifact)
        args.judge_payload.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(_result_to_dict(result), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return {case["id"]: case for case in loaded}


def _result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
        "metrics": result.metrics,
    }


if __name__ == "__main__":
    sys.exit(main())
