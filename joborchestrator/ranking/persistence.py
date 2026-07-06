from __future__ import annotations

from typing import Iterable

import pandas as pd

from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION, rank_job_speed
from joborchestrator.storage import persistence as db


def rank_and_save_jobs(
    jobs: pd.DataFrame,
    profile_path: str | None = None,
    use_llm: bool = False,
    model: str | None = None,
) -> dict[str, int]:
    profile = load_candidate_profile(profile_path)
    summary = {decision: 0 for decision in ["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"]}
    for row in jobs.to_dict("records"):
        ranking = rank_job_speed(row, profile, use_llm_fallback=use_llm, model=model)
        db.save_job_ranking(int(row["id"]), ranking)
        summary[ranking.decision] += 1
    return summary


def rank_unranked_jobs(
    limit: int = 500,
    use_llm: bool = False,
    model: str | None = None,
    ranking_version: str = SPEED_RANKING_VERSION,
) -> dict[str, int]:
    jobs = db.get_unranked_jobs(ranking_version=ranking_version, limit=limit)
    return rank_and_save_jobs(jobs, use_llm=use_llm, model=model)


def rerank_all_jobs(limit: int = 1000, use_llm: bool = False, model: str | None = None) -> dict[str, int]:
    jobs = db.get_job_postings(limit=limit)
    return rank_and_save_jobs(jobs, use_llm=use_llm, model=model)


def rerank_selected_jobs(
    job_ids: Iterable[int],
    use_llm: bool = False,
    model: str | None = None,
) -> dict[str, int]:
    rows = []
    for job_id in job_ids:
        job = db.get_job_posting(int(job_id))
        if job:
            rows.append(job)
    return rank_and_save_jobs(pd.DataFrame(rows), use_llm=use_llm, model=model)
