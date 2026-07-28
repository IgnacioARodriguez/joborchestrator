from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.prompts import active_prompt_version  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute autoloop safety metrics over persisted rankings.")
    parser.add_argument("--ranking-job-id", type=int)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def fetch_ranking_rows(*, ranking_job_id: int | None, ranking_version: str) -> list[dict[str, Any]]:
    conn = db._conn()
    try:
        if ranking_job_id is not None:
            rows = conn.execute(
                """
                SELECT
                    rji.ranking_job_id,
                    rji.job_posting_id AS job_id,
                    rji.status AS item_status,
                    rji.attempts AS item_attempts,
                    rji.started_at AS item_started_at,
                    rji.finished_at AS item_finished_at,
                    jp.title,
                    jp.company,
                    jp.location,
                    jp.source,
                    jr.final_score,
                    jr.decision,
                    jr.confidence,
                    jr.scores_json,
                    jr.evidence_json,
                    jr.ranking_validation_attempts,
                    jr.ranking_validation_errors_json,
                    jr.ranking_prompt_versions_json,
                    jr.updated_at AS ranking_updated_at
                FROM ranking_job_items rji
                JOIN job_postings jp ON jp.id = rji.job_posting_id
                LEFT JOIN job_rankings jr
                  ON jr.job_id = rji.job_posting_id
                 AND jr.ranking_version = ?
                WHERE rji.ranking_job_id = ?
                ORDER BY rji.id ASC
                """,
                (ranking_version, ranking_job_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    NULL AS ranking_job_id,
                    jp.id AS job_id,
                    NULL AS item_status,
                    NULL AS item_attempts,
                    NULL AS item_started_at,
                    NULL AS item_finished_at,
                    jp.title,
                    jp.company,
                    jp.location,
                    jp.source,
                    jr.final_score,
                    jr.decision,
                    jr.confidence,
                    jr.scores_json,
                    jr.evidence_json,
                    jr.ranking_validation_attempts,
                    jr.ranking_validation_errors_json,
                    jr.ranking_prompt_versions_json,
                    jr.updated_at AS ranking_updated_at
                FROM job_rankings jr
                JOIN job_postings jp ON jp.id = jr.job_id
                WHERE jr.ranking_version = ?
                ORDER BY jr.updated_at DESC
                """,
                (ranking_version,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = [row for row in rows if row.get("decision") and row_is_current_for_metrics(row)]
    status_counts = Counter(str(row.get("item_status") or "none") for row in rows)
    failed_items = [row for row in rows if row.get("item_status") == "failed"]
    high_item_attempt_rows = [row for row in rows if int_or_zero(row.get("item_attempts")) > 3]
    max_item_attempts = max([int_or_zero(row.get("item_attempts")) for row in rows], default=0)
    apply_now = [row for row in ranked if row.get("decision") == "APPLY_NOW"]
    unsafe_apply_now = [row for row in apply_now if is_unsafe_apply_now(row)]
    stale_completed = [row for row in rows if is_stale_completion(row)]
    retry_rows = [row for row in ranked if int_or_zero(row.get("ranking_validation_attempts")) > 1 or bool(loads_json(row.get("ranking_validation_errors_json"), []))]
    review_rows = [row for row in ranked if bool(evidence(row).get("requires_llm_review"))]
    soft_dealbreaker_rows = [row for row in ranked if has_soft_decision_with_dealbreaker(row)]
    soft_central_gap_rows = [row for row in ranked if has_soft_decision_with_many_central_gaps(row)]
    inferred_language_rows = [row for row in ranked if has_inferred_language_signal(row)]
    generic_location_rows = [row for row in ranked if has_generic_location_signal(row)]
    scores = [int(row["final_score"]) for row in ranked if row.get("final_score") is not None]
    coverage_values = [coverage for row in ranked if (coverage := central_coverage(row)) is not None]
    active_ranking_prompt = active_prompt_version("ranking", "nvidia_response_contract")
    prompt_versions = Counter(ranking_prompt_version(row) for row in ranked)
    non_active_prompt_rows = [
        row for row in ranked if ranking_prompt_version(row) not in {active_ranking_prompt, "unknown"}
    ]

    return {
        "evaluated_rows": len(rows),
        "item_status_counts": dict(sorted(status_counts.items())),
        "failed_item_count": len(failed_items),
        "high_item_attempt_threshold": 3,
        "high_item_attempt_count": len(high_item_attempt_rows),
        "max_item_attempts": max_item_attempts,
        "ranked_rows": len(ranked),
        "decision_counts": dict(sorted(Counter(str(row.get("decision")) for row in ranked).items())),
        "score": stats(scores),
        "central_requirement_coverage": stats(coverage_values),
        "apply_now_count": len(apply_now),
        "unsafe_apply_now_count": len(unsafe_apply_now),
        "apply_now_unsafe_rate": round(len(unsafe_apply_now) / len(apply_now), 4) if apply_now else 0.0,
        "critical_failures": len(unsafe_apply_now),
        "stale_completion_count": len(stale_completed),
        "retry_or_schema_count": len(retry_rows),
        "schema_failure_retry_rate": round(len(retry_rows) / len(ranked), 4) if ranked else 0.0,
        "review_required_count": len(review_rows),
        "review_required_rate": round(len(review_rows) / len(ranked), 4) if ranked else 0.0,
        "soft_dealbreaker_count": len(soft_dealbreaker_rows),
        "soft_dealbreaker_rate": round(len(soft_dealbreaker_rows) / len(ranked), 4) if ranked else 0.0,
        "soft_central_gap_count": len(soft_central_gap_rows),
        "soft_central_gap_rate": round(len(soft_central_gap_rows) / len(ranked), 4) if ranked else 0.0,
        "inferred_language_signal_count": len(inferred_language_rows),
        "generic_location_signal_count": len(generic_location_rows),
        "active_ranking_prompt_version": active_ranking_prompt,
        "prompt_version_counts": dict(sorted(prompt_versions.items())),
        "non_active_prompt_count": len(non_active_prompt_rows),
        "non_active_prompt_rate": round(len(non_active_prompt_rows) / len(ranked), 4) if ranked else 0.0,
        "unsafe_apply_now_examples": examples(unsafe_apply_now),
        "stale_completion_examples": examples(stale_completed),
        "failed_item_examples": examples(failed_items),
        "high_item_attempt_examples": item_attempt_examples(high_item_attempt_rows),
        "soft_dealbreaker_examples": examples(soft_dealbreaker_rows),
        "soft_central_gap_examples": examples(soft_central_gap_rows),
        "inferred_language_signal_examples": examples(inferred_language_rows),
        "generic_location_signal_examples": examples(generic_location_rows),
        "non_active_prompt_examples": prompt_version_examples(non_active_prompt_rows),
    }


def is_unsafe_apply_now(row: dict[str, Any]) -> bool:
    ev = evidence(row)
    return bool(ev.get("dealbreakers")) or bool(ev.get("red_flags")) or bool(
        ev.get("missing_requirements")
    ) or is_low_central_coverage(row)


def is_low_central_coverage(row: dict[str, Any], *, threshold: float = 80.0) -> bool:
    values = [
        central_coverage(row),
        percent_value(scores(row).get("central_requirement_coverage")),
    ]
    return any(value < threshold for value in values if value is not None)


def has_soft_decision_with_dealbreaker(row: dict[str, Any]) -> bool:
    return row.get("decision") in {"APPLY_WITH_TAILORED_CV", "MAYBE"} and bool(evidence(row).get("dealbreakers"))


def has_soft_decision_with_many_central_gaps(row: dict[str, Any]) -> bool:
    if row.get("decision") not in {"APPLY_WITH_TAILORED_CV", "MAYBE"}:
        return False
    ev = evidence(row)
    missing_count = material_count(ev.get("missing_requirements") or [])
    if missing_count < 3:
        return False
    coverage = central_coverage(row)
    return coverage is not None and coverage < 70


def has_inferred_language_signal(row: dict[str, Any]) -> bool:
    ev = evidence(row)
    return has_evidence_marker(ev, "German language signal not supported by profile")


def has_generic_location_signal(row: dict[str, Any]) -> bool:
    ev = evidence(row)
    return has_evidence_marker(ev, "onsite/hybrid location is not clearly within preferred locations")


def has_evidence_marker(ev: dict[str, Any], marker: str) -> bool:
    marker = marker.lower()
    buckets = [
        ev.get("dealbreakers") or [],
        ev.get("red_flags") or [],
        ev.get("missing_requirements") or [],
    ]
    return any(marker in str(item).lower() for bucket in buckets for item in bucket)


def material_count(items: list[Any]) -> int:
    return sum(1 for item in items if str(item).strip())


def row_is_current_for_metrics(row: dict[str, Any]) -> bool:
    item_status = row.get("item_status")
    return item_status in {None, "", "completed"}


def is_stale_completion(row: dict[str, Any]) -> bool:
    if row.get("item_status") != "completed":
        return False
    ranking_updated_at = str(row.get("ranking_updated_at") or "")
    item_started_at = str(row.get("item_started_at") or "")
    return bool(ranking_updated_at and item_started_at and ranking_updated_at < item_started_at)


def evidence(row: dict[str, Any]) -> dict[str, Any]:
    loaded = loads_json(row.get("evidence_json"), {})
    return loaded if isinstance(loaded, dict) else {}


def scores(row: dict[str, Any]) -> dict[str, Any]:
    loaded = loads_json(row.get("scores_json"), {})
    return loaded if isinstance(loaded, dict) else {}


def ranking_prompt_version(row: dict[str, Any]) -> str:
    payload = loads_json(row.get("ranking_prompt_versions_json"), {})
    if not isinstance(payload, dict):
        return "unknown"
    value = payload.get("ranking/nvidia_response_contract")
    return str(value or "unknown")


def central_coverage(row: dict[str, Any]) -> float | None:
    ev_value = evidence(row).get("central_requirement_coverage")
    score_value = scores(row).get("central_requirement_coverage")
    value = ev_value if ev_value is not None else score_value
    return percent_value(value)


def percent_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number * 100 if number <= 1 else number


def stats(values: list[int | float]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "avg": None, "p50": None, "max": None}
    return {
        "min": min(values),
        "avg": round(float(statistics.mean(values)), 2),
        "p50": round(float(statistics.median(values)), 2),
        "max": max(values),
    }


def examples(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "job_id": int(row["job_id"]),
            "decision": row.get("decision"),
            "final_score": row.get("final_score"),
            "title": row.get("title"),
            "company": row.get("company"),
            "location": row.get("location"),
        }
        for row in rows[:limit]
    ]


def prompt_version_examples(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    items = []
    for row in rows[:limit]:
        item = examples([row], limit=1)[0]
        item["prompt_version"] = ranking_prompt_version(row)
        items.append(item)
    return items


def item_attempt_examples(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: int_or_zero(row.get("item_attempts")), reverse=True)
    items = []
    for row in ordered[:limit]:
        item = examples([row], limit=1)[0]
        item["item_attempts"] = int_or_zero(row.get("item_attempts"))
        item["item_status"] = row.get("item_status")
        item["ranking_validation_attempts"] = int_or_zero(row.get("ranking_validation_attempts"))
        item["ranking_validation_errors"] = loads_json(row.get("ranking_validation_errors_json"), [])
        items.append(item)
    return items


def loads_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = compute_metrics(fetch_ranking_rows(ranking_job_id=args.ranking_job_id, ranking_version=args.ranking_version))
    payload = json.dumps(metrics, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
