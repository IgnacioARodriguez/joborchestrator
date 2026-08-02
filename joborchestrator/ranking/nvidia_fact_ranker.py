from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, cast

import httpx
import pandas as pd

from joborchestrator.intelligence.profile_trace import profile_trace
from joborchestrator.llm.provider import LLMProviderError, NvidiaProvider, ProviderRegistry
from joborchestrator.prompts import active_prompt_version, load_prompt
from joborchestrator.ranking.decision_engine import parse_job_facts, rank_job_facts
from joborchestrator.ranking.candidate_comparison import compare_job_with_candidate
from joborchestrator.llm.observability import LLMRequestContext
from joborchestrator.storage import persistence as db

logger = logging.getLogger(__name__)


class NvidiaFactRankingError(RuntimeError):
    pass


def rank_jobs_with_nvidia_facts(
    jobs: pd.DataFrame,
    *,
    model: str,
    request_batch_size: int,
    max_concurrency: int,
    ranking_version: str,
    api_key: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    validation_retries: int,
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    return asyncio.run(
        rank_jobs_with_nvidia_facts_async(
            jobs,
            model=model,
            request_batch_size=request_batch_size,
            max_concurrency=max_concurrency,
            ranking_version=ranking_version,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_tokens=max_tokens,
            validation_retries=validation_retries,
            progress_callback=progress_callback,
        )
    )


async def rank_jobs_with_nvidia_facts_async(
    jobs: pd.DataFrame,
    *,
    model: str,
    request_batch_size: int,
    max_concurrency: int,
    ranking_version: str,
    api_key: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    validation_retries: int,
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    if not api_key:
        raise NvidiaFactRankingError("NVIDIA_API_KEY or NIM_API_KEY is required.")

    records = jobs.to_dict("records")
    batch_size = max(1, int(request_batch_size))
    batches = [records[start : start + batch_size] for start in range(0, len(records), batch_size)]
    summary = _empty_summary()
    semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
    timeout_config = httpx.Timeout(timeout)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        tasks = [
            _extract_batch_with_context(
                batch,
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_tokens=max_tokens,
                validation_retries=validation_retries,
                semaphore=semaphore,
                client=client,
            )
            for batch in batches
        ]
        completed = 0
        for task in asyncio.as_completed(tasks):
            batch, response = await task
            completed += 1
            _apply_fact_batch_result(
                batch,
                response,
                ranking_version=ranking_version,
                model=model,
                summary=summary,
            )
            if progress_callback:
                progress_callback(completed, len(batches), dict(summary))
    return summary


def build_nvidia_fact_payload(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"jobs": [_compact_job(row) for row in jobs]}


async def _extract_batch_with_context(
    batch: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    validation_retries: int,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], dict[str, Any] | Exception]:
    try:
        async with semaphore:
            response = await _call_fact_extraction_async(
                batch,
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_tokens=max_tokens,
                validation_retries=validation_retries,
                client=client,
            )
        return batch, response
    except Exception as exc:  # noqa: BLE001 - batch failures are persisted in the summary.
        return batch, exc


async def _call_fact_extraction_async(
    jobs: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    validation_retries: int,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
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
    payload = build_nvidia_fact_payload(jobs)
    validation_errors: list[str] = []
    feedback: str | None = None

    for attempt in range(max(0, int(validation_retries)) + 1):
        try:
            response = await provider.acomplete(
                _fact_messages(payload, validation_feedback=feedback),
                model=model,
                client=client,
                temperature=0,
                response_format="json",
                max_tokens=max_tokens,
                top_p=0.95,
                frequency_penalty=0,
                presence_penalty=0,
                request_context=LLMRequestContext(
                    operation="ranking",
                    batch_id=f"ranking-{int(jobs[0].get('id') or 0)}",
                    offer_count=len(jobs),
                ),
            )
        except LLMProviderError as exc:
            raise NvidiaFactRankingError(str(exc)) from exc
        parsed = _extract_json_object(response.text)
        parsed = _normalize_interpretation(parsed)
        feedback = _fact_batch_validation_error(parsed, jobs)
        if feedback is None:
            profile_payload = db.get_candidate_profile_payload()
            if not profile_payload:
                raise NvidiaFactRankingError("No candidate profile configured. Upload a CV before ranking.")
            for item in parsed.get("jobs") or []:
                comparison = await compare_job_with_candidate(
                    item,
                    profile_payload,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    client=client,
                    batch_id=f"comparison-{int(item.get('job_id') or 0)}",
                )
                assessments = {
                    str(assessment.get("signal")): assessment
                    for assessment in comparison.get("assessments") or []
                    if isinstance(assessment, dict)
                }
                comparison_items = [
                    assessment
                    for assessment in comparison.get("assessments") or []
                    if isinstance(assessment, dict)
                ]
                for index, requirement in enumerate(item.get("requirements") or []):
                    assessment = assessments.get(str(requirement.get("id") or ""))
                    if assessment is None and index < len(comparison_items):
                        assessment = comparison_items[index]
                    if assessment is not None:
                        requirement["comparison_confidence"] = assessment.get("confidence")
                        requirement["comparison_status"] = assessment.get("status")
                        requirement["kind"] = assessment.get("kind") or requirement.get("kind")
                        requirement["importance"] = {
                            "core": "required",
                            "preference": "preferred",
                            "context": "context",
                        }.get(assessment.get("impact"), requirement.get("importance", "context"))
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        validation_errors.append(feedback)
        if attempt < int(validation_retries):
            logger.warning("Retrying NVIDIA fact extraction after invalid response: %s", feedback)

    raise NvidiaFactRankingError("NVIDIA fact extraction failed validation: " + "; ".join(validation_errors))


def _apply_fact_batch_result(
    batch: list[dict[str, Any]],
    result: dict[str, Any] | Exception,
    *,
    ranking_version: str,
    model: str,
    summary: dict[str, int],
) -> None:
    summary["processed"] += len(batch)
    if isinstance(result, Exception):
        logger.warning("NVIDIA fact extraction batch failed: %s", result)
        summary["failed"] += len(batch)
        return

    extracted = result.get("jobs")
    if not isinstance(extracted, list):
        summary["failed"] += len(batch)
        return
    facts_by_id = {
        int(item["job_id"]): item
        for item in extracted
        if isinstance(item, dict) and item.get("job_id") is not None
    }
    profile_payload = db.get_candidate_profile_payload()
    if not profile_payload:
        raise NvidiaFactRankingError("No candidate profile configured. Upload a CV before ranking.")
    profile_metadata = profile_trace(profile_payload)
    generation = result.get("_generation_metadata") if isinstance(result.get("_generation_metadata"), dict) else {}
    prompt_versions = {
        "ranking/nvidia_fact_contract": active_prompt_version("ranking", "nvidia_fact_contract")
    }

    for row in batch:
        job_id = int(row.get("id") or row.get("job_id"))
        facts_payload = facts_by_id.get(job_id)
        if facts_payload is None:
            summary["failed"] += 1
            continue
        try:
            facts = parse_job_facts(facts_payload, expected_job_id=job_id)
            ranking = rank_job_facts(
                row,
                facts,
                profile_payload,
                ranking_version=ranking_version,
            )
            db.save_job_ranking(
                job_id,
                ranking,
                ranking_provider="nvidia",
                ranking_model=model,
                ranking_prompt_versions=prompt_versions,
                ranking_validation_attempts=int(generation.get("validation_attempts") or 1),
                ranking_validation_errors=list(generation.get("validation_errors") or []),
                ranking_candidate_profile_hash=profile_metadata.get("hash"),
                ranking_candidate_profile_snapshot=profile_metadata.get("snapshot"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Deterministic ranking failed for job_id=%s: %s", job_id, exc)
            summary["failed"] += 1
            continue
        summary["saved"] += 1
        summary[ranking.decision] += 1


def _fact_messages(
    payload: dict[str, Any],
    *,
    validation_feedback: str | None = None,
) -> list[dict[str, Any]]:
    # Experimental extraction path: expose the raw posting and remove the
    # semantic classification instructions. The JSON shape remains only
    # because the downstream deterministic ranker consumes structured facts.
    user_content = (
        "Read and interpret the raw job posting as an experienced recruiter. "
        "Do not compare a candidate, calculate a score, or decide whether someone should apply. "
        "Return JSON only with one result per input job. First explain your interpretation "
        "in a free-form interpretation field. Then list evidence-backed signals, preserving "
        "the nuance of the posting. Do not use required, preferred, blocking, or any other "
        "predefined importance policy. Preserve the exact input job id. The response MUST have "
        "this technical envelope: {\"jobs\":[{\"job_id\":894,\"interpretation\":\"...\","
        "\"evidence\":[{\"text\":\"...\",\"source\":\"...\",\"analysis\":\"...\",\"confidence\":0.0}]}]}. "
        "Use an empty evidence array only when the posting has no actionable facts. "
        "For coverage, enumerate every explicit material fact from the posting: technologies "
        "and tools, programming languages, responsibilities, experience, seniority, domain "
        "knowledge, language, location or work mode, compensation, contract, and stated "
        "nice-to-haves. Do not collapse several distinct technologies or requirements into "
        "a generic phrase such as 'strong engineering skills'."
        + "\n\nRaw job posting:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    if validation_feedback:
        user_content += (
            "\n\nThe previous response failed structural validation: "
            + validation_feedback
            + "\nReturn the complete corrected JSON object only."
        )
    return [
        {
            "role": "system",
            "content": (
                "Extract structured job facts only. Do not compare a candidate, score fit, "
                "choose a decision, or recommend an application action. Return JSON only."
            ),
        },
        {"role": "user", "content": user_content},
    ]


def _normalize_interpretation(result: dict[str, Any]) -> dict[str, Any]:
    """Convert the model's free interpretation into the ranker's stable shape."""
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        return result
    normalized: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        requirements: list[dict[str, Any]] = []
        values = item.get("evidence") or []
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str):
                    text = value.strip()
                    evidence = text
                    confidence = 0.7
                    analysis = ""
                elif isinstance(value, dict):
                    text = str(value.get("text") or value.get("requirement") or "").strip()
                    evidence = str(value.get("evidence") or text).strip()
                    confidence = value.get("confidence", 0.7)
                    analysis = str(value.get("analysis") or "").strip()
                else:
                    continue
                if not text:
                    continue
                requirements.append({
                    "id": f"evidence_{index + 1}",
                    "text": text,
                    "kind": "other",
                    "importance": "context",
                    "blocking": False,
                    "blocking_basis": "unclear",
                    "evidence": evidence + (f" Interpretation: {analysis}" if analysis else ""),
                    "confidence": confidence,
                })
        normalized.append({
            "job_id": item.get("job_id"),
            "interpretation": item.get("interpretation"),
            "posting": item.get("posting") or {},
            "requirements": requirements,
            "application_effort": item.get("application_effort") or {"level": "medium", "evidence": []},
            "data_quality": item.get("data_quality") or {"score": 0.65, "source_reliability": 0.65},
            "extraction_confidence": item.get("extraction_confidence", 0.7),
        })
    return {**result, "jobs": normalized}


def _fact_batch_validation_error(result: dict[str, Any], jobs: list[dict[str, Any]]) -> str | None:
    items = result.get("jobs")
    if not isinstance(items, list):
        return "response must include a top-level jobs array"
    expected_ids = {int(row.get("id") or row.get("job_id")) for row in jobs}
    returned_ids: set[int] = set()
    problems: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"index {index} must be an object")
            continue
        try:
            parsed = parse_job_facts(item)
        except (TypeError, ValueError) as exc:
            problems.append(f"index {index}: {exc}")
            continue
        if parsed.job_id in returned_ids:
            problems.append(f"duplicate job_id {parsed.job_id}")
        returned_ids.add(parsed.job_id)
    missing = sorted(expected_ids - returned_ids)
    unexpected = sorted(returned_ids - expected_ids)
    if missing:
        problems.append(f"missing job_id values {missing}")
    if unexpected:
        problems.append(f"unexpected job_id values {unexpected}")
    return "; ".join(problems) if problems else None


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise NvidiaFactRankingError("Could not find JSON object in NVIDIA response.")
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise NvidiaFactRankingError("NVIDIA fact extraction response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise NvidiaFactRankingError("NVIDIA fact extraction response must be a JSON object.")
    return parsed


def _compact_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or row.get("job_id")),
        "title": row.get("title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "workplace_type": row.get("workplace_type"),
        "description_text": row.get("description_text"),
        "salary_min": row.get("salary_min"),
        "salary_max": row.get("salary_max"),
        "salary_currency": row.get("salary_currency"),
        "apply_type": row.get("apply_type"),
        "source": row.get("source"),
        "data_quality_flags": row.get("data_quality_flags"),
    }


def _empty_summary() -> dict[str, int]:
    return {
        "processed": 0,
        "saved": 0,
        "failed": 0,
        "APPLY_NOW": 0,
        "APPLY_WITH_TAILORED_CV": 0,
        "MAYBE": 0,
        "SKIP": 0,
        "AVOID": 0,
    }
