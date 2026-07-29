from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from joborchestrator.automation.policy import requires_explicit_human_consent as policy_requires_explicit_human_consent


SENSITIVE_KEYS = {
    "salary",
    "work_authorization",
    "sponsorship",
    "availability",
    "address",
    "disability",
    "gender",
    "ethnicity",
    "veteran",
    "background_check",
    "years_experience",
    "certifications",
}


@dataclass(frozen=True)
class FieldAnswer:
    field_name: str
    label: str
    canonical_key: str | None
    value: str | None
    field_type: str
    options: list[dict[str, str]]
    classification: str
    confidence: float
    requires_confirmation: bool
    source: str | None
    match_strategy: str
    answer_status: str | None


def classify_field(label: str, field_type: str = "text") -> tuple[str | None, str]:
    text = f"{label} {field_type}".lower()
    patterns = {
        "full_name": r"\b(full name|name|nombre)\b",
        "email": r"\b(email|e-mail|correo)\b",
        "phone": r"\b(phone|telefono|teléfono)\b",
        "linkedin": r"\blinkedin\b",
        "portfolio": r"\b(portfolio|website|github|site)\b",
        "preferred_location": r"\b(preferred location|location preference|office location)\b",
        "talent_pool": r"\b(talent pool|future opportunities)\b",
        "salary": r"\b(salary|compensation|salario)\b",
        "work_authorization": r"\b(work authorization|authorized|permiso de trabajo)\b",
        "sponsorship": r"\b(sponsor|sponsorship|visa)\b",
        "availability": r"\b(start date|availability|disponibilidad)\b",
        "address": r"\b(address|direccion|dirección)\b",
        "gender": r"\bgender\b",
        "ethnicity": r"\bethnicity|race\b",
        "disability": r"\bdisability\b",
    }
    for key, pattern in patterns.items():
        if re.search(pattern, text):
            return key, "sensitive" if key in SENSITIVE_KEYS else "safe"
    return None, "unknown"


def requires_explicit_human_consent(*parts: str) -> bool:
    return policy_requires_explicit_human_consent(*parts)


def map_answers(schema: dict[str, Any], profile: dict[str, Any], answer_bank: list[dict[str, Any]]) -> dict[str, Any]:
    usable_answers = [_normalize_answer_definition(answer) for answer in answer_bank if _answer_is_usable(answer)]
    fields = schema.get("fields") or []
    mapped: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for field in fields:
        label = str(field.get("label") or field.get("name") or "")
        canonical, classification = classify_field(label, str(field.get("type") or "text"))
        value = _profile_value(canonical, profile)
        source = "confirmed_profile" if value else None
        match_strategy = "profile" if value else "unresolved"
        answer = _match_answer_definition(label, canonical, usable_answers)
        if answer:
            value = str(answer.get("value") or "")
            canonical = str(answer.get("canonical_key") or canonical or "")
            sensitivity = str(answer.get("sensitivity") or "public")
            if classification == "unknown":
                classification = "sensitive" if sensitivity == "sensitive" else "safe"
            source = "approved_answer"
            match_strategy = str(answer.get("_match_strategy") or "answer_bank")
        requires_confirmation = (
            not value
            or (classification == "sensitive" and source != "approved_answer")
            or requires_explicit_human_consent(label, str(field.get("name") or field.get("id") or ""))
        )
        result = FieldAnswer(
            field_name=str(field.get("name") or field.get("id") or label),
            label=label,
            canonical_key=canonical,
            value=value,
            field_type=str(field.get("type") or "text"),
            options=list(field.get("options") or []),
            classification=classification,
            confidence=0.9 if value and not requires_confirmation else 0.35,
            requires_confirmation=requires_confirmation,
            source=source,
            match_strategy=match_strategy,
            answer_status=str(answer.get("status")) if answer else None,
        )
        mapped.append(result.__dict__)
        if requires_confirmation and field.get("required", False):
            unknown.append({**field, "canonical_key": canonical, "classification": classification})
    return {"answers": mapped, "unknown_fields": unknown}


def _answer_is_usable(answer: dict[str, Any]) -> bool:
    status = str(answer.get("status") or ("proposed" if answer.get("source") == "generated" else "approved"))
    if status != "approved":
        return False
    if answer.get("source") != "approved":
        return False
    if answer.get("requires_confirmation"):
        return False
    expires_at = answer.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(str(expires_at)) <= datetime.now():
                return False
        except ValueError:
            return False
    return bool(str(answer.get("value") or "").strip())


def _normalize_answer_definition(answer: dict[str, Any]) -> dict[str, Any]:
    patterns = [str(pattern) for pattern in answer.get("question_patterns") or [] if str(pattern or "").strip()]
    return {
        **answer,
        "_normalized_key": normalize_question(str(answer.get("canonical_key") or "")),
        "_normalized_patterns": [normalize_question(pattern) for pattern in patterns],
    }


def _match_answer_definition(label: str, canonical: str | None, answers: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_label = normalize_question(label)
    normalized_canonical = normalize_question(canonical or "")
    exact_matches = [
        answer for answer in answers
        if normalized_label and normalized_label in set(answer.get("_normalized_patterns") or [])
    ]
    if len(exact_matches) == 1:
        return {**exact_matches[0], "_match_strategy": "question_pattern_exact"}
    regex_matches: list[dict[str, Any]] = []
    for answer in answers:
        for pattern in answer.get("question_patterns") or []:
            if _regex_pattern_matches(str(pattern), label):
                regex_matches.append(answer)
                break
    if len(regex_matches) == 1:
        return {**regex_matches[0], "_match_strategy": "question_pattern_regex"}
    if normalized_canonical:
        for answer in answers:
            if answer.get("_normalized_key") == normalized_canonical:
                return {**answer, "_match_strategy": "canonical_key"}
    return None


def _regex_pattern_matches(pattern: str, label: str) -> bool:
    if not pattern.startswith("re:"):
        return False
    try:
        return bool(re.search(pattern[3:], label, flags=re.IGNORECASE))
    except re.error:
        return False


def normalize_question(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^\w\s]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _profile_value(canonical: str | None, profile: dict[str, Any]) -> str | None:
    if not canonical:
        return None
    aliases = {
        "full_name": ["full_name", "name", "headline"],
        "email": ["email"],
        "phone": ["phone"],
        "linkedin": ["linkedin_url", "linkedin"],
        "portfolio": ["portfolio_url", "website", "github"],
        "preferred_location": ["preferred_location", "preferred_locations", "location"],
        "talent_pool": ["talent_pool"],
    }
    for key in aliases.get(canonical, []):
        value = profile.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return str(value)
    return None
