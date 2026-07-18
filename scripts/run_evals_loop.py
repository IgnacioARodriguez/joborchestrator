from __future__ import annotations

import argparse
import difflib
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

from joborchestrator.evals.semantic import (  # noqa: E402
    build_auto_eval_case,
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ats_cv_result,
    evaluate_ranking_result,
)
from joborchestrator.intelligence.llm_application_materials import (  # noqa: E402
    DEFAULT_MATERIALS_MODEL,
    DEFAULT_NVIDIA_MATERIALS_MODEL,
    build_application_kit_with_llm,
    build_application_kit_with_nvidia,
    build_ats_cv_with_nvidia,
)
from joborchestrator.prompts import PROMPTS_ROOT, REGISTRY_PATH, active_prompt_version, load_prompt  # noqa: E402
from joborchestrator.ranking.llm_ranker import DEFAULT_LLM_MODEL, rank_job_with_llm  # noqa: E402
from joborchestrator.ranking.serialization import result_to_dict  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402
from scripts.run_llm_eval_baseline import parse_args as parse_baseline_args  # noqa: E402
from scripts.run_llm_eval_baseline import run_baseline  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/eval_loops")
DEFAULT_GOLDEN_CASES_DIR = Path("evals/fixtures/golden")
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
PROMPT_TARGET_CONSUMERS = {
    "ranking/nvidia_response_contract": ["joborchestrator/ranking/llm_ranker.py", "joborchestrator/ranking/nvidia_ranker.py"],
    "materials/nvidia_cv_contract": ["joborchestrator/intelligence/llm_application_materials.py"],
    "materials/nvidia_kit_contract": ["joborchestrator/intelligence/llm_application_materials.py"],
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
    previous_summary: dict[str, Any] | None = None if args.no_compare_last_run else load_previous_audit_summary(args.output_dir)
    iterations: list[dict[str, Any]] = []
    llm_calls_used = 0

    for iteration in range(1, args.max_iterations + 1):
        summary = run_iteration_baseline(args, surfaces, iteration)
        worst_issue = select_worst_issue(summary)
        prompt_target = prompt_owner_for_issue(worst_issue["issue"]) if worst_issue else None
        patch: dict[str, Any] | None = None
        stop_reason = ""

        hard_stop = hard_stop_reason(summary)
        if hard_stop and not args.regenerate_affected:
            stop_reason = hard_stop
        elif not worst_issue:
            stop_reason = "no_issues"
        elif args.llm_call_cap - llm_calls_used <= 0:
            stop_reason = "llm_call_cap_reached"
        elif args.apply_prompt_patch and prompt_target:
            patch = try_prompt_patch(
                args,
                summary,
                prompt_target,
                worst_issue,
                surfaces,
                iteration,
                remaining_llm_calls=args.llm_call_cap - llm_calls_used,
            )
            llm_calls_used += int(patch.get("llm_calls_used") or 0)
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
            "case_statuses": case_statuses(summary),
            "diff": diff,
            "worst_issue": worst_issue,
            "prompt_target": prompt_target,
            "patch": patch,
            "stop_reason": stop_reason,
            "llm_calls_used": llm_calls_used,
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
        "llm_calls_used": llm_calls_used,
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
    parser.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES_DIR)
    parser.add_argument("--llm-call-cap", type=int, default=0)
    parser.add_argument("--allow-main", action="store_true")
    parser.add_argument(
        "--regenerate-affected",
        action="store_true",
        help="Regenerate only affected records in memory before accepting a prompt hypothesis.",
    )
    parser.add_argument("--regeneration-provider", choices=["openai", "nvidia"], default="nvidia")
    parser.add_argument("--regeneration-model")
    parser.add_argument("--no-compare-last-run", action="store_true")
    parser.add_argument(
        "--commit-accepted-patches",
        action="store_true",
        help="Commit accepted prompt registry/version changes, one commit per accepted iteration.",
    )
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
    judge_issue_counts: Counter[str] = Counter()
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
        for issue in judge_issue_keys(record):
            judge_issue_counts[issue] += 1
    for surface_bucket in by_surface.values():
        evaluated = int(surface_bucket["evaluated"])
        surface_bucket["pass_rate"] = round(surface_bucket["passed"] / evaluated, 4) if evaluated else 0
        surface_bucket["average_score"] = round(surface_bucket["average_score"] / evaluated, 2) if evaluated else 0
    evaluated = len(records)
    passed = sum(1 for record in records if record.get("passed"))
    combined_issue_counts = issue_counts + judge_issue_counts
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
        "judge_issue_counts": dict(sorted(judge_issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        "all_issue_counts": dict(sorted(combined_issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        "failures": failures[:50],
        "records": records,
    }


def select_worst_issue(summary: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    for source, issue_counts in [
        ("deterministic", summary.get("issue_counts") or {}),
        ("judge", summary.get("judge_issue_counts") or {}),
    ]:
        for issue, count in issue_counts.items():
            candidates.append((source, str(issue), int(count)))
    if not candidates:
        return None
    for source, issue, count in sorted(
        candidates,
        key=lambda item: (-(item[2] * issue_severity(item[1])), -item[2], item[0], item[1]),
    ):
        prompt_target = prompt_owner_for_issue(issue)
        if prompt_target and is_prompt_target_wired(prompt_target):
            return {"issue": issue, "count": count, "severity": issue_severity(issue), "source": source}
    return None


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


def is_prompt_target_wired(prompt_target: str) -> bool:
    try:
        surface, sub_case = prompt_target.split("/", 1)
    except ValueError:
        return False
    consumers = PROMPT_TARGET_CONSUMERS.get(prompt_target) or []
    if not consumers:
        return False
    pattern = re.compile(
        rf"load_prompt\(\s*['\"]{re.escape(surface)}['\"]\s*,\s*['\"]{re.escape(sub_case)}['\"]"
    )
    for relative_path in consumers:
        path = PROJECT_ROOT / relative_path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern.search(source):
            return True
    return False


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
    remaining_llm_calls: int,
) -> dict[str, Any]:
    backup_registry = REGISTRY_PATH.read_text(encoding="utf-8")
    surface, sub_case = prompt_target.split("/", 1)
    current_version = active_prompt_version(surface, sub_case)
    next_version = next_prompt_version(current_version)
    prompt_dir = PROMPTS_ROOT / surface / sub_case
    next_path = prompt_dir / f"{next_version}.md"
    original_prompt = load_prompt(surface, sub_case)
    proposed_prompt = (
        original_prompt
        + "\n\n"
        + f"Loop hypothesis {iteration}: {prompt_hypothesis_note(worst_issue['issue'])}\n"
    )
    next_path.write_text(proposed_prompt, encoding="utf-8")
    update_prompt_registry(prompt_target, next_version)
    affected_before = summarize_records(affected_records(before_summary, worst_issue["issue"], prompt_target))
    regeneration = {"records": [], "llm_calls_used": 0, "skipped": []}
    golden = {"records": [], "llm_calls_used": 0, "skipped": [], "reason": "not_run"}
    if args.regenerate_affected:
        regeneration = regenerate_affected_records(
            args,
            before_summary,
            worst_issue["issue"],
            prompt_target,
            remaining_llm_calls=remaining_llm_calls,
        )
        after_summary = summarize_records(regeneration["records"])
    else:
        after_summary = run_iteration_baseline(args, surfaces, iteration)
    accepted = is_promotion_allowed(before_summary, after_summary)
    if args.regenerate_affected:
        accepted = bool(regeneration["records"]) and is_promotion_allowed(affected_before, after_summary)
    if accepted:
        golden = run_golden_set(
            args,
            remaining_llm_calls=remaining_llm_calls - int(regeneration.get("llm_calls_used") or 0),
        )
        accepted = is_golden_promotion_allowed(golden)
    if not accepted:
        REGISTRY_PATH.write_text(backup_registry, encoding="utf-8")
        next_path.unlink(missing_ok=True)
    elif args.commit_accepted_patches:
        commit_accepted_patch(next_path, worst_issue["issue"], iteration)
    return {
        "mode": "applied" if accepted else "reverted",
        "target": prompt_target,
        "from_version": current_version,
        "to_version": next_version,
        "accepted": accepted,
        "before": summary_without_records(affected_before if args.regenerate_affected else before_summary),
        "after": summary_without_records(after_summary),
        "regeneration": regeneration,
        "golden": golden,
        "llm_calls_used": int(regeneration.get("llm_calls_used") or 0) + int(golden.get("llm_calls_used") or 0),
        "prompt_diff": unified_prompt_diff(
            original_prompt,
            proposed_prompt,
            from_label=f"{prompt_target}:{current_version}",
            to_label=f"{prompt_target}:{next_version}",
        ),
        "committed": bool(accepted and args.commit_accepted_patches),
        "reason": "promotion_rule_passed" if accepted else "promotion_rule_failed",
    }


def run_golden_set(args: argparse.Namespace, *, remaining_llm_calls: int) -> dict[str, Any]:
    fixtures = load_golden_fixtures(args.golden_cases)
    if not fixtures:
        return {"records": [], "llm_calls_used": 0, "skipped": [], "reason": "no_golden_cases"}
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    calls_used = 0
    for fixture in fixtures:
        artifact_type = fixture_surface(fixture)
        estimated_calls = estimated_regeneration_calls(artifact_type, args.regeneration_provider)
        if calls_used + estimated_calls > remaining_llm_calls:
            skipped.append({"case_id": fixture.get("case_id"), "reason": "llm_call_cap"})
            continue
        try:
            records.append(regenerate_golden_fixture(args, fixture))
            calls_used += estimated_calls
        except Exception as exc:  # noqa: BLE001 - per-golden-case failures belong in audit.
            skipped.append({"case_id": fixture.get("case_id"), "reason": f"{type(exc).__name__}: {exc}"})
    return {
        "records": records,
        "summary": summary_without_records(summarize_records(records)),
        "llm_calls_used": calls_used,
        "skipped": skipped,
        "reason": "evaluated",
    }


def load_golden_fixtures(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    fixtures = []
    for file_path in files:
        try:
            fixture = json.loads(file_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if is_reviewed_golden_fixture(fixture):
            fixtures.append(fixture)
    return fixtures


def is_reviewed_golden_fixture(fixture: dict[str, Any]) -> bool:
    return str(fixture.get("review_status") or "").strip() == "reviewed" or bool(fixture.get("human_reviewed"))


def regenerate_golden_fixture(args: argparse.Namespace, fixture: dict[str, Any]) -> dict[str, Any]:
    artifact_type = fixture_surface(fixture)
    job = golden_fixture_job(fixture)
    case = golden_fixture_case(fixture)
    source = fixture.get("source") or {}
    job_id = int(source.get("job_id") or 0)
    ranking = ranking_payload_for_job(job_id, args.ranking_version) if job_id else None
    if artifact_type == "application_materials":
        output = regenerate_materials(args, job, ranking)
        result = evaluate_application_materials(case, output)
    elif artifact_type == "ats_cv":
        output = regenerate_ats_cv(args, job, ranking)
        result = evaluate_ats_cv_result(case, output)
    elif artifact_type == "ranking":
        output = regenerate_ranking(args, job)
        result = evaluate_ranking_result(case, output)
    else:
        raise RuntimeError(f"Unsupported golden fixture surface: {artifact_type}")
    return {
        "case_id": fixture.get("case_id"),
        "artifact_type": artifact_type,
        "review_status": fixture.get("review_status"),
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
        "metrics": result.metrics,
        "candidate_output": output,
    }


def golden_fixture_case(fixture: dict[str, Any]) -> dict[str, Any]:
    job = golden_fixture_job(fixture)
    profile = ((fixture.get("candidate_profile_snapshot") or {}).get("profile") or {})
    case = build_auto_eval_case(job, profile)
    case["id"] = fixture.get("case_id") or case["id"]
    case["review_status"] = fixture.get("review_status")
    expected = fixture.get("expected") or {}
    surface = fixture_surface(fixture)
    if surface == "ranking":
        case["ranking_expectations"] = expected
    elif surface == "ats_cv":
        case["ats_cv_expectations"] = expected
    else:
        case["materials_expectations"] = expected
    return case


def golden_fixture_job(fixture: dict[str, Any]) -> dict[str, Any]:
    raw_input = fixture.get("raw_input") or {}
    source = fixture.get("source") or {}
    return {
        "id": source.get("job_id"),
        "job_id": source.get("job_id"),
        "title": raw_input.get("title") or "",
        "company": raw_input.get("company") or "",
        "location": raw_input.get("location") or "",
        "description_text": raw_input.get("job_html_or_text") or "",
        "source": raw_input.get("source"),
        "url": raw_input.get("url"),
        "apply_url": raw_input.get("apply_url"),
    }


def fixture_surface(fixture: dict[str, Any]) -> str:
    surface = str(fixture.get("surface") or "").strip()
    return SURFACE_ALIASES.get(surface) or surface


def is_golden_promotion_allowed(golden: dict[str, Any]) -> bool:
    if golden.get("reason") == "no_golden_cases":
        return True
    if golden.get("skipped"):
        return False
    summary = summarize_records(golden.get("records") or [])
    return int(summary.get("evaluated") or 0) > 0 and not hard_stop_reason(summary) and int(summary.get("failed") or 0) == 0


def affected_records(summary: dict[str, Any], issue: str, prompt_target: str) -> list[dict[str, Any]]:
    target_surface = surface_for_prompt_target(prompt_target)
    selected = []
    for record in summary.get("records") or []:
        if target_surface and record.get("artifact_type") != target_surface:
            continue
        if any(issue_key(item) == issue for item in record.get("issues") or []):
            selected.append(record)
    return selected


def regenerate_affected_records(
    args: argparse.Namespace,
    before_summary: dict[str, Any],
    issue: str,
    prompt_target: str,
    *,
    remaining_llm_calls: int,
) -> dict[str, Any]:
    regenerated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    calls_used = 0
    for record in affected_records(before_summary, issue, prompt_target):
        estimated_calls = estimated_regeneration_calls(record["artifact_type"], args.regeneration_provider)
        if calls_used + estimated_calls > remaining_llm_calls:
            skipped.append({"case_id": record.get("case_id"), "reason": "llm_call_cap"})
            continue
        try:
            regenerated.append(regenerate_record(args, record))
            calls_used += estimated_calls
        except Exception as exc:  # noqa: BLE001 - per-record failures belong in audit, not process crash.
            skipped.append({"case_id": record.get("case_id"), "reason": f"{type(exc).__name__}: {exc}"})
    return {"records": regenerated, "llm_calls_used": calls_used, "skipped": skipped}


def regenerate_record(args: argparse.Namespace, record: dict[str, Any]) -> dict[str, Any]:
    job_id = int(record["job_id"])
    job = db.get_job_posting(job_id)
    if not job:
        raise RuntimeError(f"Job not found: {job_id}")
    profile = db.get_candidate_profile_payload() or {}
    case = build_auto_eval_case(job, profile)
    ranking = ranking_payload_for_job(job_id, args.ranking_version)
    artifact_type = str(record["artifact_type"])

    if artifact_type == "application_materials":
        output = regenerate_materials(args, job, ranking)
        result = evaluate_application_materials(case, output)
    elif artifact_type == "ats_cv":
        output = regenerate_ats_cv(args, job, ranking)
        result = evaluate_ats_cv_result(case, output)
    elif artifact_type == "ranking":
        output = regenerate_ranking(args, job)
        result = evaluate_ranking_result(case, output)
    else:
        raise RuntimeError(f"Unsupported artifact_type for regeneration: {artifact_type}")

    return {
        **record,
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
        "metrics": result.metrics,
        "candidate_output": output,
        "judge_payload": build_llm_judge_payload(case, output, artifact_type),
    }


def regenerate_materials(args: argparse.Namespace, job: dict[str, Any], ranking: dict[str, Any] | None) -> dict[str, Any]:
    model = args.regeneration_model
    if args.regeneration_provider == "openai":
        return build_application_kit_with_llm(job, ranking=ranking, model=model or DEFAULT_MATERIALS_MODEL)
    return build_application_kit_with_nvidia(job, ranking=ranking, model=model or DEFAULT_NVIDIA_MATERIALS_MODEL)


def regenerate_ats_cv(args: argparse.Namespace, job: dict[str, Any], ranking: dict[str, Any] | None) -> dict[str, Any]:
    model = args.regeneration_model
    if args.regeneration_provider == "openai":
        kit = build_application_kit_with_llm(job, ranking=ranking, model=model or DEFAULT_MATERIALS_MODEL)
        return {"ats_cv_text": kit.get("ats_cv_text") or ""}
    generated = build_ats_cv_with_nvidia(job, ranking=ranking, model=model or DEFAULT_NVIDIA_MATERIALS_MODEL)
    return {"ats_cv_text": generated.get("ats_cv_text") or ""}


def regenerate_ranking(args: argparse.Namespace, job: dict[str, Any]) -> dict[str, Any]:
    if args.regeneration_provider != "openai":
        raise RuntimeError("In-memory ranking regeneration currently supports --regeneration-provider openai only.")
    result = rank_job_with_llm(job, model=args.regeneration_model or DEFAULT_LLM_MODEL)
    return result_to_dict(result)


def ranking_payload_for_job(job_id: int, ranking_version: str) -> dict[str, Any] | None:
    rows = db.get_rankings_for_job_ids(ranking_version, [job_id])
    if rows.empty:
        return None
    row = rows.iloc[0].to_dict()
    return {
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row.get("confidence") or 0),
        "scores": loads_json(row.get("scores_json"), {}),
        "evidence": loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": loads_json(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
    }


def loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def estimated_regeneration_calls(artifact_type: str, provider: str) -> int:
    if artifact_type == "application_materials" and provider == "nvidia":
        return 2
    return 1


def surface_for_prompt_target(prompt_target: str) -> str | None:
    mapping = {
        "ranking/nvidia_response_contract": "ranking",
        "materials/nvidia_cv_contract": "ats_cv",
        "materials/nvidia_kit_contract": "application_materials",
    }
    return mapping.get(prompt_target)


def update_prompt_registry(prompt_target: str, version: str) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    env = registry.get("active_environment") or "default"
    registry.setdefault("environments", {}).setdefault(env, {})[prompt_target] = version
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unified_prompt_diff(before: str, after: str, *, from_label: str, to_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
        )
    )


def commit_accepted_patch(prompt_path: Path, issue: str, iteration: int) -> None:
    subprocess.run(
        ["git", "add", "--", str(REGISTRY_PATH.relative_to(PROJECT_ROOT)), str(prompt_path.relative_to(PROJECT_ROOT))],
        cwd=PROJECT_ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"Accept eval loop prompt iteration {iteration}: {issue}"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def is_promotion_allowed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before = promotion_gate_summary(before)
    after = promotion_gate_summary(after)
    excluded_records = int(before.get("promotion_gate_excluded") or 0) + int(after.get("promotion_gate_excluded") or 0)
    if int(after.get("evaluated") or 0) == 0 and excluded_records:
        return False
    if hard_stop_reason(after):
        return False
    if compare_summaries(before, after).get("regressions"):
        return False
    return float(after.get("pass_rate") or 0) >= float(before.get("pass_rate") or 0) and int(
        after.get("failed") or 0
    ) <= int(before.get("failed") or 0)


def promotion_gate_summary(summary: dict[str, Any]) -> dict[str, Any]:
    records = summary.get("records")
    if not isinstance(records, list):
        return summary
    gate_records = [
        record for record in records if str(record.get("review_status") or "").strip() != "needs_human_review"
    ]
    gate_summary = summarize_records(gate_records)
    gate_summary["promotion_gate_excluded"] = len(records) - len(gate_records)
    return gate_summary


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
    if summary.get("case_statuses"):
        return {str(key): bool(value) for key, value in summary["case_statuses"].items()}
    return {
        f"{record.get('artifact_type')}:{record.get('case_id')}": bool(record.get("passed"))
        for record in summary.get("records") or []
    }


def load_previous_audit_summary(output_dir: Path) -> dict[str, Any] | None:
    if not output_dir.exists():
        return None
    audits = sorted(output_dir.glob("eval_loop_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in audits:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        iterations = payload.get("iterations") or []
        if not iterations:
            continue
        latest = iterations[-1]
        summary = dict(latest.get("summary") or {})
        summary["case_statuses"] = latest.get("case_statuses") or {}
        return summary
    return None


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


def judge_issue_keys(record: dict[str, Any]) -> list[str]:
    judge_result = record.get("judge_result")
    if not isinstance(judge_result, dict):
        return []
    issue_codes = judge_result.get("issue_codes") or []
    if not isinstance(issue_codes, list):
        issue_codes = [issue_codes]
    return [issue_key(issue) for issue in issue_codes if str(issue or "").strip()]


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
            "regenerate_affected": args.regenerate_affected,
            "regeneration_provider": args.regeneration_provider,
            "commit_accepted_patches": args.commit_accepted_patches,
            "compare_last_run": not args.no_compare_last_run,
            "golden_cases": str(args.golden_cases),
        },
        "accepted_patches": accepted_patches,
        "iterations": iterations,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
