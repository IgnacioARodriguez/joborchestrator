from __future__ import annotations

import argparse
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_evals_loop import DEFAULT_GOLDEN_CASES_DIR, fixture_surface, load_golden_fixtures  # noqa: E402
from scripts.run_golden_baseline import run_golden_baseline  # noqa: E402
from scripts.smoke_e2e import run_guardrail_smoke, run_scan_smoke, run_smoke_e2e  # noqa: E402

SURFACES = ("ranking", "application_materials", "ats_cv")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local LLM trust gate without live LLM calls.")
    parser.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES_DIR)
    parser.add_argument("--min-reviewed-golden", type=int, default=30)
    parser.add_argument("--min-restraint-cases", type=int, default=10)
    parser.add_argument("--ranking-version", default="ranking_v1.1.0-nvidia")
    parser.add_argument("--run-golden-baseline", action="store_true")
    parser.add_argument("--include-records", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def run_trust_gate(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="joborchestrator-trust-gate-") as tmp:
        tmp_path = Path(tmp)
        checks: dict[str, dict[str, Any]] = {
            "offline_e2e": run_smoke_e2e(db_path=tmp_path / "offline-e2e.db"),
            "guardrails": run_guardrail_smoke(),
            "scan": run_scan_smoke(db_path=tmp_path / "scan.db"),
            "golden_fixtures": audit_golden_fixtures(
                args.golden_cases,
                min_reviewed=args.min_reviewed_golden,
                min_restraint_cases=args.min_restraint_cases,
            ),
        }
        if args.run_golden_baseline:
            checks["golden_baseline"] = run_persisted_golden_baseline(args)
    passed = all(bool(check.get("passed")) for check in checks.values())
    summary = {
        "passed": passed,
        "mode": "local_offline_trust_gate",
        "checks": checks,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def audit_golden_fixtures(path: Path, *, min_reviewed: int, min_restraint_cases: int) -> dict[str, Any]:
    fixtures = load_golden_fixtures(path)
    by_surface = {surface: 0 for surface in SURFACES}
    for fixture in fixtures:
        surface = fixture_surface(fixture)
        if surface in by_surface:
            by_surface[surface] += 1
    restraint_cases = sum(1 for fixture in fixtures if is_restraint_case(fixture))
    issues = []
    if len(fixtures) < min_reviewed:
        issues.append(f"reviewed_golden_below_minimum:{len(fixtures)}<{min_reviewed}")
    for surface, count in by_surface.items():
        if count == 0:
            issues.append(f"missing_surface:{surface}")
    if restraint_cases < min_restraint_cases:
        issues.append(f"restraint_cases_below_minimum:{restraint_cases}<{min_restraint_cases}")
    return {
        "passed": not issues,
        "reviewed": len(fixtures),
        "by_surface": by_surface,
        "critical": sum(1 for fixture in fixtures if fixture.get("critical")),
        "restraint_cases": restraint_cases,
        "issues": issues,
    }


def is_restraint_case(fixture: dict[str, Any]) -> bool:
    expected = fixture.get("expected") or {}
    allowed = set(expected.get("allowed_decisions") or [])
    return (
        bool(allowed and allowed <= {"MAYBE", "SKIP", "AVOID"})
        or int(expected.get("max_score") or 999) <= 55
        or bool(expected.get("dealbreaker_terms"))
    )


def run_persisted_golden_baseline(args: argparse.Namespace) -> dict[str, Any]:
    baseline = run_golden_baseline(
        Namespace(
            golden_cases=args.golden_cases,
            ranking_version=args.ranking_version,
            artifact="all",
            include_records=args.include_records,
            save_db=False,
            fail_on_issues=False,
            provider="trust-gate",
            model="deterministic",
            notes=None,
        )
    )
    return {
        **baseline,
        "passed": bool(
            baseline.get("evaluated")
            and not baseline.get("skipped")
            and int(baseline.get("failed") or 0) == 0
            and int(baseline.get("critical_failures") or 0) == 0
        ),
    }


def main() -> int:
    args = parse_args()
    summary = run_trust_gate(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
