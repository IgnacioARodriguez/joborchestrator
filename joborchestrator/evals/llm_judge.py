from __future__ import annotations

import json
import os
from typing import Any

import httpx


DEFAULT_OPENAI_JUDGE_MODEL = os.getenv("OPENAI_EVAL_JUDGE_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"
DEFAULT_NVIDIA_JUDGE_MODEL = (
    os.getenv("NVIDIA_EVAL_JUDGE_MODEL")
    or os.getenv("NVIDIA_MODEL")
    or "nvidia/llama-3.3-nemotron-super-49b-v1"
)
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"


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
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": selected_model,
                "store": False,
                "reasoning": {"effort": "low"},
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict evaluator for job-search LLM outputs. "
                            "Use only the source_case and rubric. Return JSON only."
                        ),
                    },
                    {"role": "user", "content": json.dumps(judge_payload, ensure_ascii=False)},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "llm_eval_judge_result",
                        "strict": True,
                        "schema": _judge_result_schema(),
                    }
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return _normalize_judge_result(json.loads(_extract_openai_text(response.json())))
    except httpx.HTTPError as exc:
        raise LLMJudgeError(f"OpenAI eval judge request failed: {exc}") from exc
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
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
        response = httpx.post(
            f"{NVIDIA_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": selected_model,
                "temperature": 0,
                "top_p": 0.95,
                "max_tokens": int(os.getenv("NVIDIA_EVAL_JUDGE_MAX_TOKENS", "2000")),
                "stream": False,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict evaluator for job-search LLM outputs. "
                            "Use only the source_case and rubric. Return JSON only."
                        ),
                    },
                    {"role": "user", "content": json.dumps(judge_payload, ensure_ascii=False)},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _normalize_judge_result(json.loads(_extract_json_object_text(str(content))))
    except httpx.HTTPError as exc:
        raise LLMJudgeError(f"NVIDIA eval judge request failed: {exc}") from exc
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise LLMJudgeError(f"NVIDIA eval judge returned invalid JSON: {exc}") from exc


def _normalize_judge_result(payload: dict[str, Any]) -> dict[str, Any]:
    issues = payload.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return {
        "passed": bool(payload.get("passed")),
        "score": max(0, min(100, int(payload.get("score") or 0))),
        "issues": [str(issue) for issue in issues],
        "rationale": str(payload.get("rationale") or ""),
    }


def _judge_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["passed", "score", "issues", "rationale"],
        "properties": {
            "passed": {"type": "boolean"},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "issues": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def _extract_openai_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return response["output_text"]
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    raise LLMJudgeError("Eval judge response did not include text output.")


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
