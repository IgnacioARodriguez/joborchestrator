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
    apply_now = [row for row in ranked if row.get("decision") == "APPLY_NOW"]
    unsafe_apply_now = [row for row in apply_now if is_unsafe_apply_now(row)]
    stale_completed = [row for row in rows if is_stale_completion(row)]
    retry_rows = [row for row in ranked if int_or_zero(row.get("ranking_validation_attempts")) > 1 or bool(loads_json(row.get("ranking_validation_errors_json"), []))]
    review_rows = [row for row in ranked if bool(evidence(row).get("requires_llm_review"))]
    scores = [int(row["final_score"]) for row in ranked if row.get("final_score") is not None]
    coverage_values = [coverage for row in ranked if (coverage := central_coverage(row)) is not None]

    return {
        "evaluated_rows": len(rows),
        "item_status_counts": dict(sorted(Counter(str(row.get("item_status") or "none") for row in rows).items())),
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
        "unsafe_apply_now_examples": examples(unsafe_apply_now),
        "stale_completion_examples": examples(stale_completed),
    }


def is_unsafe_apply_now(row: dict[str, Any]) -> bool:
    ev = evidence(row)
    score_payload = scores(row)
    return bool(ev.get("dealbreakers")) or bool(ev.get("red_flags")) or bool(ev.get("missing_requirements")) or (
        (central_coverage(row) or 100) < 80
    ) or float(score_payload.get("central_requirement_coverage") or 100) < 80


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


def central_coverage(row: dict[str, Any]) -> float | None:
    ev_value = evidence(row).get("central_requirement_coverage")
    score_value = scores(row).get("central_requirement_coverage")
    value = ev_value if ev_value is not None else score_value
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
