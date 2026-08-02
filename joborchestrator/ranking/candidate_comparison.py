from __future__ import annotations

import json
from typing import Any

import httpx

from joborchestrator.llm.observability import LLMRequestContext
from joborchestrator.llm.provider import LLMProviderError, NvidiaProvider, ProviderRegistry


class CandidateComparisonError(RuntimeError):
    pass


async def compare_job_with_candidate(
    interpretation: dict[str, Any],
    candidate_profile: dict[str, Any],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    client: httpx.AsyncClient,
    batch_id: str,
) -> dict[str, Any]:
    """Compare an already-interpreted job against the candidate profile.

    This stage receives no job-classification policy. It only assesses whether
    the candidate profile supports each signal and preserves uncertainty.
    """
    provider = ProviderRegistry().get(
        "ranking-comparison",
        provider_name="nvidia",
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        http_module=httpx,
    )
    messages = _comparison_messages(interpretation, candidate_profile)
    try:
        response = await provider.acomplete(
            messages,
            model=model,
            client=client,
            temperature=0,
            response_format="json",
            max_tokens=max_tokens,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
            request_context=LLMRequestContext(
                operation="ranking_comparison",
                batch_id=batch_id,
                offer_count=1,
            ),
        )
    except LLMProviderError as exc:
        raise CandidateComparisonError(str(exc)) from exc
    result = _parse_json(response.text)
    _validate_result(result, expected_job_id=interpretation.get("job_id"))
    return result


def _comparison_messages(interpretation: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Compare a job interpretation with a candidate profile. Do not invent evidence. "
                "Absence of evidence is unknown, not missing. Cultural preferences are not blockers. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "For every job evidence signal, return status strong, partial, unknown, or missing. "
                "After interpreting the signal, report its impact as core, preference, or context "
                "and its kind as skill, experience, seniority, role, location, work_mode, language, or other. "
                "Include candidate_evidence, reason, and confidence. Keep the job's interpretation "
                "and evidence separate from your assessment. Use this exact output shape:\n"
                '{"job_id": 0, "assessments": [{"signal": "...", "impact": "core|preference|context", '
                '"kind": "skill|experience|seniority|role|location|work_mode|language|other", '
                '"status": "strong|partial|unknown|missing", "candidate_evidence": [], '
                '"reason": "...", "confidence": 0.0}]}\n\n'
                "JOB INTERPRETATION:\n"
                + json.dumps(interpretation, ensure_ascii=False)
                + "\n\nCANDIDATE PROFILE:\n"
                + json.dumps(profile, ensure_ascii=False)
            ),
        },
    ]


def _parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateComparisonError("Candidate comparison response was not valid JSON.") from exc
    if not isinstance(result, dict):
        raise CandidateComparisonError("Candidate comparison response must be an object.")
    return result


def _validate_result(result: dict[str, Any], *, expected_job_id: Any) -> None:
    if not isinstance(result.get("job_id"), int):
        raise CandidateComparisonError("Candidate comparison requires integer job_id.")
    if expected_job_id is not None and result["job_id"] != int(expected_job_id):
        raise CandidateComparisonError("Candidate comparison job_id mismatch.")
    assessments = result.get("assessments")
    if not isinstance(assessments, list):
        raise CandidateComparisonError("Candidate comparison requires assessments array.")
    valid_statuses = {"strong", "partial", "unknown", "missing"}
    valid_impacts = {"core", "preference", "context"}
    valid_kinds = {"skill", "experience", "seniority", "role", "location", "work_mode", "language", "other"}
    for index, assessment in enumerate(assessments):
        if not isinstance(assessment, dict) or not str(assessment.get("signal") or "").strip():
            raise CandidateComparisonError(f"Assessment {index} requires signal.")
        if assessment.get("status") not in valid_statuses:
            raise CandidateComparisonError(f"Assessment {index} has invalid status.")
        if assessment.get("impact") not in valid_impacts:
            raise CandidateComparisonError(f"Assessment {index} has invalid impact.")
        if assessment.get("kind") not in valid_kinds:
            raise CandidateComparisonError(f"Assessment {index} has invalid kind.")
