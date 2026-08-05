from __future__ import annotations

import os
from typing import Any, Callable

import pandas as pd

from joborchestrator.ranking import nvidia_ranker as legacy_ranker
from joborchestrator.ranking.nvidia_fact_ranker import (
    NvidiaFactRankingError,
    rank_jobs_with_nvidia_facts,
)
from joborchestrator.ranking.versions import NVIDIA_DETERMINISTIC_RANKING_VERSION
from joborchestrator.ranking.llm_ranker import LLMRankingError, rank_job_with_llm
from joborchestrator.storage import persistence as db

DEFAULT_NVIDIA_MODEL = legacy_ranker.DEFAULT_NVIDIA_MODEL
DEFAULT_NVIDIA_REQUEST_BATCH_SIZE = legacy_ranker.DEFAULT_NVIDIA_REQUEST_BATCH_SIZE
DEFAULT_NVIDIA_MAX_CONCURRENCY = legacy_ranker.DEFAULT_NVIDIA_MAX_CONCURRENCY
DEFAULT_NVIDIA_MAX_TOKENS = legacy_ranker.DEFAULT_NVIDIA_MAX_TOKENS
DEFAULT_NVIDIA_TIMEOUT_SECONDS = legacy_ranker.DEFAULT_NVIDIA_TIMEOUT_SECONDS
DEFAULT_NVIDIA_VALIDATION_RETRIES = legacy_ranker.DEFAULT_NVIDIA_VALIDATION_RETRIES
NVIDIA_BASE_URL = legacy_ranker.NVIDIA_BASE_URL
NvidiaRankingError = legacy_ranker.NvidiaRankingError
DEFAULT_RANKING_MODEL = os.getenv("OPENROUTER_MODEL") or "openai/gpt-4o-mini"


def rank_jobs(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_NVIDIA_MODEL,
    request_batch_size: int = DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
    max_concurrency: int = DEFAULT_NVIDIA_MAX_CONCURRENCY,
    ranking_version: str,
    api_key: str | None = None,
    base_url: str = NVIDIA_BASE_URL,
    timeout: float = DEFAULT_NVIDIA_TIMEOUT_SECONDS,
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
    provider_name: str = "nvidia",
) -> dict[str, int]:
    if _uses_deterministic_facts(ranking_version):
        key = api_key or (os.getenv("OPENROUTER_API_KEY") if provider_name == "openrouter" else legacy_ranker.nvidia_api_key())
        if not key:
            raise NvidiaRankingError("NVIDIA_API_KEY or NIM_API_KEY is required.")
        try:
            return rank_jobs_with_nvidia_facts(
                jobs,
                model=model,
                request_batch_size=request_batch_size,
                max_concurrency=max_concurrency,
                ranking_version=ranking_version,
                api_key=key,
                base_url=None if provider_name == "openrouter" else base_url,
                timeout=timeout,
                max_tokens=DEFAULT_NVIDIA_MAX_TOKENS,
                validation_retries=DEFAULT_NVIDIA_VALIDATION_RETRIES,
                progress_callback=progress_callback,
                provider_name=provider_name,
            )
        except NvidiaFactRankingError as exc:
            raise NvidiaRankingError(str(exc)) from exc
    return legacy_ranker.rank_jobs_with_nvidia(
        jobs,
        model=model,
        request_batch_size=request_batch_size,
        max_concurrency=max_concurrency,
        ranking_version=ranking_version,
        api_key=api_key,
        base_url=None if provider_name == "openrouter" else base_url,
        timeout=timeout,
        progress_callback=progress_callback,
        provider_name=provider_name,
    )


# Compatibility alias for integrations that still import the old provider name.
rank_jobs_with_nvidia = rank_jobs


def _uses_deterministic_facts(ranking_version: Any) -> bool:
    return str(ranking_version or "").startswith(NVIDIA_DETERMINISTIC_RANKING_VERSION)
