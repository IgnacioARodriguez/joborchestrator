from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.prompts import PROMPTS_ROOT, REGISTRY_PATH, active_prompt_version, load_prompt  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from scripts.run_llm_eval_baseline import parse_args as parse_baseline_args  # noqa: E402
from scripts.run_llm_eval_baseline import run_baseline  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/eval_loops")
SURFACE_ALIASES = {
    "materials": "application_materials",
    "application_materials": "application_materials",
    "ranking": "ranking",
    "ats_cv": "ats_cv",
}
CRITICAL_ISSUES = {
    "unsupported_claims",
    "ats_cv_contains_internal_notes",
    "apply_now_with_expected_dealbreaker",
    "unsafe_cv_keyword_emphasis",
    "judge_disputed",
}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    branch = current_branch()
    if branch in {"main", "master"} and not args.allow_main:
        raise SystemExit(
            f"Refusing to run eval loop on {branch}. Create a branch first or pass --allow-main for audit-only use."
        )

    surfaces = parse_surfaces(args.surfaces)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_started = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    audit_path = args.output_dir / f"eval_loop_{run_started}.json"

    accepted_patches = 0
    no_improvement_count = 0
    previous_summary: dict[str, Any] | None = None
    iterations: list[dict[str, Any]] = []

    for iteration in range(1, args.max_iterations + 1):
        summary = run_iteration_baseline(args, surfaces, iteration)
        worst_issue = select_worst_issue(summary)
        prompt_target = prompt_owner_for_issue(worst_issue["issue"]) if worst_issue else None
        patch: dict[str, Any] | None = None
        stop_reason = ""

        hard_stop = hard_stop_reason(summary)
        if hard_stop:
            stop_reason = hard_stop
        elif not worst_issue:
            stop_reason = "no_issues"
        elif args.llm_call_cap <= 0:
            stop_reason = "llm_call_cap_reached"
        elif args.apply_prompt_patch and prompt_target:
            patch = try_prompt_patch(args, summary, prompt_target, worst_issue, surfaces, iteration)
            if patch["accepted"]:
                accepted_patches += 1
                no_improvement_count = 0
            else:
                no_improvement_count += 1
        else:
            patch = build_prompt_patch_plan(prompt_target, worst_issue)
            no_improvement_count += 1

        diff = compare_summaries(previous_summary, summary)
        record = {
            "iteration": iteration,
            "summary": summary_without_records(summary),
            "diff": diff,
            "worst_issue": worst_issue,
            "prompt_target": prompt_target,
            "patch": patch,
            "stop_reason": stop_reason,
        }
        iterations.append(record)
        write_audit(audit_path, args, branch, iterations, accepted_patches)

        if stop_reason:
            break
        if no_improvement_count >= args.stop_if_no_improvement:
            iterations[-1]["stop_reason"] = "stop_if_no_improvement"
            write_audit(audit_path, args, branch, iterations, accepted_patches)
            break
        previous_summary = summary

    final = {
        "audit_path": str(audit_path),
        "branch": branch,
        "iterations": len(iterations),
        "accepted_patches": accepted_patches,
        "last_stop_reason": iterations[-1].get("stop_reason") if iterations else "not_run",
        "last_summary": iterations[-1]["summary"] if iterations else {},
    }
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a guarded autonomous prompt-eval loop.")
    parser.add_argument("--surfaces", default="ranking,materials,ats_cv")
    parser.add_argument("--max-iterations", type=int, default=15)
    parser.add_argument("--stop-if-no-improvement", type=int, default=2)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--llm-call-cap", type=int, default=0)
    parser.add_argument("--allow-main", action="store_true")
    parser.add_argument(
        "--apply-prompt-patch",
        action="store_true",
        help="Create a prompt version hypothesis and keep it only if stored-output evals improve.",
    )
    return parser.parse_args(argv)


def run_iteration_baseline(args: argparse.Namespace, surfaces: list[str], iteration: int) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for surface in surfaces:
        baseline_args = parse_baseline_args(
            [
                "--artifact",
                surface,
                "--limit",
                str(args.limit),
                "--ranking-version",
                args.ranking_version,
                "--provider",
                "eval-loop",
                "--model",
                "deterministic",
                "--notes",
                f"eval-loop iteration {iteration}",
                "--include-records",
            ]
            + (["--min-score", str(args.min_score)] if args.min_score is not None else [])
        )
        summary = run_baseline(baseline_args)
        records.extend(summary.get("records") or [])
    return summarize_records(records)


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    by_surface: dict[str, dict[str, Any]] = {}
    failures = []
    for record in records:
        surface = str(record.get("artifact_type") or "unknown")
        surface_bucket = by_surface.setdefault(surface, {"evaluated": 0, "passed": 0, "failed": 0, "average_score": 0})
        surface_bucket["evaluated"] += 1
        if record.get("passed"):
            surface_bucket["passed"] += 1
        else:
            surface_bucket["failed"] += 1
            failures.append(record)
        surface_bucket["average_score"] += int(record.get("score") or 0)
        for issue in record.get("issues") or []:
            issue_counts[issue_key(issue)] += 1
    for surface_bucket in by_surface.values():
        evaluated = int(surface_bucket["evaluated"])
        surface_bucket["pass_rate"] = round(surface_bucket["passed"] / evaluated, 4) if evaluated else 0
        surface_bucket["average_score"] = round(surface_bucket["average_score"] / evaluated, 2) if evaluated else 0
    evaluated = len(records)
    passed = sum(1 for record in records if record.get("passed"))
    return {
        "evaluated": evaluated,
        "passed": passed,
        "failed": evaluated - passed,
        "pass_rate": round(passed / evaluated, 4) if evaluated else 0,
        "average_score": round(sum(int(record.get("score") or 0) for record in records) / evaluated, 2)
        if evaluated
        else 0,
        "by_surface": by_surface,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        "failures": failures[:50],
        "records": records,
    }


def select_worst_issue(summary: dict[str, Any]) -> dict[str, Any] | None:
    issue_counts = summary.get("issue_counts") or {}
    if not issue_counts:
        return None
    issue, count = sorted(
        issue_counts.items(),
        key=lambda item: (-(int(item[1]) * issue_severity(str(item[0]))), -int(item[1]), str(item[0])),
    )[0]
    return {"issue": issue, "count": int(count), "severity": issue_severity(issue)}


def prompt_owner_for_issue(issue: str | None) -> str | None:
    if not issue:
        return None
    if issue.startswith(("invalid_decision", "decision_", "score_", "missing_evidence", "apply_now")):
        return "ranking/nvidia_response_contract"
    if issue.startswith(("recruiter_message", "missing_job_specificity", "missing_required_fields")):
        return "materials/nvidia_kit_contract"
    if issue.startswith(("ats_cv", "omitted_base_experience", "unsupported_claims", "missing_required_keywords")):
        return "materials/nvidia_cv_contract"
    return None


def build_prompt_patch_plan(prompt_target: str | None, worst_issue: dict[str, Any] | None) -> dict[str, Any] | None:
    if not prompt_target or not worst_issue:
        return None
    return {
        "mode": "plan_only",
        "target": prompt_target,
        "accepted": False,
        "reason": (
            "Stored-output evals cannot improve until affected artifacts are regenerated. "
            "Run with --apply-prompt-patch only when regeneration is wired into the loop."
        ),
        "proposed_note": prompt_hypothesis_note(worst_issue["issue"]),
    }


def try_prompt_patch(
    args: argparse.Namespace,
    before_summary: dict[str, Any],
    prompt_target: str,
    worst_issue: dict[str, Any],
    surfaces: list[str],
    iteration: int,
) -> dict[str, Any]:
    backup_registry = REGISTRY_PATH.read_text(encoding="utf-8")
    surface, sub_case = prompt_target.split("/", 1)
    current_version = active_prompt_version(surface, sub_case)
    next_version = next_prompt_version(current_version)
    prompt_dir = PROMPTS_ROOT / surface / sub_case
    next_path = prompt_dir / f"{next_version}.md"
    original_prompt = load_prompt(surface, sub_case)
    next_path.write_text(
        original_prompt
        + "\n\n"
        + f"Loop hypothesis {iteration}: {prompt_hypothesis_note(worst_issue['issue'])}\n",
        encoding="utf-8",
    )
    update_prompt_registry(prompt_target, next_version)
    after_summary = run_iteration_baseline(args, surfaces, iteration)
    accepted = is_promotion_allowed(before_summary, after_summary)
    if not accepted:
        REGISTRY_PATH.write_text(backup_registry, encoding="utf-8")
        next_path.unlink(missing_ok=True)
    return {
        "mode": "applied" if accepted else "reverted",
        "target": prompt_target,
        "from_version": current_version,
        "to_version": next_version,
        "accepted": accepted,
        "before": summary_without_records(before_summary),
        "after": summary_without_records(after_summary),
        "reason": "promotion_rule_passed" if accepted else "promotion_rule_failed_or_no_regeneration",
    }


def update_prompt_registry(prompt_target: str, version: str) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    env = registry.get("active_environment") or "default"
    registry.setdefault("environments", {}).setdefault(env, {})[prompt_target] = version
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_promotion_allowed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if hard_stop_reason(after):
        return False
    return float(after.get("pass_rate") or 0) >= float(before.get("pass_rate") or 0) and int(
        after.get("failed") or 0
    ) <= int(before.get("failed") or 0)


def compare_summaries(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return {"baseline": True}
    previous_cases = case_statuses(previous)
    current_cases = case_statuses(current)
    regressions = [
        key for key, passed in previous_cases.items() if passed and key in current_cases and not current_cases[key]
    ]
    return {
        "pass_rate_delta": round(float(current.get("pass_rate") or 0) - float(previous.get("pass_rate") or 0), 4),
        "score_delta": round(float(current.get("average_score") or 0) - float(previous.get("average_score") or 0), 2),
        "regressions": regressions,
    }


def case_statuses(summary: dict[str, Any]) -> dict[str, bool]:
    return {
        f"{record.get('artifact_type')}:{record.get('case_id')}": bool(record.get("passed"))
        for record in summary.get("records") or []
    }


def hard_stop_reason(summary: dict[str, Any]) -> str:
    for issue in summary.get("issue_counts") or {}:
        if issue in CRITICAL_ISSUES:
            return f"critical_issue:{issue}"
    return ""


def prompt_hypothesis_note(issue: str) -> str:
    suggestions = {
        "recruiter_message_too_long": "Make recruiter_message a single short recruiter note under the configured character limit.",
        "recruiter_message_cover_letter_style": "Reject cover-letter salutations and formal letter closings in recruiter_message.",
        "ats_cv_contains_internal_notes": "Return final CV text only; never include target role, keyword, or optimization notes.",
        "omitted_base_experience": "Preserve every real source CV experience entry, even older or less relevant roles.",
        "unsupported_claims": "Use only candidate-supported facts; put adjacent or uncertain claims in risk flags instead.",
        "missing_required_keywords": "Include truthful job keywords or accepted synonyms in parseable ATS sections.",
        "missing_evidence_terms": "Cite concrete source-job evidence for the strongest match and central gap.",
    }
    return suggestions.get(issue, f"Address recurring eval issue `{issue}` with a stricter output rule.")


def issue_key(issue: Any) -> str:
    return str(issue).split(":", 1)[0]


def issue_severity(issue: str) -> int:
    if issue in CRITICAL_ISSUES:
        return 3
    if issue.startswith(("unsupported", "ats_cv", "apply_now", "unsafe")):
        return 2
    return 1


def parse_surfaces(value: str) -> list[str]:
    surfaces = []
    for item in value.split(","):
        normalized = SURFACE_ALIASES.get(item.strip())
        if not normalized:
            raise SystemExit(f"Unsupported surface: {item}")
        if normalized not in surfaces:
            surfaces.append(normalized)
    return surfaces


def next_prompt_version(version: str) -> str:
    match = re.fullmatch(r"v(\d+)", version)
    if not match:
        raise SystemExit(f"Cannot bump non-standard prompt version: {version}")
    return f"v{int(match.group(1)) + 1}"


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def summary_without_records(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "records"}


def write_audit(
    path: Path,
    args: argparse.Namespace,
    branch: str,
    iterations: list[dict[str, Any]],
    accepted_patches: int,
) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": branch,
        "config": {
            "surfaces": args.surfaces,
            "max_iterations": args.max_iterations,
            "stop_if_no_improvement": args.stop_if_no_improvement,
            "llm_call_cap": args.llm_call_cap,
            "apply_prompt_patch": args.apply_prompt_patch,
        },
        "accepted_patches": accepted_patches,
        "iterations": iterations,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
