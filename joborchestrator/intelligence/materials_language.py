from __future__ import annotations

import re
from typing import Literal

TargetLanguage = Literal["en", "es", "unsupported"]


SPANISH_MARKERS = {
    "experiencia",
    "remoto",
    "programador",
    "desarrollador",
    "conocimientos",
    "requisitos",
    "oferta",
    "trabajo",
    "jornada",
    "incorporacion",
    "incorporación",
}

ENGLISH_MARKERS = {
    "experience",
    "remote",
    "engineer",
    "developer",
    "requirements",
    "responsibilities",
    "role",
    "team",
    "work",
}


def detect_job_language(title: str, description: str) -> TargetLanguage:
    tokens = set(re.findall(r"[a-záéíóúñü]+", f"{title} {description}".lower()))
    spanish = len(tokens & SPANISH_MARKERS)
    english = len(tokens & ENGLISH_MARKERS)
    if spanish >= 2 and spanish >= english:
        return "es"
    if english >= 2 and english > spanish:
        return "en"
    return "unsupported"


def language_mismatch(text: str, target_language: TargetLanguage) -> bool:
    if target_language == "unsupported":
        return False
    detected = detect_job_language("", text)
    return detected != "unsupported" and detected != target_language
