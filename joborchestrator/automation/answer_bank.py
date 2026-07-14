from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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
    canonical_key: str | None
    value: str | None
    classification: str
    confidence: float
    requires_confirmation: bool


def classify_field(label: str, field_type: str = "text") -> tuple[str | None, str]:
    text = f"{label} {field_type}".lower()
    patterns = {
        "full_name": r"\b(full name|name|nombre)\b",
        "email": r"\b(email|e-mail|correo)\b",
        "phone": r"\b(phone|telefono|teléfono)\b",
        "linkedin": r"\blinkedin\b",
        "portfolio": r"\b(portfolio|website|github|site)\b",
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


def map_answers(schema: dict[str, Any], profile: dict[str, Any], answer_bank: list[dict[str, Any]]) -> dict[str, Any]:
    approved = {
        str(answer.get("canonical_key")): answer
        for answer in answer_bank
        if answer.get("source") == "approved" and not answer.get("requires_confirmation")
    }
    fields = schema.get("fields") or []
    mapped: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for field in fields:
        label = str(field.get("label") or field.get("name") or "")
        canonical, classification = classify_field(label, str(field.get("type") or "text"))
        value = _profile_value(canonical, profile)
        answer = approved.get(canonical or "")
        if answer and answer.get("sensitivity") != "sensitive":
            value = str(answer.get("value") or "")
        requires_confirmation = classification == "sensitive" or not value
        result = FieldAnswer(
            field_name=str(field.get("name") or field.get("id") or label),
            canonical_key=canonical,
            value=value,
            classification=classification,
            confidence=0.9 if value and not requires_confirmation else 0.35,
            requires_confirmation=requires_confirmation,
        )
        mapped.append(result.__dict__)
        if requires_confirmation and field.get("required", False):
            unknown.append({**field, "canonical_key": canonical, "classification": classification})
    return {"answers": mapped, "unknown_fields": unknown}


def _profile_value(canonical: str | None, profile: dict[str, Any]) -> str | None:
    if not canonical:
        return None
    aliases = {
        "full_name": ["full_name", "name", "headline"],
        "email": ["email"],
        "phone": ["phone"],
        "linkedin": ["linkedin_url", "linkedin"],
        "portfolio": ["portfolio_url", "website", "github"],
    }
    for key in aliases.get(canonical, []):
        value = profile.get(key)
        if value:
            return str(value)
    return None
