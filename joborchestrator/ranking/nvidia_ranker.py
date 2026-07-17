from __future__ import annotations

import json
import os
import re
import asyncio
import logging
from dataclasses import asdict
from typing import Any, Callable, cast

import httpx
import pandas as pd

from joborchestrator.llm.provider import NvidiaProvider, ProviderRegistry
from joborchestrator.prompts import load_prompt
from joborchestrator.ranking.llm_ranker import _ranking_from_payload
from joborchestrator.ranking.ranking_rules import NVIDIA_EXTRA_RULES, RANKING_GOAL, RANKING_RULES, SCORING_RUBRIC
from joborchestrator.ranking.schemas import CandidateProfile, Decision, VALID_DECISIONS
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.storage import persistence as db
from joborchestrator.intelligence.cv_profile_extractor import profile_payload_to_candidate_profile

NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = (
    os.getenv("NVIDIA_RANKING_MODEL")
    or os.getenv("NVIDIA_MODEL")
    or "nvidia/llama-3.3-nemotron-super-49b-v1"
)
DEFAULT_NVIDIA_REQUEST_BATCH_SIZE = int(os.getenv("NVIDIA_RANKING_BATCH_SIZE", "2"))
DEFAULT_NVIDIA_MAX_CONCURRENCY = int(os.getenv("NVIDIA_RANKING_MAX_CONCURRENCY", "1"))
DEFAULT_NVIDIA_MAX_TOKENS = int(os.getenv("NVIDIA_RANKING_MAX_TOKENS", "8192"))
DEFAULT_NVIDIA_TIMEOUT_SECONDS = float(os.getenv("NVIDIA_RANKING_TIMEOUT_SECONDS", "180"))
DEFAULT_NVIDIA_VALIDATION_RETRIES = int(os.getenv("NVIDIA_RANKING_VALIDATION_RETRIES", "1"))
logger = logging.getLogger(__name__)


class NvidiaRankingError(RuntimeError):
    pass


def nvidia_api_key() -> str | None:
    return os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")


def rank_jobs_with_nvidia(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_NVIDIA_MODEL,
    request_batch_size: int = DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
    max_concurrency: int = 1,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    api_key: str | None = None,
    base_url: str = NVIDIA_BASE_URL,
    timeout: float = DEFAULT_NVIDIA_TIMEOUT_SECONDS,
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    return asyncio.run(
        rank_jobs_with_nvidia_async(
            jobs,
            model=model,
            request_batch_size=request_batch_size,
            max_concurrency=max_concurrency,
            ranking_version=ranking_version,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            progress_callback=progress_callback,
        )
    )


async def rank_jobs_with_nvidia_async(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_NVIDIA_MODEL,
    request_batch_size: int = DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
    max_concurrency: int = DEFAULT_NVIDIA_MAX_CONCURRENCY,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    api_key: str | None = None,
    base_url: str = NVIDIA_BASE_URL,
    timeout: float = DEFAULT_NVIDIA_TIMEOUT_SECONDS,
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    key = api_key or nvidia_api_key()
    if not key:
        raise NvidiaRankingError("NVIDIA_API_KEY or NIM_API_KEY is required.")

    summary = {
        "processed": 0,
        "saved": 0,
        "failed": 0,
        "APPLY_NOW": 0,
        "APPLY_WITH_TAILORED_CV": 0,
        "MAYBE": 0,
        "SKIP": 0,
        "AVOID": 0,
    }
    records = jobs.to_dict("records")
    batches = [records[start : start + request_batch_size] for start in range(0, len(records), request_batch_size)]
    semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
    timeout_config = httpx.Timeout(timeout)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        tasks = [
            _rank_nvidia_batch_with_context_async(
                batch,
                model=model,
                api_key=key,
                base_url=base_url,
                timeout=timeout,
                semaphore=semaphore,
                client=client,
            )
            for batch in batches
        ]
        completed_batches = 0
        for task in asyncio.as_completed(tasks):
            batch, result = await task
            completed_batches += 1
            _apply_nvidia_batch_result(batch, result, ranking_version, summary)
            if progress_callback:
                progress_callback(completed_batches, len(batches), dict(summary))
    return summary


def build_nvidia_ranking_payload(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    profile_payload = db.get_candidate_profile_payload()
    if not profile_payload:
        raise NvidiaRankingError("No candidate profile configured. Upload a CV in Profile before running NVIDIA ranking.")
    profile = CandidateProfile(**profile_payload_to_candidate_profile(profile_payload))
    return {
        "candidate_profile": asdict(profile),
        "ranking_goal": RANKING_GOAL,
        "rules": [*RANKING_RULES, *NVIDIA_EXTRA_RULES],
        "scoring_rubric": SCORING_RUBRIC,
        "jobs": [_compact_job(row) for row in jobs],
    }


def _call_nvidia_batch(
    jobs: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    payload = build_nvidia_ranking_payload(jobs)
    validation_feedback: str | None = None
    provider = cast(
        NvidiaProvider,
        ProviderRegistry().get(
            "ranking",
            provider_name="nvidia",
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            http_module=httpx,
        ),
    )
    for attempt in range(DEFAULT_NVIDIA_VALIDATION_RETRIES + 1):
        response = provider.complete(
            _nvidia_messages(payload, validation_feedback=validation_feedback),
            model=model,
            temperature=0,
            response_format="json",
            max_tokens=DEFAULT_NVIDIA_MAX_TOKENS,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
        )
        parsed = _extract_json_object(response.text)
        validation_feedback = _nvidia_batch_validation_error(parsed, jobs)
        if not validation_feedback:
            return parsed
        if attempt < DEFAULT_NVIDIA_VALIDATION_RETRIES:
            logger.warning("Retrying NVIDIA ranking batch after invalid response: %s", validation_feedback)
            continue
        logger.warning("NVIDIA ranking batch still invalid after retry; applying valid partial results: %s", validation_feedback)
        return parsed
    raise NvidiaRankingError("NVIDIA ranking batch could not be validated.")


async def _rank_nvidia_batch_async(
    jobs: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    async with semaphore:
        return await _call_nvidia_batch_async(
            jobs,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            client=client,
        )


async def _rank_nvidia_batch_with_context_async(
    jobs: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], dict[str, Any] | Exception]:
    try:
        result = await _rank_nvidia_batch_async(
            jobs,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            semaphore=semaphore,
            client=client,
        )
        return jobs, result
    except Exception as exc:  # noqa: BLE001 - batch-level failures are summarized, not raised.
        return jobs, exc


async def _call_nvidia_batch_async(
    jobs: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    payload = build_nvidia_ranking_payload(jobs)
    validation_feedback: str | None = None
    provider = cast(
        NvidiaProvider,
        ProviderRegistry().get(
            "ranking",
            provider_name="nvidia",
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        ),
    )
    for attempt in range(DEFAULT_NVIDIA_VALIDATION_RETRIES + 1):
        response = await provider.acomplete(
            _nvidia_messages(payload, validation_feedback=validation_feedback),
            model=model,
            client=client,
            temperature=0,
            response_format="json",
            max_tokens=DEFAULT_NVIDIA_MAX_TOKENS,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
        )
        parsed = _extract_json_object(response.text)
        validation_feedback = _nvidia_batch_validation_error(parsed, jobs)
        if not validation_feedback:
            return parsed
        if attempt < DEFAULT_NVIDIA_VALIDATION_RETRIES:
            logger.warning("Retrying NVIDIA ranking batch after invalid response: %s", validation_feedback)
            continue
        logger.warning("NVIDIA ranking batch still invalid after retry; applying valid partial results: %s", validation_feedback)
        return parsed
    raise NvidiaRankingError("NVIDIA ranking batch could not be validated.")


def _apply_nvidia_batch_result(
    batch: list[dict[str, Any]],
    result: dict[str, Any] | Exception,
    ranking_version: str,
    summary: dict[str, int],
) -> None:
    summary["processed"] += len(batch)
    if isinstance(result, Exception):
        logger.warning("NVIDIA ranking batch failed before parsing: %s", _exception_summary(result))
        summary["failed"] += len(batch)
        return
    try:
        rankings = result.get("rankings")
        if not isinstance(rankings, list):
            raise NvidiaRankingError("NVIDIA response did not include `rankings` list.")
        by_id = {int(item["job_id"]): item for item in rankings if isinstance(item, dict) and item.get("job_id")}
        expected_ids = [int(row.get("id") or row.get("job_id")) for row in batch]
        missing = sorted(set(expected_ids) - set(by_id))
        if missing:
            logger.warning("NVIDIA response is missing job_id values: %s", missing)
        active_dealbreakers = _active_profile_dealbreakers()

        for row in batch:
            job_id = int(row.get("id") or row.get("job_id"))
            if job_id not in by_id:
                summary["failed"] += 1
                continue
            try:
                if _decision_score_inconsistent(
                    by_id[job_id].get("decision"),
                    by_id[job_id].get("final_score"),
                ):
                    raise ValueError("decision/score mismatch")
                ranking = _ranking_from_payload(by_id[job_id], ranking_version)
                ranking.evidence.requires_llm_review = False
                reasons = list(ranking.evidence.llm_escalation_reasons or [])
                if "nvidia_ranking_applied" not in reasons:
                    reasons.append("nvidia_ranking_applied")
                ranking.evidence.llm_escalation_reasons = reasons
                ranking.ranking_version = ranking_version
                _apply_hard_override_gate(row, ranking, active_dealbreakers)
                db.save_job_ranking(job_id, ranking)
                summary["saved"] += 1
                summary[ranking.decision] += 1
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("NVIDIA ranking payload for job_id=%s could not be saved: %s", job_id, exc)
                summary["failed"] += 1
    except (KeyError, ValueError, json.JSONDecodeError, httpx.HTTPError, NvidiaRankingError):
        logger.warning("NVIDIA ranking batch response could not be applied.", exc_info=True)
        summary["failed"] += len(batch)


def _nvidia_chat_body(payload: dict[str, Any], model: str, validation_feedback: str | None = None) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "top_p": 0.95,
        "max_tokens": DEFAULT_NVIDIA_MAX_TOKENS,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": _nvidia_messages(payload, validation_feedback=validation_feedback),
    }


def _nvidia_messages(payload: dict[str, Any], validation_feedback: str | None = None) -> list[dict[str, Any]]:
    user_content = _response_contract() + "\n\nContext:\n" + json.dumps(payload, ensure_ascii=False)
    if validation_feedback:
        user_content += (
            "\n\nYour previous response was rejected because: "
            f"{validation_feedback}\nReturn a corrected complete JSON object only."
        )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict job-ranking evaluator. Return only JSON that matches the requested shape. "
                "The objective is fast hiring probability for this candidate, not generic job quality."
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _response_contract() -> str:
    return load_prompt("ranking", "nvidia_response_contract")


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise NvidiaRankingError("Could not find JSON object in NVIDIA response.")
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise NvidiaRankingError("NVIDIA response JSON must be an object.")
    return parsed


def _nvidia_batch_validation_error(result: dict[str, Any], jobs: list[dict[str, Any]]) -> str | None:
    rankings = result.get("rankings")
    if not isinstance(rankings, list):
        return "response must include a `rankings` array"

    expected_ids = sorted({int(row.get("id") or row.get("job_id")) for row in jobs})
    returned_ids = sorted(
        {
            int(item["job_id"])
            for item in rankings
            if isinstance(item, dict) and item.get("job_id") is not None
        }
    )
    missing_ids = sorted(set(expected_ids) - set(returned_ids))
    invalid_decisions = sorted(
        {
            str(item.get("decision"))
            for item in rankings
            if isinstance(item, dict) and str(item.get("decision")) not in VALID_DECISIONS
        }
    )
    inconsistent_decisions = sorted(
        {
            int(item.get("job_id"))
            for item in rankings
            if isinstance(item, dict)
            and item.get("job_id") is not None
            and _decision_score_inconsistent(item.get("decision"), item.get("final_score"))
        }
    )
    problems = []
    if missing_ids:
        problems.append(f"missing job_id values {missing_ids}")
    if invalid_decisions:
        problems.append(f"invalid decision values {invalid_decisions}")
    if inconsistent_decisions:
        problems.append(f"decision/score mismatch for job_id values {inconsistent_decisions}")
    return "; ".join(problems) if problems else None


def _decision_score_inconsistent(decision: Any, score: Any) -> bool:
    try:
        numeric_score = int(score)
    except (TypeError, ValueError):
        return True
    if decision == "APPLY_NOW":
        return numeric_score < 65
    if decision == "APPLY_WITH_TAILORED_CV":
        return numeric_score < 50
    return False


def _active_profile_dealbreakers() -> list[str]:
    profile_payload = db.get_candidate_profile_payload() or {}
    return [
        str(item).strip()
        for item in profile_payload.get("dealbreakers", [])
        if str(item).strip()
    ]


def _apply_hard_override_gate(
    job: dict[str, Any],
    ranking: Any,
    active_dealbreakers: list[str],
) -> None:
    triggered = _triggered_dealbreakers(job, ranking, active_dealbreakers)
    if not triggered:
        return
    for item in triggered:
        if item not in ranking.evidence.dealbreakers:
            ranking.evidence.dealbreakers.append(item)
        flag = f"profile dealbreaker: {item}"
        if flag not in ranking.evidence.red_flags:
            ranking.evidence.red_flags.append(flag)
    reason = "hard_override_dealbreaker"
    if reason not in ranking.evidence.llm_escalation_reasons:
        ranking.evidence.llm_escalation_reasons.append(reason)
    ranking.decision = cast(Decision, "AVOID")
    ranking.final_score = min(int(ranking.final_score), 20)
    ranking.scores.risk_penalty = 40
    prefix = f"Forced AVOID because profile dealbreaker(s) matched: {', '.join(triggered)}."
    ranking.reasoning_summary = f"{prefix} {ranking.reasoning_summary}".strip()


def _triggered_dealbreakers(
    job: dict[str, Any],
    ranking: Any,
    active_dealbreakers: list[str],
) -> list[str]:
    haystack = _normalized_job_and_ranking_text(job, ranking)
    triggered = []
    for dealbreaker in active_dealbreakers:
        normalized = _normalize_text(dealbreaker)
        if _dealbreaker_matches(normalized, haystack):
            triggered.append(dealbreaker)
    return triggered


def _dealbreaker_matches(dealbreaker: str, haystack: str) -> bool:
    if not dealbreaker:
        return False
    if "unpaid" in dealbreaker:
        return any(marker in haystack for marker in ["unpaid", "no salary", "without pay", "unremunerated"])
    if "commission" in dealbreaker:
        return any(marker in haystack for marker in ["commission only", "commission-only", "100% commission"])
    if "relocation" in dealbreaker:
        requires_relocation = "relocation" in haystack and any(
            marker in haystack
            for marker in ["mandatory", "required", "requires", "must relocate", "relocation package"]
        )
        has_exception = any(marker in haystack for marker in ["remote", "spain", "espana", "eu", "europe", "hybrid"])
        return requires_relocation and not has_exception
    return dealbreaker in haystack


def _normalized_job_and_ranking_text(job: dict[str, Any], ranking: Any) -> str:
    parts = [
        job.get("title"),
        job.get("company"),
        job.get("location"),
        job.get("workplace_type"),
        job.get("description_text"),
        ranking.reasoning_summary,
        ranking.recommended_application_angle,
        *ranking.evidence.dealbreakers,
        *ranking.evidence.red_flags,
        *ranking.evidence.missing_requirements,
    ]
    return _normalize_text(" ".join(str(part) for part in parts if part))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _exception_summary(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response_text = exc.response.text[:1000] if exc.response is not None else ""
        return (
            f"{type(exc).__name__}: status={exc.response.status_code} "
            f"url={exc.request.url} body={response_text!r}"
        )
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__}: url={exc.request.url} detail={exc!r}"
    return f"{type(exc).__name__}: {exc!r}"


def _compact_job(job: dict[str, Any], max_description_chars: int = 6000) -> dict[str, Any]:
    keys = [
        "id",
        "job_id",
        "title",
        "company",
        "location",
        "workplace_type",
        "source",
        "url",
        "apply_url",
        "description_text",
        "posted_at",
        "posted_at_raw",
        "first_seen_at",
        "last_seen_at",
        "parse_confidence",
        "data_quality_flags",
    ]
    compact = {key: job.get(key) for key in keys if job.get(key) is not None}
    job_id = compact.get("job_id") or compact.get("id")
    if job_id is not None:
        compact["job_id"] = int(job_id)
    description = str(compact.get("description_text") or "")
    if len(description) > max_description_chars:
        compact["description_text"] = description[:max_description_chars] + "\n[truncated]"
    return compact
