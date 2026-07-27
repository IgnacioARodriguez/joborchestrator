from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking import nvidia_ranker  # noqa: E402
from joborchestrator.ranking.llm_ranker import _ranking_from_payload  # noqa: E402
from joborchestrator.ranking.serialization import result_to_dict  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402

DEFAULT_REVALIDATION_DECISIONS = ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply current deterministic ranking safety gates to persisted rankings."
    )
    parser.add_argument("--ranking-job-id", type=int, required=True)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument(
        "--decision",
        action="append",
        dest="decisions",
        default=None,
        help=(
            "Decision to revalidate. Repeatable. Defaults to APPLY_NOW and "
            "APPLY_WITH_TAILORED_CV, the optimistic decisions safety gates can downgrade."
        ),
    )
    parser.add_argument("--execute", action="store_true", help="Persist changed rankings.")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def fetch_rows(*, ranking_job_id: int, ranking_version: str, decisions: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in decisions)
    conn = db._conn()
    try:
        rows = conn.execute(
            f"""
            SELECT
                jp.id AS job_id,
                jp.title,
                jp.company,
                jp.location,
                jp.workplace_type,
                jp.description_text,
                jp.data_quality_flags,
                jr.final_score,
                jr.decision,
                jr.confidence,
                jr.scores_json,
                jr.evidence_json,
                jr.reasoning_summary,
                jr.recommended_application_angle,
                jr.cv_keywords_to_emphasize_json,
                jr.cv_keywords_to_avoid_overclaiming_json,
                jr.ranking_version,
                jr.ranking_provider,
                jr.ranking_model,
                jr.ranking_prompt_versions_json,
                jr.ranking_validation_attempts,
                jr.ranking_validation_errors_json,
                jr.ranking_candidate_profile_hash,
                jr.ranking_candidate_profile_snapshot_json
            FROM ranking_job_items rji
            JOIN job_postings jp ON jp.id = rji.job_posting_id
            JOIN job_rankings jr
              ON jr.job_id = jp.id
             AND jr.ranking_version = ?
            WHERE rji.ranking_job_id = ?
              AND rji.status = 'completed'
              AND jr.decision IN ({placeholders})
            ORDER BY jr.final_score DESC, jp.id ASC
            """,
            (ranking_version, ranking_job_id, *decisions),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def revalidate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safety_context = nvidia_ranker._active_profile_safety_context()
    changed: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for row in rows:
        ranking = ranking_from_row(row)
        before = result_to_dict(ranking)
        nvidia_ranker._apply_ranking_safety_gate(job_from_row(row), ranking, safety_context)
        nvidia_ranker._apply_profile_backed_evidence_terms(job_from_row(row), ranking, safety_context)
        nvidia_ranker._apply_evidence_consistency_gate(ranking)
        after = result_to_dict(ranking)
        summary = change_summary(row, before, after)
        if before == after:
            unchanged.append(summary)
        else:
            summary["ranking"] = ranking
            changed.append(summary)
    return changed, unchanged


def persist_changes(changes: list[dict[str, Any]]) -> None:
    for change in changes:
        row = change["row"]
        ranking = change["ranking"]
        db.save_job_ranking(
            int(row["job_id"]),
            ranking,
            ranking_provider=row.get("ranking_provider"),
            ranking_model=row.get("ranking_model"),
            ranking_prompt_versions=loads_json(row.get("ranking_prompt_versions_json"), None),
            ranking_validation_attempts=int_or_none(row.get("ranking_validation_attempts")),
            ranking_validation_errors=loads_json(row.get("ranking_validation_errors_json"), None),
            ranking_candidate_profile_hash=row.get("ranking_candidate_profile_hash"),
            ranking_candidate_profile_snapshot=loads_json(
                row.get("ranking_candidate_profile_snapshot_json"), None
            ),
        )


def ranking_from_row(row: dict[str, Any]) -> Any:
    payload = {
        "job_id": int(row["job_id"]),
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row["confidence"]),
        "scores": loads_json(row.get("scores_json"), {}),
        "evidence": loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": loads_json(
            row.get("cv_keywords_to_avoid_overclaiming_json"), []
        ),
    }
    return _ranking_from_payload(payload, str(row["ranking_version"]))


def job_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["job_id"],
        "job_id": row["job_id"],
        "title": row.get("title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "workplace_type": row.get("workplace_type"),
        "description_text": row.get("description_text"),
        "data_quality_flags": row.get("data_quality_flags"),
    }


def change_summary(row: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_evidence = before.get("evidence") if isinstance(before.get("evidence"), dict) else {}
    after_evidence = after.get("evidence") if isinstance(after.get("evidence"), dict) else {}
    before_reasons = set(before_evidence.get("llm_escalation_reasons") or [])
    after_reasons = set(after_evidence.get("llm_escalation_reasons") or [])
    before_red_flags = set(before_evidence.get("red_flags") or [])
    after_red_flags = set(after_evidence.get("red_flags") or [])
    before_dealbreakers = set(before_evidence.get("dealbreakers") or [])
    after_dealbreakers = set(after_evidence.get("dealbreakers") or [])
    return {
        "job_id": int(row["job_id"]),
        "title": row.get("title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "before": {
            "decision": before.get("decision"),
            "final_score": before.get("final_score"),
            "requires_llm_review": before_evidence.get("requires_llm_review"),
        },
        "after": {
            "decision": after.get("decision"),
            "final_score": after.get("final_score"),
            "requires_llm_review": after_evidence.get("requires_llm_review"),
        },
        "added_red_flags": sorted(after_red_flags - before_red_flags),
        "added_dealbreakers": sorted(after_dealbreakers - before_dealbreakers),
        "added_escalation_reasons": sorted(after_reasons - before_reasons),
        "row": row,
    }


def public_change(change: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in change.items() if key not in {"row", "ranking"}}


def loads_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    decisions = args.decisions or DEFAULT_REVALIDATION_DECISIONS
    rows = fetch_rows(
        ranking_job_id=args.ranking_job_id,
        ranking_version=args.ranking_version,
        decisions=decisions,
    )
    changed, unchanged = revalidate_rows(rows)
    if args.execute:
        persist_changes(changed)

    payload = {
        "mode": "execute" if args.execute else "dry_run",
        "ranking_job_id": args.ranking_job_id,
        "ranking_version": args.ranking_version,
        "decisions": decisions,
        "checked_count": len(rows),
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
        "changes": [public_change(change) for change in changed],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
