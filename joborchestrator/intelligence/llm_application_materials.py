from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from io import BytesIO
from typing import Any

import httpx

from joborchestrator.intelligence.llm_costs import estimate_application_kit_tokens, estimate_cost
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranker import result_to_dict

DEFAULT_MATERIALS_MODEL = os.getenv("OPENAI_MATERIALS_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"


class LLMMaterialsError(RuntimeError):
    pass


def estimate_materials_cost(
    job_count: int,
    model: str = DEFAULT_MATERIALS_MODEL,
    *,
    batch: bool = False,
    avg_description_chars: int = 7000,
) -> float:
    input_tokens, output_tokens = estimate_application_kit_tokens(job_count, avg_description_chars)
    return estimate_cost(input_tokens, output_tokens, model, batch=batch)


def build_application_kit_with_llm(
    job: Any,
    ranking: Any | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> dict[str, str]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise LLMMaterialsError("OPENAI_API_KEY is required to generate materials with API.")

    profile = load_candidate_profile()
    payload = {
        "candidate_profile": asdict(profile),
        "job": _compact_job(_to_dict(job)),
        "ranking": result_to_dict(ranking) if ranking is not None else None,
        "goal": (
            "Generate truthful, editable application materials for this specific job. "
            "Optimize for ATS filters and fast application workflow without inventing experience."
        ),
        "rules": [
            "Do not invent employers, degrees, certifications, years of experience, tools or projects.",
            "Use job requirements as keywords only when the candidate can truthfully claim or position adjacent experience.",
            "Recruiter messages must be concise and human: one LinkedIn connection note and one longer InMail/email variant.",
            "ATS CV text should be a focused one-page CV draft/section set, not generic advice.",
            "Cover letter can be empty only if the job clearly does not need one; otherwise provide a concise tailored letter.",
            "Autofill notes should include copy-paste answers for common portal questions and caveats for claims to avoid.",
            "Return only JSON matching the schema.",
        ],
    }
    response = _call_openai(payload, key, model or DEFAULT_MATERIALS_MODEL, timeout)
    return {
        "recruiter_message": str(response["recruiter_message"]),
        "cover_letter": str(response.get("cover_letter") or ""),
        "ats_cv_text": str(response["ats_cv_text"]),
        "autofill_notes": str(response["autofill_notes"]),
    }


def export_ats_cv_docx_bytes(job: dict[str, Any], ats_cv_text: str) -> bytes:
    try:
        from docx import Document
    except ModuleNotFoundError as exc:
        raise LLMMaterialsError("DOCX export requires python-docx. Install it with `pip install python-docx`.") from exc

    title = job.get("title") or "Target role"
    company = job.get("company") or "Target company"
    document = Document()
    document.add_heading(f"ATS CV - {title}", level=1)
    document.add_paragraph(f"Target company: {company}")
    document.add_paragraph("")
    for block in str(ats_cv_text or "").splitlines():
        text = block.strip()
        if not text:
            document.add_paragraph("")
        elif text.startswith(("-", "*")):
            document.add_paragraph(text[1:].strip(), style="List Bullet")
        else:
            document.add_paragraph(text)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _call_openai(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    body = {
        "model": model,
        "store": False,
        "reasoning": {"effort": "low"},
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a strict career application assistant. Create high-quality, truthful, ATS-aware "
                    "materials. Return only structured JSON."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "application_kit",
                "strict": True,
                "schema": _materials_schema(),
            }
        },
    }
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMMaterialsError(f"OpenAI materials request failed: {exc}") from exc

    try:
        return json.loads(_extract_response_text(response.json()))
    except json.JSONDecodeError as exc:
        raise LLMMaterialsError("OpenAI materials response was not valid JSON.") from exc


def _materials_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "recruiter_message",
            "cover_letter",
            "ats_cv_text",
            "autofill_notes",
        ],
        "properties": {
            "recruiter_message": {"type": "string"},
            "cover_letter": {"type": "string"},
            "ats_cv_text": {"type": "string"},
            "autofill_notes": {"type": "string"},
        },
    }


def _extract_response_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return response["output_text"]
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    raise LLMMaterialsError("OpenAI materials response did not include text output.")


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
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
        "first_seen_at",
        "last_seen_at",
    ]
    compact = {key: job.get(key) for key in keys if job.get(key) is not None}
    description = str(compact.get("description_text") or "")
    if len(description) > 9000:
        compact["description_text"] = description[:9000] + "\n[truncated]"
    return compact
