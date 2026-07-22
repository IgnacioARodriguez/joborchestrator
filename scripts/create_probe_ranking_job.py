from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.ranking.nvidia_ranker import DEFAULT_NVIDIA_MODEL  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402

DEFAULT_PROBE_PATH = Path("logs/autoloop_probe_cases.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a small NVIDIA ranking job from selected autoloop probe cases.")
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE_PATH)
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--model", default=DEFAULT_NVIDIA_MODEL)
    parser.add_argument("--category", action="append", default=[], help="Include only cases with this category. Repeatable.")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--request-batch-size", type=int, default=2)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="Actually create the ranking job. Without this, dry-run only.")
    return parser.parse_args(argv)


def selected_job_ids(probe: dict[str, Any], *, categories: list[str], limit: int) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()
    required = set(categories)
    for case in probe.get("cases") or []:
        if not isinstance(case, dict) or case.get("job_id") is None:
            continue
        case_categories = set(str(item) for item in case.get("categories") or [])
        if required and not required.intersection(case_categories):
            continue
        job_id = int(case["job_id"])
        if job_id in seen:
            continue
        selected.append(job_id)
        seen.add(job_id)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def create_probe_job(args: argparse.Namespace) -> dict[str, Any]:
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    job_ids = selected_job_ids(probe, categories=list(args.category or []), limit=int(args.limit))
    response: dict[str, Any] = {
        "dry_run": not args.execute,
        "probe": str(args.probe),
        "selected_job_ids": job_ids,
        "ranking_version": args.ranking_version,
        "model": args.model,
        "request_batch_size": int(args.request_batch_size),
        "max_concurrency": int(args.max_concurrency),
    }
    if args.execute:
        if not job_ids:
            raise ProbeRankingJobError("No probe job ids matched the requested filters.")
        response["ranking_job_id"] = db.create_ranking_job(
            provider="nvidia",
            model=str(args.model),
            ranking_version=str(args.ranking_version),
            job_ids=job_ids,
            request_batch_size=int(args.request_batch_size),
            max_concurrency=int(args.max_concurrency),
        )
    return response


class ProbeRankingJobError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        response = create_probe_job(args)
    except ProbeRankingJobError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
