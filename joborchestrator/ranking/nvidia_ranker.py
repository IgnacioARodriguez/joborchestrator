from __future__ import annotations

import json
import os
import re
import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, cast

import httpx
import pandas as pd

from joborchestrator.llm.provider import NvidiaProvider, ProviderRegistry
from joborchestrator.prompts import active_prompt_version, load_prompt
from joborchestrator.intelligence.profile_trace import profile_trace
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


@dataclass(frozen=True)
class RankingSafetySignal:
    label: str
    decision_cap: Decision
    max_score: int
    risk_penalty: int
    reason: str
    evidence_kind: str = "red_flag"


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
            _apply_nvidia_batch_result(batch, result, ranking_version, summary, model=model)
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
    validation_errors: list[str] = []
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
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_NVIDIA_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning("Retrying NVIDIA ranking batch after invalid response: %s", validation_feedback)
            continue
        logger.warning("NVIDIA ranking batch still invalid after retry; applying valid partial results: %s", validation_feedback)
        parsed["_generation_metadata"] = {
            "validation_attempts": attempt + 1,
            "validation_errors": [*validation_errors, validation_feedback],
        }
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
    validation_errors: list[str] = []
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
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_NVIDIA_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning("Retrying NVIDIA ranking batch after invalid response: %s", validation_feedback)
            continue
        logger.warning("NVIDIA ranking batch still invalid after retry; applying valid partial results: %s", validation_feedback)
        parsed["_generation_metadata"] = {
            "validation_attempts": attempt + 1,
            "validation_errors": [*validation_errors, validation_feedback],
        }
        return parsed
    raise NvidiaRankingError("NVIDIA ranking batch could not be validated.")


def _apply_nvidia_batch_result(
    batch: list[dict[str, Any]],
    result: dict[str, Any] | Exception,
    ranking_version: str,
    summary: dict[str, int],
    *,
    model: str,
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
        safety_context = _active_profile_safety_context()
        generation_metadata = result.get("_generation_metadata") if isinstance(result.get("_generation_metadata"), dict) else {}
        profile_metadata = profile_trace(db.get_candidate_profile_payload())
        prompt_versions = {"ranking/nvidia_response_contract": active_prompt_version("ranking", "nvidia_response_contract")}

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
                _apply_ranking_safety_gate(row, ranking, safety_context)
                _apply_evidence_consistency_gate(ranking)
                db.save_job_ranking(
                    job_id,
                    ranking,
                    ranking_provider="nvidia",
                    ranking_model=model,
                    ranking_prompt_versions=prompt_versions,
                    ranking_validation_attempts=int(generation_metadata.get("validation_attempts") or 1),
                    ranking_validation_errors=list(generation_metadata.get("validation_errors") or []),
                    ranking_candidate_profile_hash=profile_metadata.get("hash"),
                    ranking_candidate_profile_snapshot=profile_metadata.get("snapshot"),
                )
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


_DECISION_SEVERITY = {
    "APPLY_NOW": 0,
    "APPLY_WITH_TAILORED_CV": 1,
    "MAYBE": 2,
    "SKIP": 3,
    "AVOID": 4,
}


def _active_profile_safety_context() -> dict[str, Any]:
    profile_payload = db.get_candidate_profile_payload() or {}
    return {
        "dealbreakers": [
            str(item).strip()
            for item in profile_payload.get("dealbreakers", [])
            if str(item).strip()
        ],
        "preferred_locations": _clean_profile_list(profile_payload.get("preferred_locations")),
        "preferred_work_modes": _clean_profile_list(profile_payload.get("preferred_work_modes")),
        "profile_text": _normalize_text(_flatten_profile_text(profile_payload)),
        "real_experience_years": profile_payload.get("real_experience_years"),
    }


def _apply_ranking_safety_gate(
    job: dict[str, Any],
    ranking: Any,
    safety_context: dict[str, Any],
) -> None:
    signals = _ranking_safety_signals(job, ranking, safety_context)
    if not signals:
        return

    for signal in signals:
        target = ranking.evidence.dealbreakers if signal.evidence_kind == "dealbreaker" else ranking.evidence.red_flags
        if signal.label not in target:
            target.append(signal.label)
        if signal.reason == "hard_override_dealbreaker":
            profile_flag = f"profile dealbreaker: {signal.label}"
            if profile_flag not in ranking.evidence.red_flags:
                ranking.evidence.red_flags.append(profile_flag)
        if signal.reason not in ranking.evidence.llm_escalation_reasons:
            ranking.evidence.llm_escalation_reasons.append(signal.reason)

    most_conservative = max(signals, key=lambda item: _DECISION_SEVERITY[item.decision_cap])
    if _DECISION_SEVERITY[ranking.decision] < _DECISION_SEVERITY[most_conservative.decision_cap]:
        ranking.decision = most_conservative.decision_cap
    ranking.final_score = min(int(ranking.final_score), min(signal.max_score for signal in signals))
    ranking.scores.risk_penalty = max(int(ranking.scores.risk_penalty), max(signal.risk_penalty for signal in signals))
    ranking.evidence.requires_llm_review = True
    prefix = "Safety gate applied: " + "; ".join(signal.label for signal in signals) + "."
    ranking.reasoning_summary = f"{prefix} {ranking.reasoning_summary}".strip()


def _apply_evidence_consistency_gate(ranking: Any) -> None:
    evidence = ranking.evidence
    reasons = list(evidence.llm_escalation_reasons or [])
    review_reasons = [reason for reason in reasons if reason != "nvidia_ranking_applied"]
    has_dealbreakers = bool(evidence.dealbreakers)
    has_red_flags = bool(evidence.red_flags)
    has_missing = bool(evidence.missing_requirements)
    low_coverage = _ranking_central_coverage_percent(ranking) < 80

    if ranking.decision == "APPLY_NOW" and (has_dealbreakers or has_red_flags or has_missing or low_coverage):
        ranking.decision = cast(Decision, "APPLY_WITH_TAILORED_CV")
        ranking.final_score = min(int(ranking.final_score), 78)
        ranking.scores.risk_penalty = max(int(ranking.scores.risk_penalty), 20)
        if "evidence_consistency_cap_apply_now" not in reasons:
            reasons.append("evidence_consistency_cap_apply_now")
        review_reasons.append("evidence_consistency_cap_apply_now")

    if ranking.decision in {"APPLY_WITH_TAILORED_CV", "MAYBE"} and (
        has_dealbreakers or has_red_flags or has_missing or low_coverage or review_reasons
    ):
        evidence.requires_llm_review = True
        if "evidence_requires_review" not in reasons:
            reasons.append("evidence_requires_review")

    evidence.llm_escalation_reasons = reasons


def _ranking_central_coverage_percent(ranking: Any) -> float:
    value = ranking.evidence.central_requirement_coverage
    if value is None:
        value = getattr(ranking.scores, "central_requirement_coverage", None)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 100.0
    return number * 100 if number <= 1 else number


def _ranking_safety_signals(
    job: dict[str, Any],
    ranking: Any,
    safety_context: dict[str, Any],
) -> list[RankingSafetySignal]:
    haystack = _normalized_job_and_ranking_text(job, ranking)
    job_text = _normalized_job_text(job)
    profile_text = str(safety_context.get("profile_text") or "")
    signals: list[RankingSafetySignal] = []

    for item in _triggered_dealbreakers(job, ranking, safety_context.get("dealbreakers") or []):
        signals.append(
            RankingSafetySignal(
                label=item,
                decision_cap=cast(Decision, "AVOID"),
                max_score=20,
                risk_penalty=40,
                reason="hard_override_dealbreaker",
                evidence_kind="dealbreaker",
            )
        )

    if _is_unpaid_or_commission_only(haystack):
        signals.append(
            RankingSafetySignal(
                label="unpaid or commission-only compensation",
                decision_cap=cast(Decision, "AVOID"),
                max_score=20,
                risk_penalty=40,
                reason="hard_override_compensation",
                evidence_kind="dealbreaker",
            )
        )

    if _requires_relocation_without_remote(job_text):
        signals.append(
            RankingSafetySignal(
                label="mandatory relocation without clear remote option",
                decision_cap=cast(Decision, "AVOID"),
                max_score=30,
                risk_penalty=40,
                reason="hard_override_relocation",
                evidence_kind="dealbreaker",
            )
        )

    location_label = _restricted_location_mismatch(job_text, safety_context)
    if location_label:
        signals.append(
            RankingSafetySignal(
                label=location_label,
                decision_cap=cast(Decision, "AVOID"),
                max_score=35,
                risk_penalty=35,
                reason="hard_override_location_restriction",
                evidence_kind="dealbreaker",
            )
        )

    low_context_spam = _is_low_context_spam(job, job_text)
    if low_context_spam:
        signals.append(
            RankingSafetySignal(
                label="low-context or spam-like posting",
                decision_cap=cast(Decision, "SKIP"),
                max_score=25,
                risk_penalty=35,
                reason="safety_cap_low_context",
            )
        )
        signals.append(
            RankingSafetySignal(
                label="generic low-context posting with magic word filter",
                decision_cap=cast(Decision, "SKIP"),
                max_score=25,
                risk_penalty=35,
                reason="safety_cap_low_context",
                evidence_kind="dealbreaker",
            )
        )

    if _contract_ai_training_risk(job_text):
        signals.append(
            RankingSafetySignal(
                label="contract AI training/verification work",
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=70,
                risk_penalty=25,
                reason="safety_cap_contract_ai_training",
                evidence_kind="dealbreaker",
            )
        )

    if _hybrid_seniority_review(job_text, safety_context):
        signals.append(
            RankingSafetySignal(
                label="hybrid role with 6+ years seniority gap",
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=82,
                risk_penalty=20,
                reason="safety_cap_hybrid_seniority_review",
                evidence_kind="dealbreaker",
            )
        )

    india_location_label = _india_remote_location_unclear(job_text, safety_context)
    if india_location_label:
        signals.append(
            RankingSafetySignal(
                label=india_location_label,
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=70,
                risk_penalty=20,
                reason="safety_cap_location_review",
                evidence_kind="dealbreaker",
            )
        )

    madrid_freelance_label = _madrid_freelance_review(job_text)
    if madrid_freelance_label:
        signals.append(
            RankingSafetySignal(
                label=madrid_freelance_label,
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=75,
                risk_penalty=15,
                reason="safety_cap_freelance_location_review",
            )
        )

    if _industrial_automation_mismatch(job_text, profile_text):
        signals.append(
            RankingSafetySignal(
                label="industrial automation/electrical domain mismatch",
                decision_cap=cast(Decision, "AVOID"),
                max_score=35,
                risk_penalty=35,
                reason="hard_override_domain_mismatch",
                evidence_kind="dealbreaker",
            )
        )

    language_gap_label = _required_language_gap_label(job_text, profile_text)
    if language_gap_label:
        signals.append(
            RankingSafetySignal(
                label=language_gap_label,
                decision_cap=cast(Decision, "MAYBE"),
                max_score=55,
                risk_penalty=30,
                reason="safety_cap_language_gap",
                evidence_kind="dealbreaker",
            )
        )

    if _munich_location_review(job_text, safety_context):
        signals.append(
            RankingSafetySignal(
                label="Munich location outside preferred remote/Spain profile",
                decision_cap=cast(Decision, "MAYBE"),
                max_score=55,
                risk_penalty=20,
                reason="safety_cap_location_review",
                evidence_kind="dealbreaker",
            )
        )

    if _security_specialization_gap(job_text, profile_text):
        signals.append(
            RankingSafetySignal(
                label="security specialization outside core profile",
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=68,
                risk_penalty=25,
                reason="safety_cap_specialization_gap",
            )
        )

    if _senior_infrastructure_review(job_text, safety_context):
        signals.append(
            RankingSafetySignal(
                label="senior infrastructure specialization outside core profile",
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=75,
                risk_penalty=20,
                reason="safety_cap_senior_infrastructure_review",
            )
        )

    deep_specialization_label = _deep_specialization_gap(job_text, profile_text)
    if deep_specialization_label:
        cap = (
            cast(Decision, "AVOID")
            if "autonomous driving" in deep_specialization_label
            else cast(Decision, "APPLY_WITH_TAILORED_CV")
        )
        max_score = 35 if cap == "AVOID" else 68
        signals.append(
            RankingSafetySignal(
                label=deep_specialization_label,
                decision_cap=cap,
                max_score=max_score,
                risk_penalty=25,
                reason="safety_cap_specialization_gap",
            )
        )

    if _solutions_architect_pivot(job_text, profile_text):
        signals.append(
            RankingSafetySignal(
                label="solutions architect/presales pivot requires tailoring",
                decision_cap=cast(Decision, "APPLY_WITH_TAILORED_CV"),
                max_score=78,
                risk_penalty=20,
                reason="safety_cap_pivot_role",
            )
        )

    return _dedupe_safety_signals(signals)


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


def _is_unpaid_or_commission_only(haystack: str) -> bool:
    return any(marker in haystack for marker in ["unpaid", "no salary", "without pay", "unremunerated"]) or any(
        marker in haystack for marker in ["commission only", "100% commission", "no base salary"]
    )


def _requires_relocation_without_remote(job_text: str) -> bool:
    if _contains_any(job_text, ["no relocation required", "relocation not required", "without relocation"]):
        return False
    relocation_required = _contains_any(
        job_text,
        [
            "mandatory relocation",
            "required relocation",
            "requires relocation",
            "must relocate",
            "relocation to",
            "relocation package",
            "relocation assistance",
        ],
    )
    if not relocation_required:
        return False
    return not _contains_any(job_text, ["fully remote", "remote anywhere", "remote first", "remote within spain"])


def _restricted_location_mismatch(job_text: str, safety_context: dict[str, Any]) -> str | None:
    preferred_locations = " ".join(str(item) for item in safety_context.get("preferred_locations") or [])
    preferred_work_modes = " ".join(str(item) for item in safety_context.get("preferred_work_modes") or [])
    preference_text = _normalize_text(f"{preferred_locations} {preferred_work_modes}")
    if not preference_text:
        return None
    if "remote" in preference_text and _contains_any(job_text, ["fully remote", "remote anywhere", "remote first"]):
        return None

    restricted_markers = [
        "must be based in",
        "must be located in",
        "candidates must be located",
        "candidates must be based",
        "candidates located in",
        "candidates based in",
        "only candidates in",
        "applicants must be located",
        "applicants must be based",
        "hybrid in",
        "on site in",
        "onsite in",
        "presencial",
    ]
    if not _contains_any(job_text, restricted_markers):
        return None

    outside_locations = [
        "belo horizonte",
        "brazil",
        "brasil",
        "florianopolis",
        "india",
        "munich",
        "germany",
        "finland",
        "houston",
        "navarra",
        "turku",
        "united states",
        "usa",
        "u s ",
    ]
    for location in outside_locations:
        if _contains_location_marker(job_text, location) and location not in preference_text:
            return f"location restriction outside preferences: {location.strip()}"
    return None


def _is_low_context_spam(job: dict[str, Any], job_text: str) -> bool:
    title = _normalize_text(str(job.get("title") or ""))
    description = _normalize_text(str(job.get("description_text") or ""))
    generic_titles = {"apply here", "join our hq", "join our team", "open application"}
    if title in generic_titles:
        return True
    if len(description) < 120 and _contains_any(title, ["apply", "join", "general application"]):
        return True
    return _contains_any(job_text, ["magic word", "anti spam", "prove you read this"]) and len(description) < 800


def _contract_ai_training_risk(job_text: str) -> bool:
    return "contract" in job_text and _contains_any(
        job_text,
        [
            "ai training",
            "train ai",
            "training ai",
            "verify ai",
            "ai verification",
            "evaluate ai",
            "next-generation ai systems",
            "ai systems",
            "ai models learn",
            "shape how ai models",
        ],
    )


def _hybrid_seniority_review(job_text: str, safety_context: dict[str, Any]) -> bool:
    years = safety_context.get("real_experience_years")
    try:
        real_years = float(years)
    except (TypeError, ValueError):
        real_years = 0
    if real_years >= 6:
        return False
    if not _contains_any(job_text, ["hybrid", "hibrido"]):
        return False
    return _contains_any(job_text, ["6+ years", "6 years", "6+ anos", "seniority around 6+"])


def _india_remote_location_unclear(job_text: str, safety_context: dict[str, Any]) -> str | None:
    preferred_locations = _normalize_text(" ".join(str(item) for item in safety_context.get("preferred_locations") or []))
    if "india" in preferred_locations or "india" not in job_text:
        return None
    if _contains_any(job_text, ["locations listed as", "flexible/remote", "flexible / remote"]):
        return "India location/remote eligibility requires review"
    return None


def _madrid_freelance_review(job_text: str) -> str | None:
    if "madrid" in job_text and _contains_any(job_text, ["freelance", "contractor", "contract role"]):
        return "Madrid freelance role requires tailored review"
    return None


def _industrial_automation_mismatch(job_text: str, profile_text: str) -> bool:
    profile_negates_automation = _contains_any(
        profile_text,
        [
            "no industrial automation",
            "no plc",
            "no scada",
            "no robotics",
            "without industrial automation",
        ],
    )
    if not profile_negates_automation and _contains_any(profile_text, ["plc", "scada", "vfd", "statcom", "epc"]):
        return False
    industrial_terms = [
        "plc",
        "scada",
        "vfd",
        "statcom",
        "epc",
        "plant electrical",
        "industrial automation",
        "manufacturing equipment",
        "robotic systems",
        "machinery",
        "automated solutions",
        "production requirements",
        "biofarma",
        "biopharma",
    ]
    role_terms = ["automation engineer", "application engineer", "electrical engineer", "control systems"]
    return _contains_any(job_text, industrial_terms) and _contains_any(job_text, role_terms)


def _required_language_gap_label(job_text: str, profile_text: str) -> str | None:
    profile_negates_german = _contains_any(
        profile_text,
        ["no german", "without german", "german language absent", "not fluent in german"],
    )
    if "german" in profile_text and not profile_negates_german:
        return None
    if _contains_any(
        job_text,
        ["german required", "fluent german", "c1 german", "b2 german", "must speak german", "german language"],
    ):
        return "German language requirement not supported by profile"
    if "german" in job_text:
        return "German language signal not supported by profile"
    return None


def _munich_location_review(job_text: str, safety_context: dict[str, Any]) -> bool:
    preferred_locations = _normalize_text(" ".join(str(item) for item in safety_context.get("preferred_locations") or []))
    if "munich" in preferred_locations or "munich" not in job_text:
        return False
    return not _contains_any(job_text, ["fully remote", "remote anywhere", "remote first"])


def _security_specialization_gap(job_text: str, profile_text: str) -> bool:
    profile_negates_security = _contains_any(
        profile_text,
        ["no core security", "no security", "no cybersecurity", "no appsec", "no devsecops"],
    )
    if not profile_negates_security and _contains_any(profile_text, ["security", "cybersecurity", "devsecops", "appsec"]):
        return False
    if _solutions_architect_pivot(job_text, profile_text):
        return False
    return _contains_any(job_text, ["security engineer", "cybersecurity", "appsec", "devsecops"])


def _senior_infrastructure_review(job_text: str, safety_context: dict[str, Any]) -> bool:
    years = safety_context.get("real_experience_years")
    try:
        real_years = float(years)
    except (TypeError, ValueError):
        real_years = 0
    if real_years >= 6:
        return False
    return _contains_any(
        job_text,
        [
            "senior infrastructure engineer",
            "sr infrastructure engineer",
            "sr. infrastructure engineer",
            "staff infrastructure engineer",
        ],
    )


def _deep_specialization_gap(job_text: str, profile_text: str) -> str | None:
    checks = [
        (
            ["rust kernel", "linux kernel", "device driver", "device drivers"],
            ["rust", "kernel", "device driver"],
            "Rust kernel/device-driver specialization outside core profile",
        ),
        (
            ["autonomous driving", "vehicle simulation", "simulation engineer"],
            ["autonomous", "simulation"],
            "autonomous driving simulation specialization outside core profile",
        ),
        (
            ["erp consultant", "sap consultant", "erp implementation"],
            ["erp", "sap"],
            "ERP implementation specialization outside core profile",
        ),
        (
            ["senior infrastructure engineer", "sr infrastructure engineer", "staff infrastructure engineer"],
            ["infrastructure", "sre", "kubernetes"],
            "senior infrastructure specialization outside core profile",
        ),
    ]
    for job_terms, profile_terms, label in checks:
        if _contains_any(job_text, job_terms) and not _contains_any(profile_text, profile_terms):
            return label
    return None


def _solutions_architect_pivot(job_text: str, profile_text: str) -> bool:
    if _contains_any(profile_text, ["solutions architect", "presales", "sales engineer"]):
        return False
    return _contains_any(job_text, ["solutions architect", "solution architect", "sales engineer", "presales"])


def _dedupe_safety_signals(signals: list[RankingSafetySignal]) -> list[RankingSafetySignal]:
    deduped: list[RankingSafetySignal] = []
    seen = set()
    for signal in signals:
        key = (signal.label, signal.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
    return deduped


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


def _normalized_job_text(job: dict[str, Any]) -> str:
    parts = [
        job.get("title"),
        job.get("company"),
        job.get("location"),
        job.get("workplace_type"),
        job.get("description_text"),
        job.get("data_quality_flags"),
    ]
    return _normalize_text(" ".join(str(part) for part in parts if part))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _contains_any(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


def _contains_location_marker(text: str, marker: str) -> bool:
    normalized = marker.strip()
    if normalized in {"usa", "u s"}:
        return bool(re.search(r"\b(?:usa|u s)\b", text))
    return normalized in text


def _clean_profile_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _flatten_profile_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_profile_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_profile_text(item) for item in value)
    return str(value or "")


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
