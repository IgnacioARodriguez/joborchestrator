from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402
from scripts.compute_autoloop_metrics import (  # noqa: E402
    central_coverage,
    evidence,
    is_low_central_coverage,
    is_unsafe_apply_now,
    loads_json,
    scores,
)
from scripts.run_golden_baseline import (  # noqa: E402
    DEFAULT_GOLDEN_CASES_DIR,
    parse_args as parse_golden_args,
    run_golden_baseline,
)

DEFAULT_CONFIG_PATH = Path("config/autoloop_config.json")
DEFAULT_KNOWN_HARD_CASES = Path("config/autoloop_known_hard_cases.json")
DEFAULT_OUTPUT = Path("logs/autoloop_probe_cases.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select a small, stratified autoloop probe set without reranking.")
    parser.add_argument("--ranking-job-id", type=int)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--target-total", type=int)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--known-hard-cases", type=Path, default=DEFAULT_KNOWN_HARD_CASES)
    parser.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def fetch_candidate_rows(*, ranking_job_id: int | None, ranking_version: str) -> list[dict[str, Any]]:
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
                    rji.error AS item_error,
                    rji.started_at AS item_started_at,
                    rji.finished_at AS item_finished_at,
                    jp.title,
                    jp.company,
                    jp.location,
                    jp.source,
                    jp.description_text,
                    jr.id AS ranking_id,
                    jr.final_score,
                    jr.decision,
                    jr.confidence,
                    jr.scores_json,
                    jr.evidence_json,
                    jr.ranking_validation_attempts,
                    jr.ranking_validation_errors_json,
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
                    NULL AS item_error,
                    NULL AS item_started_at,
                    NULL AS item_finished_at,
                    jp.title,
                    jp.company,
                    jp.location,
                    jp.source,
                    jp.description_text,
                    jr.id AS ranking_id,
                    jr.final_score,
                    jr.decision,
                    jr.confidence,
                    jr.scores_json,
                    jr.evidence_json,
                    jr.ranking_validation_attempts,
                    jr.ranking_validation_errors_json,
                    jr.updated_at AS ranking_updated_at
                FROM job_postings jp
                LEFT JOIN job_rankings jr
                  ON jr.job_id = jp.id
                 AND jr.ranking_version = ?
                WHERE jp.is_active = 1
                ORDER BY jp.last_seen_at DESC, jp.id DESC
                LIMIT 500
                """,
                (ranking_version,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def select_probe_cases(
    rows: list[dict[str, Any]],
    *,
    target_total: int,
    category_quotas: dict[str, int],
    golden_failure_ids: set[int],
    known_hard_cases: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for category in classify_probe_categories(row, golden_failure_ids, known_hard_cases):
            by_category[category].append(row)

    for category, quota in category_quotas.items():
        for row in sorted(by_category.get(category, []), key=probe_priority, reverse=True):
            job_id = int(row["job_id"])
            if job_id in seen:
                continue
            selected.append(probe_record(row, golden_failure_ids, known_hard_cases))
            seen.add(job_id)
            if sum(1 for item in selected if category in item["categories"]) >= int(quota):
                break

    if len(selected) < target_total:
        for row in sorted(rows, key=probe_priority, reverse=True):
            job_id = int(row["job_id"])
            if job_id in seen:
                continue
            selected.append(probe_record(row, golden_failure_ids, known_hard_cases))
            seen.add(job_id)
            if len(selected) >= target_total:
                break
    return selected[:target_total]


def classify_probe_categories(
    row: dict[str, Any],
    golden_failure_ids: set[int],
    known_hard_cases: dict[int, dict[str, Any]],
) -> list[str]:
    categories: list[str] = []
    job_id = int(row["job_id"])
    ev = evidence(row)
    decision = str(row.get("decision") or "")
    score = int(row.get("final_score") or 0)

    if job_id in golden_failure_ids or job_id in known_hard_cases:
        categories.append("golden_failure")
    if decision == "APPLY_NOW" and is_unsafe_apply_now(row):
        categories.append("suspicious_apply_now")
    if ev.get("dealbreakers") or ev.get("red_flags"):
        categories.append("risk_evidence")
    if 55 <= score <= 80:
        categories.append("borderline")
    if is_low_central_coverage(row):
        categories.append("low_central_coverage")
    if int(row.get("ranking_validation_attempts") or 0) > 1 or bool(loads_json(row.get("ranking_validation_errors_json"), [])):
        categories.append("retry_or_schema")
    if row.get("item_status") == "queued":
        categories.append("queued")
    if not categories:
        categories.append("general")
    return categories


def probe_record(
    row: dict[str, Any],
    golden_failure_ids: set[int],
    known_hard_cases: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    job_id = int(row["job_id"])
    ev = evidence(row)
    sc = scores(row)
    hard_case = known_hard_cases.get(job_id)
    return {
        "job_id": job_id,
        "categories": classify_probe_categories(row, golden_failure_ids, known_hard_cases),
        "known_hard_case": hard_case,
        "item_status": row.get("item_status"),
        "source": row.get("source"),
        "company": row.get("company"),
        "title": row.get("title"),
        "location": row.get("location"),
        "current_ranking": {
            "has_ranking": bool(row.get("ranking_id")),
            "decision": row.get("decision"),
            "final_score": row.get("final_score"),
            "confidence": row.get("confidence"),
            "central_requirement_coverage": central_coverage(row),
            "score_central_requirement_coverage": sc.get("central_requirement_coverage"),
            "requires_llm_review": bool(ev.get("requires_llm_review")),
            "dealbreakers": ev.get("dealbreakers") or [],
            "red_flags": ev.get("red_flags") or [],
            "missing_requirements": ev.get("missing_requirements") or [],
            "ranking_validation_attempts": row.get("ranking_validation_attempts"),
        },
        "description_preview": compact_text(row.get("description_text"), limit=320),
    }


def probe_priority(row: dict[str, Any]) -> tuple:
    decision = str(row.get("decision") or "")
    score = int(row.get("final_score") or 0)
    ev = evidence(row)
    risk_count = len(ev.get("dealbreakers") or []) + len(ev.get("red_flags") or []) + len(ev.get("missing_requirements") or [])
    queued_bonus = 1 if row.get("item_status") == "queued" else 0
    apply_bonus = 2 if decision == "APPLY_NOW" else 0
    retry_bonus = 1 if int(row.get("ranking_validation_attempts") or 0) > 1 else 0
    return (apply_bonus, queued_bonus, risk_count, retry_bonus, score)


def golden_failure_ids(golden_cases: Path, ranking_version: str) -> set[int]:
    args = parse_golden_args(
        [
            "--golden-cases",
            str(golden_cases),
            "--ranking-version",
            ranking_version,
            "--artifact",
            "ranking",
            "--include-records",
        ]
    )
    summary = run_golden_baseline(args)
    return {int(record["job_id"]) for record in summary.get("records", []) if not record.get("passed")}


def load_known_hard_cases(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        return {}
    return {int(case["job_id"]): dict(case) for case in cases if isinstance(case, dict) and case.get("job_id") is not None}


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    target_total = int(args.target_total or config.get("probe_target_total") or 20)
    category_quotas = dict(config.get("probe_category_quotas") or {})
    known_hard = load_known_hard_cases(args.known_hard_cases)
    failures = golden_failure_ids(args.golden_cases, args.ranking_version)
    rows = fetch_candidate_rows(ranking_job_id=args.ranking_job_id, ranking_version=args.ranking_version)
    cases = select_probe_cases(
        rows,
        target_total=target_total,
        category_quotas=category_quotas,
        golden_failure_ids=failures,
        known_hard_cases=known_hard,
    )
    payload = {
        "ranking_job_id": args.ranking_job_id,
        "ranking_version": args.ranking_version,
        "target_total": target_total,
        "candidate_count": len(cases),
        "protected_fixture_policy": "This selector reads golden fixtures but never writes evals/fixtures.",
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "candidate_count": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
