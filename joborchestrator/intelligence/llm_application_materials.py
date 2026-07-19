from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, is_dataclass
from io import BytesIO
from typing import Any

import httpx

from joborchestrator.llm.provider import LLMProviderError, ProviderRegistry
from joborchestrator.prompts import active_prompt_version, load_prompt
from joborchestrator.intelligence.llm_costs import estimate_application_kit_tokens, estimate_cost
from joborchestrator.intelligence.cv_profile_extractor import profile_payload_to_candidate_profile
from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.ranking.serialization import result_to_dict
from joborchestrator.storage import persistence as db

DEFAULT_MATERIALS_MODEL = os.getenv("OPENAI_MATERIALS_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"
DEFAULT_NVIDIA_MATERIALS_MODEL = (
    os.getenv("NVIDIA_MATERIALS_MODEL")
    or os.getenv("NVIDIA_RANKING_MODEL")
    or os.getenv("NVIDIA_MODEL")
    or "nvidia/llama-3.3-nemotron-super-49b-v1"
)
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MATERIALS_TIMEOUT_SECONDS = float(os.getenv("NVIDIA_MATERIALS_TIMEOUT_SECONDS", "300"))
DEFAULT_MATERIALS_VALIDATION_RETRIES = int(os.getenv("OPENAI_MATERIALS_VALIDATION_RETRIES", "1"))
logger = logging.getLogger(__name__)


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


def materials_prompt_versions() -> dict[str, str]:
    return {
        "materials/nvidia_cv_contract": active_prompt_version("materials", "nvidia_cv_contract"),
        "materials/nvidia_kit_contract": active_prompt_version("materials", "nvidia_kit_contract"),
    }


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

    payload = _materials_payload(job, ranking)
    kit_response = _call_openai(payload, key, model or DEFAULT_MATERIALS_MODEL, timeout)
    kit = _kit_from_response(kit_response)
    _attach_generation_metadata(kit, kit_response)
    return kit


def build_application_kit_with_nvidia(
    job: Any,
    ranking: Any | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_NVIDIA_MATERIALS_TIMEOUT_SECONDS,
) -> dict[str, str]:
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
    if not key:
        raise LLMMaterialsError("NVIDIA_API_KEY or NIM_API_KEY is required to generate materials with NVIDIA.")

    payload = _materials_payload(job, ranking)
    selected_model = model or DEFAULT_NVIDIA_MATERIALS_MODEL
    cv_response = _call_nvidia_cv(payload, key, selected_model, timeout)
    kit_response = _call_nvidia_kit(payload, key, selected_model, timeout)
    response = {**kit_response, **cv_response}
    response["_generation_metadata"] = _combined_generation_metadata([cv_response, kit_response])
    kit = _kit_from_response(response)
    _attach_generation_metadata(kit, response)
    return kit


def _materials_payload(job: Any, ranking: Any | None = None) -> dict[str, Any]:
    profile_payload = db.get_candidate_profile_payload()
    if not profile_payload:
        raise LLMMaterialsError("No candidate profile configured. Upload a CV in Profile before generating materials.")
    profile = CandidateProfile(**profile_payload_to_candidate_profile(profile_payload))
    base_cv_text = str(profile_payload.get("base_cv_text") or "").strip()
    return {
        "candidate_profile": asdict(profile),
        "base_cv": {
            "filename": profile_payload.get("base_cv_filename") or "",
            "text": base_cv_text[:24000],
        },
        "job": _compact_job(_to_dict(job)),
        "ranking": _ranking_payload(ranking),
        "goal": (
            "Generate truthful, editable application materials and a complete ATS-optimized CV for this specific job. "
            "Optimize for ATS filters and fast application workflow without inventing experience."
        ),
        "rules": [
            "Do not invent employers, degrees, certifications, years of experience, tools or projects.",
            "The ats_cv_text field must be a complete rewritten CV, not notes, and must preserve the candidate's real personal details, experience, education, dates, and achievements from base_cv.",
            "Keep the base CV's overall section structure when possible, but rewrite wording and ordering for ATS fit against this job.",
            "If base_cv is empty, produce the best complete CV draft possible from the candidate profile and mark missing source limitations in risk_flags.",
            "Use job requirements as keywords only when the candidate can truthfully claim or position adjacent experience.",
            "Recruiter_message must be a short LinkedIn connection note to a recruiter or hiring contact, not a cover letter and not multiple variants.",
            "Recruiter_message must fit a LinkedIn invite: under 300 characters when possible, one paragraph, no formal letter salutation, no cover-letter body.",
            "Recruiter_message should say why this specific role matches the CV and that the candidate would like to send/share the CV.",
            "Output language should match the job posting language unless the user profile clearly indicates otherwise.",
            "ATS CV text should be ready to copy, export to DOCX/PDF, and submit after human review.",
            "Cover letter can be empty only when application context clearly does not need one; otherwise provide a concise tailored letter.",
            "Autofill notes should include copy-paste answers for common portal questions and caveats for claims to avoid.",
            "List risk_flags for unsupported claims, adjacency framing, or user facts to double-check.",
            "Return only JSON matching the schema.",
        ],
        "output_shape": {
            "recruiter_message": "short recruiter connection note, ready to paste into LinkedIn invite/InMail/email",
            "cover_letter": "concise tailored cover letter or empty string",
            "ats_cv_text": "complete ATS-optimized CV only; no notes or internal instructions",
            "autofill_notes": "structured copy-paste application workflow",
            "risk_flags": ["unsupported or review-needed claims"],
            "keywords_used": ["truthful job keywords included"],
        },
    }


def _kit_from_response(response: dict[str, Any]) -> dict[str, str]:
    return {
        "recruiter_message": _clean_recruiter_message(_material_text(response["recruiter_message"])),
        "cover_letter": str(response.get("cover_letter") or ""),
        "ats_cv_text": _clean_cv_text_for_export(str(response["ats_cv_text"])),
        "autofill_notes": _material_text(response["autofill_notes"]),
    }


def _attach_generation_metadata(kit: dict[str, Any], response: dict[str, Any]) -> None:
    metadata = response.get("_generation_metadata")
    if isinstance(metadata, dict):
        kit["_generation_metadata"] = metadata


def _combined_generation_metadata(responses: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = 0
    errors: list[str] = []
    for response in responses:
        metadata = response.get("_generation_metadata")
        if not isinstance(metadata, dict):
            continue
        attempts += int(metadata.get("validation_attempts") or 0)
        errors.extend(str(error) for error in metadata.get("validation_errors") or [])
    return {"validation_attempts": attempts or 1, "validation_errors": errors}


def _clean_recruiter_message(text: str) -> str:
    message = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    if not message:
        return ""
    contamination_patterns = [
        r"\bDear\s+(?:Hiring Manager|Recruiter|Sir/Madam|Team)\b[:,]?",
        r"\bI'?m reaching out to express (?:my )?interest\b",
        r"\bI am writing to (?:express|apply)\b",
        r"\bSincerely\b[:,]?",
        r"\bBest regards\b[:,]?",
    ]
    earliest: int | None = None
    for pattern in contamination_patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match and match.start() > 0:
            earliest = match.start() if earliest is None else min(earliest, match.start())
    if earliest is not None:
        message = message[:earliest].strip()
    return re.sub(r"[ \t]+", " ", message).strip()


def _material_text(value: Any) -> str:
    if isinstance(value, dict):
        preferred_keys = ["short", "long", "summary", "copy_paste_block", "notes"]
        parts = [str(value[key]).strip() for key in preferred_keys if str(value.get(key) or "").strip()]
        if parts:
            return "\n\n".join(parts)
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "")


def _ranking_payload(ranking: Any | None) -> dict[str, Any] | None:
    if ranking is None:
        return None
    if isinstance(ranking, dict):
        return ranking
    return result_to_dict(ranking)


def build_ats_cv_with_nvidia(
    job: Any,
    ranking: Any | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_NVIDIA_MATERIALS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
    if not key:
        raise LLMMaterialsError("NVIDIA_API_KEY or NIM_API_KEY is required to generate materials with NVIDIA.")
    payload = _materials_payload(job, ranking)
    return _call_nvidia_cv(payload, key, model or DEFAULT_NVIDIA_MATERIALS_MODEL, timeout)


def build_lightweight_kit_with_nvidia(
    job: Any,
    ranking: Any | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_NVIDIA_MATERIALS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
    if not key:
        raise LLMMaterialsError("NVIDIA_API_KEY or NIM_API_KEY is required to generate materials with NVIDIA.")
    payload = _materials_payload(job, ranking)
    return _call_nvidia_kit(payload, key, model or DEFAULT_NVIDIA_MATERIALS_MODEL, timeout)


def export_ats_cv_docx_bytes(job: dict[str, Any], ats_cv_text: str) -> bytes:
    try:
        from docx import Document
    except ModuleNotFoundError as exc:
        raise LLMMaterialsError("DOCX export requires python-docx. Install it with `pip install python-docx`.") from exc

    document = Document()
    for block in _clean_cv_text_for_export(ats_cv_text).splitlines():
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


def export_ats_cv_pdf_bytes(job: dict[str, Any], ats_cv_text: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:
        raise LLMMaterialsError("PDF export requires reportlab. Install it with `pip install reportlab`.") from exc

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x = 2 * cm
    y = height - 2 * cm
    pdf.setFont("Helvetica", 10)
    for raw_line in _clean_cv_text_for_export(ats_cv_text).splitlines():
        line = raw_line.rstrip()
        if not line:
            y -= 0.35 * cm
            continue
        for chunk in _wrap_pdf_line(line, max_chars=95):
            if y < 2 * cm:
                pdf.showPage()
                y = height - 2 * cm
                pdf.setFont("Helvetica", 10)
            pdf.drawString(x, y, chunk)
            y -= 0.42 * cm
    pdf.save()
    return buffer.getvalue()


def _clean_cv_text_for_export(text: str) -> str:
    cleaned = str(text or "")
    replacements = {
        "\x7f": "-",
        "\u2022": "-",
        "\u2023": "-",
        "\u25e6": "-",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    forbidden_sections = [
        "Optimization notes",
        "ATS CV targeting notes",
        "ATS optimized CV draft",
        "Optimized CV",
    ]
    lines = []
    skip_rest = False
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        if any(stripped.lower().startswith(section.lower()) for section in forbidden_sections):
            if stripped.lower().startswith("optimization notes"):
                skip_rest = True
            continue
        if skip_rest:
            continue
        if stripped.startswith("Target role:") or stripped.startswith("Positioning angle:"):
            continue
        if stripped.startswith("ATS keywords to emphasize truthfully:"):
            continue
        if set(stripped) <= {"-"}:
            continue
        lines.append(raw_line)
    return "\n".join(lines).strip()


def _wrap_pdf_line(line: str, max_chars: int) -> list[str]:
    words = line.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _call_openai(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    validation_feedback: str | None = None
    validation_errors: list[str] = []
    for attempt in range(DEFAULT_MATERIALS_VALIDATION_RETRIES + 1):
        parsed = _call_openai_once(payload, api_key, model, timeout, validation_feedback)
        validation_feedback = _materials_validation_error(parsed, _base_cv_text(payload), payload)
        if not validation_feedback:
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_MATERIALS_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning("Retrying OpenAI materials generation after invalid response: %s", validation_feedback)
            continue
        raise LLMMaterialsError(f"OpenAI materials response was incomplete: {validation_feedback}")
    raise LLMMaterialsError("OpenAI materials response did not produce a usable application kit.")


def _call_nvidia(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    validation_feedback: str | None = None
    validation_errors: list[str] = []
    for attempt in range(DEFAULT_MATERIALS_VALIDATION_RETRIES + 1):
        parsed = _call_nvidia_once(payload, api_key, model, timeout, validation_feedback)
        validation_feedback = _materials_validation_error(parsed, _base_cv_text(payload), payload)
        if not validation_feedback:
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_MATERIALS_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning("Retrying NVIDIA materials generation after invalid response: %s", validation_feedback)
            continue
        raise LLMMaterialsError(f"NVIDIA materials response was incomplete: {validation_feedback}")
    raise LLMMaterialsError("NVIDIA materials response did not produce a usable application kit.")


def _call_nvidia_cv(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    validation_feedback: str | None = None
    validation_errors: list[str] = []
    for attempt in range(DEFAULT_MATERIALS_VALIDATION_RETRIES + 1):
        parsed = _call_nvidia_contract_once(
            _nvidia_cv_contract(),
            payload,
            api_key,
            model,
            timeout,
            validation_feedback,
        )
        validation_feedback = _ats_cv_response_validation_error(parsed, _base_cv_text(payload), payload)
        if not validation_feedback:
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_MATERIALS_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning(
                "Retrying NVIDIA ATS CV generation after invalid response: %s received_keys=%s",
                validation_feedback,
                sorted(parsed.keys()),
            )
            continue
        raise LLMMaterialsError(f"NVIDIA ATS CV response was incomplete: {validation_feedback}")
    raise LLMMaterialsError("NVIDIA ATS CV response did not produce a usable CV.")


def _call_nvidia_kit(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    validation_feedback: str | None = None
    validation_errors: list[str] = []
    for attempt in range(DEFAULT_MATERIALS_VALIDATION_RETRIES + 1):
        parsed = _call_nvidia_contract_once(
            _nvidia_kit_contract(),
            payload,
            api_key,
            model,
            timeout,
            validation_feedback,
        )
        validation_feedback = _kit_response_validation_error(parsed, payload)
        if not validation_feedback:
            parsed["_generation_metadata"] = {
                "validation_attempts": attempt + 1,
                "validation_errors": validation_errors,
            }
            return parsed
        if attempt < DEFAULT_MATERIALS_VALIDATION_RETRIES:
            validation_errors.append(validation_feedback)
            logger.warning(
                "Retrying NVIDIA kit generation after invalid response: %s received_keys=%s",
                validation_feedback,
                sorted(parsed.keys()),
            )
            continue
        raise LLMMaterialsError(f"NVIDIA kit response was incomplete: {validation_feedback}")
    raise LLMMaterialsError("NVIDIA kit response did not produce usable materials.")


def _call_nvidia_contract_once(
    contract: str,
    payload: dict[str, Any],
    api_key: str,
    model: str,
    timeout: float,
    validation_feedback: str | None = None,
) -> dict[str, Any]:
    try:
        provider = ProviderRegistry().get(
            "materials",
            provider_name="nvidia",
            api_key=api_key,
            base_url=NVIDIA_BASE_URL,
            timeout=timeout,
            http_module=httpx,
        )
        response = provider.complete(
            _nvidia_contract_messages(contract, payload, validation_feedback),
            model=model,
            temperature=0,
            response_format="json",
            max_tokens=int(os.getenv("NVIDIA_MATERIALS_MAX_TOKENS", "8000")),
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
        )
    except LLMProviderError as exc:
        raise LLMMaterialsError(f"NVIDIA materials request failed: {exc}") from exc

    try:
        return json.loads(_extract_json_object_text(response.text))
    except json.JSONDecodeError as exc:
        raise LLMMaterialsError(f"NVIDIA materials response was not valid JSON: {exc}") from exc


def _call_nvidia_once(
    payload: dict[str, Any],
    api_key: str,
    model: str,
    timeout: float,
    validation_feedback: str | None = None,
) -> dict[str, Any]:
    user_payload = dict(payload)
    if validation_feedback:
        user_payload["previous_response_error"] = validation_feedback
        user_payload["instruction"] = "Return a corrected complete JSON object only."
    try:
        provider = ProviderRegistry().get(
            "materials",
            provider_name="nvidia",
            api_key=api_key,
            base_url=NVIDIA_BASE_URL,
            timeout=timeout,
            http_module=httpx,
        )
        response = provider.complete(
            _nvidia_materials_messages(user_payload),
            model=model,
            temperature=0.1,
            response_format="json",
            max_tokens=int(os.getenv("NVIDIA_MATERIALS_MAX_TOKENS", "12000")),
            top_p=0.95,
        )
    except LLMProviderError as exc:
        raise LLMMaterialsError(f"NVIDIA materials request failed: {exc}") from exc

    try:
        return json.loads(_extract_json_object_text(response.text))
    except json.JSONDecodeError as exc:
        raise LLMMaterialsError(f"NVIDIA materials response was not valid JSON: {exc}") from exc


def _call_openai_once(
    payload: dict[str, Any],
    api_key: str,
    model: str,
    timeout: float,
    validation_feedback: str | None = None,
) -> dict[str, Any]:
    user_payload = dict(payload)
    if validation_feedback:
        user_payload["previous_response_error"] = validation_feedback
        user_payload["instruction"] = "Return a corrected complete JSON object only."
    try:
        provider = ProviderRegistry().get(
            "materials",
            provider_name="openai",
            api_key=api_key,
            timeout=timeout,
            http_module=httpx,
        )
        response = provider.complete(
            _openai_materials_messages(user_payload),
            model=model,
            response_format="json",
            response_schema=_materials_schema(),
            schema_name="application_kit",
        )
    except LLMProviderError as exc:
        raise LLMMaterialsError(f"OpenAI materials request failed: {exc}") from exc

    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise LLMMaterialsError("OpenAI materials response was not valid JSON.") from exc


def _nvidia_contract_messages(
    contract: str,
    payload: dict[str, Any],
    validation_feedback: str | None = None,
) -> list[dict[str, Any]]:
    user_content = contract + "\n\nContext:\n" + json.dumps(payload, ensure_ascii=False)
    if validation_feedback:
        user_content += (
            "\n\nYour previous response was rejected because: "
            f"{validation_feedback}\nReturn a corrected complete JSON object only."
        )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict career application assistant. Return only JSON that matches "
                "the requested shape. Do not include markdown fences or commentary."
            ),
        },
        {"role": "user", "content": user_content},
    ]


def _nvidia_materials_messages(user_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a strict career application assistant. Return only valid JSON. "
                "The ats_cv_text value must be a final complete CV, not notes, comments, or instructions."
            ),
        },
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _openai_materials_messages(user_payload: dict[str, Any]) -> list[dict[str, Any]]:
    user_content = _openai_materials_contract() + "\n\nContext:\n" + json.dumps(user_payload, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "You are a strict career application assistant. Create high-quality, truthful, ATS-aware "
                "materials. Return only structured JSON. Do not leave required sections blank."
            ),
        },
        {"role": "user", "content": user_content},
    ]


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


def _materials_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "recruiter_message",
            "cover_letter",
            "ats_cv_text",
            "autofill_notes",
            "risk_flags",
            "keywords_used",
        ],
        "properties": {
            "recruiter_message": {"type": "string"},
            "cover_letter": {"type": "string"},
            "ats_cv_text": {"type": "string"},
            "autofill_notes": {"type": "string"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "keywords_used": {"type": "array", "items": {"type": "string"}},
        },
    }


def _nvidia_cv_contract() -> str:
    return load_prompt("materials", "nvidia_cv_contract")


def _nvidia_kit_contract() -> str:
    return load_prompt("materials", "nvidia_kit_contract")


def _openai_materials_contract() -> str:
    return (
        "ATS CV contract:\n"
        + _nvidia_cv_contract()
        + "\n\nApplication kit contract:\n"
        + _nvidia_kit_contract()
        + "\n\nReturn one JSON object containing the ATS CV fields and application kit fields."
    )


def _materials_validation_error(
    payload: dict[str, Any],
    base_cv_text: str | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    if base_cv_text is None and source_payload is not None:
        base_cv_text = _base_cv_text(source_payload)
    problems = []
    kit_error = _kit_response_validation_error(payload, source_payload)
    cv_error = _ats_cv_response_validation_error(payload, base_cv_text, source_payload)
    if kit_error:
        problems.append(kit_error)
    if cv_error:
        problems.append(cv_error)
    return "; ".join(problems) if problems else None


def _kit_response_validation_error(
    payload: dict[str, Any],
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    problems = []
    for field in ["recruiter_message", "autofill_notes"]:
        if not str(payload.get(field) or "").strip():
            problems.append(f"{field} is required")
    recruiter_message = str(payload.get("recruiter_message") or "")
    if len(recruiter_message) > 320:
        problems.append("recruiter_message is too long")
    problems.extend(_recruiter_message_quality_problems(recruiter_message))
    problems.extend(_recruiter_message_specificity_problems(recruiter_message, source_payload))
    return "; ".join(problems) if problems else None


def _recruiter_message_quality_problems(text: str) -> list[str]:
    message = str(text or "").strip()
    lower = message.lower()
    problems: list[str] = []
    cover_letter_markers = [
        "dear hiring manager",
        "dear recruiter",
        "i am writing to express",
        "i'm writing to express",
        "i am reaching out to express interest",
        "i'm reaching out to express interest",
        "sincerely",
    ]
    found = [marker for marker in cover_letter_markers if marker in lower]
    if found:
        problems.append(f"recruiter_message reads like a cover letter: {', '.join(found[:2])}")
    intro_markers = len(re.findall(r"\b(?:i am|i'm)\s+[^.\n]{0,90}\b(?:developer|engineer|specialist|manager|consultant)\b", lower))
    if intro_markers > 1:
        problems.append("recruiter_message repeats the candidate introduction")
    interest_markers = len(re.findall(r"\b(?:interested in|interest in|excited about|express interest)\b", lower))
    if interest_markers > 2:
        problems.append("recruiter_message repeats the interest statement")
    return problems


def _recruiter_message_specificity_problems(
    text: str,
    source_payload: dict[str, Any] | None,
) -> list[str]:
    terms = _recruiter_specificity_terms(source_payload)
    if not terms:
        return []
    normalized = _normalize_for_match(text)
    if any(term in normalized for term in terms):
        return []
    return ["recruiter_message is generic; mention the target company or role"]


def _recruiter_specificity_terms(source_payload: dict[str, Any] | None) -> list[str]:
    if not source_payload:
        return []
    job = source_payload.get("job") if isinstance(source_payload.get("job"), dict) else {}
    company = _normalize_for_match(str(job.get("company") or ""))
    title = _normalize_for_match(str(job.get("title") or ""))
    terms = []
    if company and company not in {"confidential", "unknown", "none"}:
        terms.append(company)
    title = re.sub(r"\([^)]*\)", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    if title:
        terms.append(title)
        role_words = [
            word
            for word in title.split()
            if len(word) >= 3 and word not in {"remote", "hybrid", "onsite", "senior", "junior", "lead"}
        ]
        if len(role_words) >= 2:
            terms.append(" ".join(role_words[:3]))
    return _dedupe_strings(terms)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _ats_cv_response_validation_error(
    payload: dict[str, Any],
    base_cv_text: str | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    problems = []
    ats_cv_text = str(payload.get("ats_cv_text") or "")
    if not ats_cv_text.strip():
        problems.append("ats_cv_text is required")
    for field in ["risk_flags", "keywords_used"]:
        if not isinstance(payload.get(field), list):
            problems.append(f"{field} must be an array")
    problems.extend(_ats_cv_quality_problems(ats_cv_text))
    problems.extend(_experience_coverage_problems(str(base_cv_text or ""), ats_cv_text))
    problems.extend(_ats_cv_overclaiming_problems(ats_cv_text, source_payload))
    return "; ".join(problems) if problems else None


def _base_cv_text(payload: dict[str, Any]) -> str:
    base_cv = payload.get("base_cv")
    if isinstance(base_cv, dict):
        return str(base_cv.get("text") or "")
    return ""


def _ats_cv_quality_problems(text: str) -> list[str]:
    cleaned = _clean_cv_text_for_export(text)
    normalized = cleaned.lower()
    raw_normalized = str(text or "").lower()
    problems: list[str] = []
    if len(cleaned) < 700:
        problems.append("ats_cv_text is too short to be a complete ATS CV")
    if len([line for line in cleaned.splitlines() if line.strip()]) < 18:
        problems.append("ats_cv_text has too few parseable lines for a complete CV")

    section_patterns = {
        "summary": ["summary", "profile", "professional summary", "perfil", "resumen"],
        "experience": ["experience", "work experience", "professional experience", "experiencia"],
        "skills": ["skills", "technical skills", "core skills", "competencias", "habilidades"],
        "education": ["education", "formacion", "formación", "academic", "educacion", "educación"],
    }
    missing_sections = [
        section
        for section, aliases in section_patterns.items()
        if not any(_contains_section_heading(normalized, alias) for alias in aliases)
    ]
    if missing_sections:
        problems.append(f"ats_cv_text is missing standard ATS sections: {', '.join(missing_sections)}")

    forbidden_markers = [
        "optimization notes",
        "ats cv targeting notes",
        "target role:",
        "positioning angle:",
        "do not add skills",
        "profile-backed keywords",
        "keywords to emphasize",
        "internal note",
    ]
    found_markers = [marker for marker in forbidden_markers if marker in raw_normalized]
    if found_markers:
        problems.append(f"ats_cv_text contains internal/non-CV notes: {', '.join(found_markers[:3])}")
    return problems


def _contains_section_heading(normalized_text: str, heading: str) -> bool:
    for line in normalized_text.splitlines():
        stripped = line.strip(" :-\t")
        if stripped == heading or stripped.startswith(f"{heading}:"):
            return True
    return False


def _experience_coverage_problems(base_cv_text: str, ats_cv_text: str) -> list[str]:
    entries = _extract_base_experience_entries(base_cv_text)
    if len(entries) < 2:
        return []
    normalized_cv = _normalize_for_match(ats_cv_text)
    missing = []
    for entry in entries:
        terms = entry["terms"]
        if not any(term in normalized_cv for term in terms):
            missing.append(entry["label"])
    if missing:
        return [f"ats_cv_text omitted base CV experience entries: {', '.join(missing[:6])}"]
    return []


def _ats_cv_overclaiming_problems(text: str, source_payload: dict[str, Any] | None) -> list[str]:
    if not source_payload:
        return []
    ranking = source_payload.get("ranking") if isinstance(source_payload.get("ranking"), dict) else {}
    avoid_terms = _terms_from_maybe_json(
        ranking.get("cv_keywords_to_avoid_overclaiming")
        or ranking.get("cv_keywords_to_avoid_overclaiming_json")
        or source_payload.get("cv_keywords_to_avoid_overclaiming")
    )
    if not avoid_terms:
        return []

    normalized_cv = _normalize_for_match(text)
    supported_source = _normalize_for_match(_supported_materials_source_text(source_payload))
    unsupported_terms = [
        term
        for term in avoid_terms
        if _contains_phrase_for_materials(normalized_cv, term)
        and not _contains_phrase_for_materials(supported_source, term)
    ]
    if not unsupported_terms:
        return []
    return [
        "ats_cv_text contains unsupported ranking avoid-overclaiming terms: "
        + ", ".join(unsupported_terms[:6])
    ]


def _supported_materials_source_text(source_payload: dict[str, Any]) -> str:
    base_cv = source_payload.get("base_cv")
    profile = source_payload.get("candidate_profile")
    return "\n".join(
        [
            str(base_cv.get("text") or "") if isinstance(base_cv, dict) else "",
            json.dumps(profile, ensure_ascii=False) if isinstance(profile, dict) else str(profile or ""),
        ]
    )


def _terms_from_maybe_json(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                return _dedupe_strings([str(item).strip() for item in json.loads(stripped) if str(item).strip()])
            except json.JSONDecodeError:
                pass
        return [stripped] if stripped else []
    if isinstance(value, list):
        return _dedupe_strings([str(item).strip() for item in value if str(item).strip()])
    return []


def _extract_base_experience_entries(base_cv_text: str) -> list[dict[str, Any]]:
    section = _experience_section(base_cv_text)
    if not section:
        return []
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = _date_range_match(line)
        if not match:
            continue
        title = line[: match.start()].strip(" -|")
        company = _next_company_line(lines, index + 1)
        if not title or not company:
            continue
        terms = _company_match_terms(company)
        if not terms:
            continue
        entries.append(
            {
                "title": title,
                "company": company,
                "label": f"{title} at {company}",
                "terms": terms,
            }
        )
    return entries


def _experience_section(text: str) -> str:
    match = re.search(
        r"(?ims)^\s*(experience|professional experience|experiencia)\s*$([\s\S]*?)(?=^\s*(projects|technical skills|skills|education|formaci[oó]n)\s*$|\Z)",
        text,
    )
    return match.group(2) if match else ""


def _date_range_match(line: str) -> re.Match[str] | None:
    month = (
        r"january|february|march|april|may|june|july|august|september|october|november|december|"
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    )
    return re.search(rf"(?i)\b(?:{month})\s+\d{{4}}\s*[-–—]\s*(?:(?:{month})\s+\d{{4}}|present|current|actualidad)", line)


def _next_company_line(lines: list[str], start: int) -> str:
    for line in lines[start : start + 3]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("•", "-", "*")):
            continue
        if _date_range_match(stripped):
            continue
        return stripped
    return ""


def _company_match_terms(company: str) -> list[str]:
    normalized = _normalize_for_match(company)
    stopwords = {
        "client",
        "cliente",
        "malaga",
        "spain",
        "espana",
        "buenos",
        "aires",
        "argentina",
        "remote",
        "remoto",
        "consulting",
        "group",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 4 and token not in stopwords
    ]
    seen = set()
    unique = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique[:5]


def _normalize_for_match(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_text.lower()


def _contains_phrase_for_materials(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_for_match(phrase)
    if not normalized_phrase:
        return False
    return normalized_phrase in normalized_text


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
