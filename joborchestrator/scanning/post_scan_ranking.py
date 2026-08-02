from __future__ import annotations

from collections.abc import Callable
from typing import Any

from joborchestrator.intelligence.profile_trace import profile_trace
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
)
from joborchestrator.ranking.versions import (
    NVIDIA_RANKING_VERSION,
)
from joborchestrator.storage import (
    persistence as db,
)

ProgressCallback = Callable[
    [str],
    None,
]


def queue_post_scan_ranking(
    input_payload: dict[str, Any],
    scan_started_at: str,
    summary: dict[str, Any],
    progress: (
        ProgressCallback | None
    ) = None,
    *,
    included_sources: (
        list[str] | None
    ) = None,
    excluded_sources: (
        list[str] | None
    ) = None,
) -> dict[str, Any]:
    if not input_payload.get(
        "auto_rank_new",
        True,
    ):
        return {
            "queued": 0,
            "skipped": "disabled",
        }

    profile_payload = db.get_candidate_profile_payload()
    if not profile_payload:
        return {
            "queued": 0,
            "skipped": (
                "missing_candidate_profile"
            ),
        }

    changed_count = (
        int(summary.get("new") or 0)
        + int(
            summary.get("updated") or 0
        )
    )

    if changed_count <= 0:
        return {
            "queued": 0,
            "skipped": (
                "no_new_or_updated_jobs"
            ),
        }

    ranking_version = str(
        input_payload.get(
            "ranking_version"
        )
        or NVIDIA_RANKING_VERSION
    )

    limit = max(
        1,
        min(
            int(
                input_payload.get(
                    "ranking_limit"
                )
                or 250
            ),
            2000,
        ),
    )

    candidates = (
        db.get_jobs_for_post_scan_ranking(
            seen_since=scan_started_at,
            ranking_version=(
                ranking_version
            ),
            limit=limit,
            included_sources=(
                included_sources
            ),
            excluded_sources=(
                excluded_sources
            ),
            candidate_profile_hash=profile_trace(profile_payload).get("hash"),
        )
    )

    job_ids = [
        int(value)
        for value
        in candidates["id"].tolist()
    ]

    if not job_ids:
        return {
            "queued": 0,
            "skipped": (
                "no_unranked_scan_jobs"
            ),
        }

    if progress:
        progress(
            "Queueing NVIDIA ranking for "
            f"{len(job_ids)} new or "
            "updated job(s)."
        )

    ranking_job_id = (
        db.create_ranking_job(
            provider="nvidia",
            model=str(
                input_payload.get(
                    "ranking_model"
                )
                or DEFAULT_NVIDIA_MODEL
            ),
            ranking_version=(
                ranking_version
            ),
            job_ids=job_ids,
            request_batch_size=int(
                input_payload.get(
                    "ranking_request_batch_size"
                )
                or (
                    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE
                )
            ),
            max_concurrency=int(
                input_payload.get(
                    "ranking_max_concurrency"
                )
                or (
                    DEFAULT_NVIDIA_MAX_CONCURRENCY
                )
            ),
        )
    )

    ranking_job = db.get_ranking_job(ranking_job_id) or {}
    queued_count = int(ranking_job.get("total_items") or 0)
    return {
        "ranking_job_id": (
            ranking_job_id
        ),
        "queued": queued_count,
        "ranking_version": (
            ranking_version
        ),
    }
