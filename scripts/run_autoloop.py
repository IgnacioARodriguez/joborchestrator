from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from scripts.compute_autoloop_metrics import compute_metrics, fetch_ranking_rows  # noqa: E402
from scripts.select_probe_cases import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_GOLDEN_CASES_DIR,
    DEFAULT_KNOWN_HARD_CASES,
    fetch_candidate_rows,
    golden_failure_ids,
    load_config,
    load_known_hard_cases,
    select_probe_cases,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one safe autoloop dry-run iteration.")
    parser.add_argument("--dry-run", action="store_true", help="Required. Do not edit prompts, rerank, or commit.")
    parser.add_argument("--ranking-job-id", type=int)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--known-hard-cases", type=Path, default=DEFAULT_KNOWN_HARD_CASES)
    parser.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES_DIR)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--probe-output", type=Path)
    return parser.parse_args(argv)


def run_autoloop(args: argparse.Namespace) -> dict[str, Any]:
    if not args.dry_run:
        raise AutoloopError("run_autoloop currently supports only --dry-run.")

    config = load_config(args.config)
    runtime = config.get("runtime") or {}
    state_path = args.state_path or Path(runtime.get("state_path") or "logs/autoloop_state.json")
    log_path = args.log_path or Path(runtime.get("log_path") or "logs/autoloop_log.jsonl")
    probe_output = args.probe_output or Path("logs/autoloop_probe_cases.json")
    stop_file = Path(runtime.get("stop_file") or "AUTOLOOP_STOP")
    previous_state = load_state(state_path)

    if stop_file.exists():
        event = autoloop_event(
            args=args,
            status="halted",
            decision={
                "action": "halt_required",
                "reason": "stop_file_present",
                "stop_file": str(stop_file),
            },
            metrics=None,
            probe=None,
            previous_state=previous_state,
        )
        persist_event(event, state_path=state_path, log_path=log_path)
        return event

    runtime_limit_failures = evaluate_runtime_limits(previous_state, config)
    if runtime_limit_failures:
        event = autoloop_event(
            args=args,
            status="halted",
            decision={
                "action": "halt_required",
                "reason": "runtime_limits_exceeded",
                "runtime_limit_failures": runtime_limit_failures,
            },
            metrics=None,
            probe=None,
            previous_state=previous_state,
        )
        persist_event(event, state_path=state_path, log_path=log_path)
        return event

    metrics = compute_metrics(fetch_ranking_rows(ranking_job_id=args.ranking_job_id, ranking_version=args.ranking_version))
    probe = build_probe_payload(args, config)
    probe_output.parent.mkdir(parents=True, exist_ok=True)
    probe_output.write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    decision = decide(metrics, previous_state.get("baseline"), config.get("guards") or {})
    status = "halted" if decision["action"] == "halt_required" else "dry_run_complete"
    event = autoloop_event(
        args=args,
        status=status,
        decision=decision,
        metrics=metrics,
        probe={
            "output": str(probe_output),
            "candidate_count": probe["candidate_count"],
            "category_counts": probe["category_counts"],
        },
        previous_state=previous_state,
    )
    persist_event(event, state_path=state_path, log_path=log_path)
    return event


def build_probe_payload(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    known_hard = load_known_hard_cases(args.known_hard_cases)
    failures = golden_failure_ids(args.golden_cases, args.ranking_version)
    rows = fetch_candidate_rows(ranking_job_id=args.ranking_job_id, ranking_version=args.ranking_version)
    cases = select_probe_cases(
        rows,
        target_total=int(config.get("probe_target_total") or 20),
        category_quotas=dict(config.get("probe_category_quotas") or {}),
        golden_failure_ids=failures,
        known_hard_cases=known_hard,
    )
    category_counts: dict[str, int] = {}
    for case in cases:
        for category in case.get("categories") or []:
            category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "ranking_job_id": args.ranking_job_id,
        "ranking_version": args.ranking_version,
        "candidate_count": len(cases),
        "category_counts": dict(sorted(category_counts.items())),
        "protected_fixture_policy": "This dry-run reads golden fixtures but never writes evals/fixtures.",
        "cases": cases,
    }


def decide(metrics: dict[str, Any], baseline: dict[str, Any] | None, guards: dict[str, Any]) -> dict[str, Any]:
    guard_failures = evaluate_guards(metrics, guards)
    comparison = compare_metrics(baseline, metrics) if baseline else {"baseline": "missing"}
    if guard_failures:
        action = "halt_required"
    elif comparison.get("critical_regressions"):
        action = "reject"
    elif not baseline:
        action = "baseline_recorded"
    elif comparison.get("improvements"):
        action = "continue"
    else:
        action = "no_op"
    return {
        "action": action,
        "guard_failures": guard_failures,
        "comparison": comparison,
    }


def evaluate_guards(metrics: dict[str, Any], guards: dict[str, Any]) -> list[str]:
    checks = [
        ("critical_failures", "max_critical_failures"),
        ("stale_completion_count", "max_stale_completion_count"),
        ("apply_now_unsafe_rate", "max_apply_now_unsafe_rate"),
        ("non_active_prompt_rate", "max_non_active_prompt_rate"),
    ]
    failures = []
    for metric_key, guard_key in checks:
        if guard_key not in guards:
            continue
        value = float(metrics.get(metric_key) or 0)
        limit = float(guards[guard_key])
        if value > limit:
            failures.append(f"{metric_key}:{value:g}>{limit:g}")
    return failures


def evaluate_runtime_limits(previous_state: dict[str, Any], config: dict[str, Any]) -> list[str]:
    failures = []
    iteration = int(previous_state.get("iteration") or 0)
    max_iterations = config.get("max_iterations")
    if max_iterations is not None and iteration >= int(max_iterations):
        failures.append(f"iteration:{iteration}>={int(max_iterations)}")

    budgets = previous_state.get("budgets") or {}
    api_calls_used = int(budgets.get("api_calls_used") or 0)
    max_api_calls = config.get("max_api_calls")
    if max_api_calls is not None and api_calls_used >= int(max_api_calls):
        failures.append(f"api_calls_used:{api_calls_used}>={int(max_api_calls)}")

    estimated_tokens_used = int(budgets.get("estimated_tokens_used") or 0)
    max_tokens = config.get("max_tokens")
    if max_tokens is not None and estimated_tokens_used >= int(max_tokens):
        failures.append(f"estimated_tokens_used:{estimated_tokens_used}>={int(max_tokens)}")

    no_improvement_count = int(previous_state.get("consecutive_no_improvement") or 0)
    max_no_improvement = config.get("max_consecutive_no_improvement")
    if max_no_improvement is not None and no_improvement_count >= int(max_no_improvement):
        failures.append(f"consecutive_no_improvement:{no_improvement_count}>={int(max_no_improvement)}")
    return failures


def compare_metrics(baseline: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not baseline:
        return {"baseline": "missing"}
    lower_is_better = [
        "critical_failures",
        "unsafe_apply_now_count",
        "apply_now_unsafe_rate",
        "stale_completion_count",
        "retry_or_schema_count",
        "schema_failure_retry_rate",
        "non_active_prompt_count",
        "non_active_prompt_rate",
    ]
    higher_is_better = ["ranked_rows"]
    improvements = []
    regressions = []
    critical_regressions = []
    for key in lower_is_better:
        before = float(baseline.get(key) or 0)
        after = float(current.get(key) or 0)
        if after < before:
            improvements.append(f"{key}:{before:g}->{after:g}")
        elif after > before:
            item = f"{key}:{before:g}->{after:g}"
            regressions.append(item)
            if key in {
                "critical_failures",
                "unsafe_apply_now_count",
                "apply_now_unsafe_rate",
                "stale_completion_count",
                "non_active_prompt_count",
                "non_active_prompt_rate",
            }:
                critical_regressions.append(item)
    for key in higher_is_better:
        before = float(baseline.get(key) or 0)
        after = float(current.get(key) or 0)
        if after > before:
            improvements.append(f"{key}:{before:g}->{after:g}")
        elif after < before:
            regressions.append(f"{key}:{before:g}->{after:g}")
    return {
        "improvements": improvements,
        "regressions": regressions,
        "critical_regressions": critical_regressions,
    }


def autoloop_event(
    *,
    args: argparse.Namespace,
    status: str,
    decision: dict[str, Any],
    metrics: dict[str, Any] | None,
    probe: dict[str, Any] | None,
    previous_state: dict[str, Any],
) -> dict[str, Any]:
    iteration = int(previous_state.get("iteration") or 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "iteration": iteration,
        "mode": "dry_run",
        "ranking_job_id": args.ranking_job_id,
        "ranking_version": args.ranking_version,
        "decision": decision,
        "metrics": metrics,
        "probe": probe,
        "budgets": previous_state.get("budgets") or {"api_calls_used": 0, "estimated_tokens_used": 0},
        "previous_baseline": previous_state.get("baseline"),
        "previous_consecutive_no_improvement": int(previous_state.get("consecutive_no_improvement") or 0),
    }


def persist_event(event: dict[str, Any], *, state_path: Path, log_path: Path) -> None:
    state = {
        "status": event["status"],
        "iteration": event["iteration"],
        "baseline": event.get("metrics") if event.get("metrics") is not None else event.get("previous_baseline"),
        "last_decision": event.get("decision"),
        "last_probe": event.get("probe"),
        "budgets": event.get("budgets"),
        "consecutive_no_improvement": consecutive_no_improvement_count(event),
        "halt_reason": halt_reason(event),
        "updated_at": event["generated_at"],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def halt_reason(event: dict[str, Any]) -> str | None:
    decision = event.get("decision") or {}
    if decision.get("action") != "halt_required":
        return None
    failures = decision.get("guard_failures") or []
    if failures:
        return "; ".join(str(item) for item in failures)
    runtime_failures = decision.get("runtime_limit_failures") or []
    if runtime_failures:
        return "; ".join(str(item) for item in runtime_failures)
    return str(decision.get("reason") or "halt_required")


def consecutive_no_improvement_count(event: dict[str, Any]) -> int:
    current = int(event.get("previous_consecutive_no_improvement") or 0)
    action = (event.get("decision") or {}).get("action")
    if action in {"continue", "baseline_recorded"}:
        return 0
    if action in {"no_op", "reject"}:
        return current + 1
    return current


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class AutoloopError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        event = run_autoloop(args)
    except AutoloopError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
