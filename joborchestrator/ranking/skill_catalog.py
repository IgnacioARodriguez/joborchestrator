from __future__ import annotations

from joborchestrator.profile_skill_catalog import DEFAULT_SKILL_CATALOG
from joborchestrator.scanning.normalization import normalize_text


def find_skills(text: str) -> list[str]:
    normalized = normalize_text(text)
    found = []
    for skill in sorted(_skill_terms(), key=len, reverse=True):
        if _contains_term(normalized, normalize_text(skill)):
            found.append(skill)
    return _dedupe(found)


def _skill_terms() -> list[str]:
    try:
        from joborchestrator.storage import persistence as db

        rows = db.list_skill_catalog()
        terms = [str(row["name"]) for row in rows if row.get("name")]
        if terms:
            return terms
    except Exception:
        pass
    return [skill for skills in DEFAULT_SKILL_CATALOG.values() for skill in skills]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _contains_term(text: str, term: str) -> bool:
    padded = f" {text} "
    if f" {term} " in padded:
        return True
    if term.endswith("s") and f" {term[:-1]} " in padded:
        return True
    if not term.endswith("s") and f" {term}s " in padded:
        return True
    return False
