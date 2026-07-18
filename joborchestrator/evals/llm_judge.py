from __future__ import annotations

import json
import os
from typing import Any

import httpx

from joborchestrator.llm.provider import LLMProviderError, ProviderRegistry


DEFAULT_OPENAI_JUDGE_MODEL = os.getenv("OPENAI_EVAL_JUDGE_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"
DEFAULT_NVIDIA_JUDGE_MODEL = (
    os.getenv("NVIDIA_EVAL_JUDGE_MODEL")
    or os.getenv("NVIDIA_MODEL")
    or "nvidia/llama-3.3-nemotron-super-49b-v1"
)
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
JUDGE_ISSUE_CODES = [
    "unsupported_claims",
    "missing_job_specificity",
    "ats_cv_contains_internal_notes",
    "omitted_base_experience",
    "recruiter_message_cover_letter_style",
    "missing_evidence_terms",
    "apply_now_with_expected_dealbreaker",
    "missing_required_keywords",
    "unsafe_cv_keyword_emphasis",
    "invalid_decision",
    "judge_disputed",
    "judge_other",
]


class LLMJudgeError(RuntimeError):
    pass


def judge_with_openai(
    judge_payload: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise LLMJudgeError("OPENAI_API_KEY is required to run the OpenAI eval judge.")
    selected_model = model or DEFAULT_OPENAI_JUDGE_MODEL
    try:
        provider = ProviderRegistry().get(
            "judge",
            provider_name="openai",
            api_key=key,
            timeout=timeout,
            http_module=httpx,
        )
        response = provider.complete(
            _judge_messages(judge_payload),
            model=selected_model,
            response_format="json",
            response_schema=_judge_result_schema(),
            schema_name="llm_eval_judge_result",
        )
        return _normalize_judge_result(json.loads(response.text))
    except LLMProviderError as exc:
        raise LLMJudgeError(f"OpenAI eval judge request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMJudgeError(f"OpenAI eval judge returned invalid JSON: {exc}") from exc


def judge_with_nvidia(
    judge_payload: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
    if not key:
        raise LLMJudgeError("NVIDIA_API_KEY or NIM_API_KEY is required to run the NVIDIA eval judge.")
    selected_model = model or DEFAULT_NVIDIA_JUDGE_MODEL
    try:
        provider = ProviderRegistry().get(
            "judge",
            provider_name="nvidia",
            api_key=key,
            base_url=NVIDIA_BASE_URL,
            timeout=timeout,
            http_module=httpx,
        )
        response = provider.complete(
            _judge_messages(judge_payload),
            model=selected_model,
            temperature=0,
            response_format="json",
            max_tokens=int(os.getenv("NVIDIA_EVAL_JUDGE_MAX_TOKENS", "2000")),
            top_p=0.95,
        )
        return _normalize_judge_result(json.loads(_extract_json_object_text(response.text)))
    except LLMProviderError as exc:
        raise LLMJudgeError(f"NVIDIA eval judge request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMJudgeError(f"NVIDIA eval judge returned invalid JSON: {exc}") from exc


def judge_with_provider(
    judge_payload: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    selected_provider = (provider or ProviderRegistry().provider_name_for_role("judge")).strip().lower()
    if selected_provider == "openai":
        return judge_with_openai(judge_payload, model=model, timeout=timeout or 60.0)
    if selected_provider == "nvidia":
        return judge_with_nvidia(judge_payload, model=model, timeout=timeout or 120.0)
    raise LLMJudgeError(f"Unsupported eval judge provider: {selected_provider}")


def judge_with_configured_providers(
    judge_payload: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    secondary_provider: str | None = None,
    secondary_model: str | None = None,
) -> dict[str, Any]:
    registry = ProviderRegistry()
    primary_provider = (provider or registry.provider_name_for_role("judge")).strip().lower()
    primary = judge_with_provider(judge_payload, provider=primary_provider, model=model)

    configured_secondary = secondary_provider
    if configured_secondary is None:
        configured_secondary = registry.provider_name_for_role("judge_secondary")
    secondary_name = (configured_secondary or "").strip().lower()
    if not secondary_name:
        return {**primary, "disputed": False, "judge_provider": primary_provider}

    secondary = judge_with_provider(judge_payload, provider=secondary_name, model=secondary_model)
    disputed = bool(primary["passed"]) != bool(secondary["passed"])
    if not disputed:
        return {
            **primary,
            "disputed": False,
            "judge_provider": primary_provider,
            "secondary_judge_provider": secondary_name,
            "secondary_judge_result": secondary,
        }

    issue_codes = sorted({*primary.get("issue_codes", []), *secondary.get("issue_codes", []), "judge_disputed"})
    issues = sorted({*primary.get("issues", []), *secondary.get("issues", []), *issue_codes})
    return {
        **primary,
        "passed": False,
        "disputed": True,
        "issue_codes": issue_codes,
        "issues": issues,
        "judge_provider": primary_provider,
        "secondary_judge_provider": secondary_name,
        "primary_judge_result": primary,
        "secondary_judge_result": secondary,
        "rationale": (
            "Primary and secondary judges disagreed on pass/fail. "
            f"Primary={primary_provider}:{primary['passed']} secondary={secondary_name}:{secondary['passed']}."
        ),
    }


def _judge_messages(judge_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a strict evaluator for job-search LLM outputs. "
                "Use only the source_case and rubric. Return JSON only. "
                "Map every failure to issue_codes from the provided enum; use judge_other only when no code fits."
            ),
        },
        {"role": "user", "content": json.dumps(judge_payload, ensure_ascii=False)},
    ]


def _normalize_judge_result(payload: dict[str, Any]) -> dict[str, Any]:
    issues = payload.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    issue_codes = payload.get("issue_codes") or []
    if not isinstance(issue_codes, list):
        issue_codes = [str(issue_codes)]
    normalized_codes = _normalize_issue_codes(issue_codes)
    merged_issues = [str(issue) for issue in issues]
    for code in normalized_codes:
        if code not in merged_issues:
            merged_issues.append(code)
    return {
        "passed": bool(payload.get("passed")),
        "score": max(0, min(100, int(payload.get("score") or 0))),
        "issue_codes": normalized_codes,
        "issues": merged_issues,
        "rationale": str(payload.get("rationale") or ""),
    }


def _judge_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["passed", "score", "issue_codes", "issues", "rationale"],
        "properties": {
            "passed": {"type": "boolean"},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "issue_codes": {"type": "array", "items": {"type": "string", "enum": JUDGE_ISSUE_CODES}},
            "issues": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def _extract_json_object_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)
    return cleaned[start : end + 1]


def _normalize_issue_codes(issue_codes: list[Any]) -> list[str]:
    valid = set(JUDGE_ISSUE_CODES)
    normalized: list[str] = []
    seen: set[str] = set()
    for issue_code in issue_codes:
        code = str(issue_code).split(":", 1)[0].strip()
        if not code:
            continue
        if code not in valid:
            code = "judge_other"
        if code not in seen:
            seen.add(code)
            normalized.append(code)
    return normalized
