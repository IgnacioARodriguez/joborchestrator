from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.prompts import active_prompt_version  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402
from scripts.compute_autoloop_metrics import fetch_ranking_rows, ranking_prompt_version  # noqa: E402

DEFAULT_OUTPUT = Path("logs/requeue_non_active_prompt_items.json")
PROMPT_KEY = "ranking/nvidia_response_contract"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Requeue completed ranking items produced by a non-active prompt.")
    parser.add_argument("--ranking-job-id", type=int, required=True)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def non_active_prompt_job_ids(rows: list[dict[str, Any]], *, active_version: str) -> list[int]:
    selected = []
    for row in rows:
        if row.get("item_status") != "completed":
            continue
        version = ranking_prompt_version(row)
        if version in {active_version, "unknown"}:
            continue
        selected.append(int(row["job_id"]))
    return selected


def build_requeue_payload(args: argparse.Namespace) -> dict[str, Any]:
    active_version = active_prompt_version("ranking", "nvidia_response_contract")
    rows = fetch_ranking_rows(ranking_job_id=args.ranking_job_id, ranking_version=args.ranking_version)
    job_ids = non_active_prompt_job_ids(rows, active_version=active_version)
    if args.limit is not None:
        job_ids = job_ids[: max(0, int(args.limit))]
    return {
        "ranking_job_id": args.ranking_job_id,
        "ranking_version": args.ranking_version,
        "prompt_key": PROMPT_KEY,
        "active_prompt_version": active_version,
        "candidate_count": len(job_ids),
        "job_ids": job_ids,
        "execute": bool(args.execute),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_requeue_payload(args)
    requeued = 0
    if args.execute and payload["job_ids"]:
        requeued = db.requeue_ranking_items(
            args.ranking_job_id,
            list(payload["job_ids"]),
            reason="Requeued because ranking prompt version is no longer active.",
            statuses=("completed",),
        )
    payload["requeued"] = requeued
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    payload = run(parse_args(argv))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
