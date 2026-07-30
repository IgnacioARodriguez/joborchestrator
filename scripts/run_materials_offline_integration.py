from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.intelligence.materials_context import (  # noqa: E402
    build_generation_context,
    forbidden_aliases_absent_from_generation_context,
)
from joborchestrator.intelligence.materials_controlled_pipeline import build_controlled_ats_cv  # noqa: E402
from joborchestrator.intelligence.materials_language import language_mismatch  # noqa: E402
from joborchestrator.intelligence.materials_routing import should_auto_generate_materials  # noqa: E402

DEFAULT_FIXTURES = Path("tests/fixtures/materials_controlled_offline_cases.json")


def run_offline_integration(fixtures_path: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    fixture = json.loads(fixtures_path.read_text(encoding="utf-8"))
    case_results = [_run_case(case) for case in fixture["cases"]]
    scenario_coverage = sorted({scenario for case in fixture["cases"] for scenario in case.get("scenarios", [])})
    required_scenarios = list(fixture.get("required_scenarios") or [])
    missing_scenarios = [scenario for scenario in required_scenarios if scenario not in scenario_coverage]
    passed = sum(1 for case in case_results if case["passed"])
    return {
        "mode": "offline_integration",
        "case_count": len(case_results),
        "passed": passed,
        "failed": len(case_results) - passed,
        "required_scenarios": required_scenarios,
        "scenario_coverage": scenario_coverage,
        "missing_scenarios": missing_scenarios,
        "cases": case_results,
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    payload = case.get("payload") if isinstance(case.get("payload"), dict) else {}
    expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    generation_context = build_generation_context(payload)

    if "auto_generate" in expect:
        actual = should_auto_generate_materials(payload.get("ranking"))
        _check(issues, actual == expect["auto_generate"], f"auto_generate expected {expect['auto_generate']} got {actual}")

    if "target_language" in expect:
        actual_language = generation_context["job"]["target_language"]
        _check(issues, actual_language == expect["target_language"], f"target_language expected {expect['target_language']} got {actual_language}")

    if "language_mismatch" in expect:
        target_language = generation_context["job"]["target_language"]
        actual_mismatch = language_mismatch(str(case.get("language_text") or ""), target_language)
        _check(issues, actual_mismatch == expect["language_mismatch"], f"language_mismatch expected {expect['language_mismatch']} got {actual_mismatch}")

    aliases = ((payload.get("ranking_constraints") or {}).get("avoid_overclaiming_aliases") or {}) if isinstance(payload.get("ranking_constraints"), dict) else {}
    if "forbidden_aliases_absent" in expect:
        actual_absent = forbidden_aliases_absent_from_generation_context(generation_context, aliases)
        _check(issues, actual_absent == expect["forbidden_aliases_absent"], f"forbidden_aliases_absent expected {expect['forbidden_aliases_absent']} got {actual_absent}")

    controlled_cv: dict[str, Any] | None = None
    if case.get("base_cv_text"):
        supported_keywords = list((payload.get("ats_fit_analysis") or {}).get("supported_keywords") or []) if isinstance(payload.get("ats_fit_analysis"), dict) else []
        controlled_cv = build_controlled_ats_cv(
            str(case.get("base_cv_text") or ""),
            supported_keywords,
            planner_response=case.get("planner_response") if isinstance(case.get("planner_response"), dict) else None,
        )
        cv_text = str(controlled_cv.get("ats_cv_text") or "")
        for expected_text in expect.get("contains") or []:
            _check(issues, str(expected_text) in cv_text, f"missing rendered text: {expected_text}")
        for forbidden_text in expect.get("not_contains") or []:
            _check(issues, str(forbidden_text) not in cv_text, f"forbidden rendered text present: {forbidden_text}")
        if "keywords_used" in expect:
            _check(issues, controlled_cv.get("keywords_used") == expect["keywords_used"], f"keywords_used expected {expect['keywords_used']} got {controlled_cv.get('keywords_used')}")
        metadata = controlled_cv.get("_generation_metadata") if isinstance(controlled_cv.get("_generation_metadata"), dict) else {}
        if "human_review_required" in expect:
            _check(issues, metadata.get("human_review_required") is expect["human_review_required"], f"human_review_required expected {expect['human_review_required']} got {metadata.get('human_review_required')}")
        if "risk_flags" in expect:
            _check(issues, controlled_cv.get("risk_flags") == expect["risk_flags"], f"risk_flags expected {expect['risk_flags']} got {controlled_cv.get('risk_flags')}")
        if "validation_errors" in expect:
            _check(issues, metadata.get("validation_errors") == expect["validation_errors"], f"validation_errors expected {expect['validation_errors']} got {metadata.get('validation_errors')}")

    return {
        "case_id": case["case_id"],
        "scenarios": list(case.get("scenarios") or []),
        "passed": not issues,
        "issues": issues,
    }


def _check(issues: list[str], condition: bool, message: str) -> None:
    if not condition:
        issues.append(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic offline materials integration cases.")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_offline_integration(args.fixtures)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if report["failed"] or report["missing_scenarios"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
