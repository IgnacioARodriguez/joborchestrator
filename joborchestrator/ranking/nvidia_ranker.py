from __future__ import annotations

import json
import os
import re
import asyncio
from dataclasses import asdict
from typing import Any

import httpx
import pandas as pd

from joborchestrator.ranking.llm_ranker import _apply_guards, _ranking_from_payload
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION
from joborchestrator.storage import persistence as db

NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = (
    os.getenv("NVIDIA_RANKING_MODEL")
    or os.getenv("NVIDIA_MODEL")
    or "nvidia/llama-3.3-nemotron-super-49b-v1"
)


class NvidiaRankingError(RuntimeError):
    pass


def nvidia_api_key() -> str | None:
    return os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")


def rank_jobs_with_nvidia(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_NVIDIA_MODEL,
    request_batch_size: int = 5,
    max_concurrency: int = 1,
    ranking_version: str = SPEED_RANKING_VERSION,
    api_key: str | None = None,
    base_url: str = NVIDIA_BASE_URL,
    timeout: float = 90.0,
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
        )
    )


async def rank_jobs_with_nvidia_async(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_NVIDIA_MODEL,
    request_batch_size: int = 5,
    max_concurrency: int = 3,
    ranking_version: str = SPEED_RANKING_VERSION,
    api_key: str | None = None,
    base_url: str = NVIDIA_BASE_URL,
    timeout: float = 90.0,
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
            _rank_nvidia_batch_async(
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
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for batch, result in zip(batches, results, strict=True):
        summary["processed"] += len(batch)
        if isinstance(result, Exception):
            summary["failed"] += len(batch)
            continue
        try:
            rankings = result.get("rankings")
            if not isinstance(rankings, list):
                raise NvidiaRankingError("NVIDIA response did not include `rankings` list.")
            by_id = {int(item["job_id"]): item for item in rankings if isinstance(item, dict) and item.get("job_id")}
            expected_ids = [int(row.get("id") or row.get("job_id")) for row in batch]
            missing = sorted(set(expected_ids) - set(by_id))
            if missing:
                raise NvidiaRankingError(f"NVIDIA response is missing job_id: {missing}")

            for row in batch:
                job_id = int(row.get("id") or row.get("job_id"))
                ranking = _ranking_from_payload(by_id[job_id], ranking_version)
                ranking.evidence.requires_llm_review = False
                reasons = list(ranking.evidence.llm_escalation_reasons or [])
                if "nvidia_ranking_applied" not in reasons:
                    reasons.append("nvidia_ranking_applied")
                ranking.evidence.llm_escalation_reasons = reasons
                ranking = _apply_guards(ranking, row)
                ranking.ranking_version = ranking_version
                db.save_job_ranking(job_id, ranking)
                summary["saved"] += 1
                summary[ranking.decision] += 1
        except (KeyError, ValueError, json.JSONDecodeError, httpx.HTTPError, NvidiaRankingError):
            summary["failed"] += len(batch)
    return summary


def build_nvidia_ranking_payload(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    profile = load_candidate_profile()
    return {
        "candidate_profile": asdict(profile),
        "ranking_goal": (
            "Prioritize jobs where the candidate has the highest probability of getting hired quickly. "
            "This is not a salary, prestige or dream-job ranking."
        ),
        "rules": [
            "Evaluate each job independently.",
            "Use raw job text as source of truth; do not invent candidate skills or job requirements.",
            "Central mandatory requirements dominate the score.",
            "Generic matches such as Git, Agile, cloud, testing or communication cannot rescue a job whose main stack/domain is outside the profile.",
            "Technical Consultant, Presales and Solutions Engineer are viable only when backend/API/integration transfer is explicit.",
            "Pure sales, unrelated domains, unpaid, commission-only or critical dealbreakers must be capped at SKIP/AVOID.",
            "Return one result for every input job_id.",
            "Return only valid JSON. No markdown.",
        ],
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
    body = _nvidia_chat_body(payload, model)
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json_object(content)


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
    body = _nvidia_chat_body(payload, model)
    response = await client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json_object(content)


def _nvidia_chat_body(payload: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "top_p": 0.95,
        "max_tokens": 4096,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict job-ranking evaluator. Return only JSON that matches the requested shape. "
                    "The objective is fast hiring probability for this candidate, not generic job quality."
                ),
            },
            {
                "role": "user",
                "content": _response_contract() + "\n\nContext:\n" + json.dumps(payload, ensure_ascii=False),
            },
        ],
    }


def _response_contract() -> str:
    return """
Return exactly:
{
  "rankings": [
    {
      "job_id": 123,
      "final_score": 0,
      "decision": "APPLY_NOW | APPLY_WITH_TAILORED_CV | MAYBE | SKIP | AVOID",
      "confidence": 0.0,
      "scores": {
        "technical_fit": 0,
        "seniority_fit": 0,
        "role_fit": 0,
        "opportunity_quality": 0,
        "application_roi": 0,
        "market_alignment": 0,
        "risk_penalty": 0,
        "speed_signal": 0,
        "technical_readiness": 0,
        "central_requirement_coverage": 0,
        "role_confidence": 0,
        "application_effort_signal": 0,
        "data_quality_signal": 0,
        "source_reliability_signal": 0
      },
      "evidence": {
        "strong_matches": [],
        "partial_matches": [],
        "missing_requirements": [],
        "nice_to_have_matches": [],
        "dealbreakers": [],
        "red_flags": [],
        "central_requirement_coverage": 0.0,
        "central_requirement_raw_coverage": 0.0,
        "central_requirement_evidence_quality": 0.0,
        "requirement_backed_signal_count": 0,
        "central_requirement_thresholds": {},
        "central_requirements": [],
        "requires_llm_review": false,
        "llm_escalation_reasons": []
      },
      "reasoning_summary": "short explanation",
      "recommended_application_angle": "short positioning",
      "cv_keywords_to_emphasize": [],
      "cv_keywords_to_avoid_overclaiming": []
    }
  ]
}
""".strip()


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
