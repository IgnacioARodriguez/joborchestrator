from __future__ import annotations

import re
import unicodedata


KEYWORD_VARIANTS: dict[str, tuple[str, ...]] = {
    "API": ("API", "APIs"),
    "APIs": ("API", "APIs"),
    "REST API": ("REST API", "REST APIs"),
    "REST APIs": ("REST API", "REST APIs"),
}


def derive_keywords_used(ats_cv_text: str, supported_keywords: list[str]) -> list[str]:
    """Return supported keywords that appear in rendered CV text."""
    found: list[str] = []
    for keyword in supported_keywords:
        value = str(keyword or "").strip()
        if not value:
            continue
        if any(_contains_keyword(ats_cv_text, variant) for variant in _keyword_variants(value)):
            if value not in found:
                found.append(value)
    return found


def _keyword_variants(keyword: str) -> tuple[str, ...]:
    if keyword in KEYWORD_VARIANTS:
        return KEYWORD_VARIANTS[keyword]
    normalized = _normalize(keyword)
    variants = {keyword}
    if normalized.endswith("s") and len(normalized) > 3:
        variants.add(keyword[:-1])
    elif len(normalized) > 2:
        variants.add(f"{keyword}s")
    return tuple(variant for variant in variants if variant)


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = _normalize(text)
    normalized_keyword = _normalize(keyword)
    if not normalized_keyword:
        return False
    pattern = rf"(?<![a-z0-9+#]){re.escape(normalized_keyword)}(?![a-z0-9+#])"
    return re.search(pattern, normalized_text) is not None


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_text.lower()
