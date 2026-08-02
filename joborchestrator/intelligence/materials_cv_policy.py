from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable

EXPERIENCE_DENSITY_CHAR_RATIO = 0.45
EXPERIENCE_DENSITY_BULLET_RULES = (
    {"ratio": 0.50, "floor": 4, "cap": 6},
    {"ratio": 0.35, "floor": 3, "cap": 5},
    {"ratio": 0.25, "floor": 1, "cap": 3},
)


def required_bullets_for_role(
    role_index: int,
    source_bullets: int,
    *,
    explicit_minimum: int = 0,
) -> int:
    """Return the single source of truth for role-detail preservation."""
    count = max(0, int(source_bullets))
    if count == 0:
        return 0
    rule = EXPERIENCE_DENSITY_BULLET_RULES[
        min(max(0, int(role_index)), len(EXPERIENCE_DENSITY_BULLET_RULES) - 1)
    ]
    proportional = math.ceil(count * float(rule["ratio"]))
    floor = min(int(rule["floor"]), count)
    policy_required = min(count, int(rule["cap"]), max(floor, proportional))
    return min(count, max(policy_required, max(0, int(explicit_minimum))))


def technology_key(value: str) -> str:
    normalized = _normalize(value)
    aliases = {
        "api": "api",
        "apis": "api",
        "rest api": "rest api",
        "rest apis": "rest api",
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "js": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "typescript": "typescript",
        "k8s": "kubernetes",
        "kubernetes": "kubernetes",
    }
    return aliases.get(normalized, normalized)


def dedupe_technologies(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = technology_key(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def technology_difference(left: Iterable[str], right: Iterable[str]) -> list[str]:
    right_keys = {technology_key(value) for value in right if str(value or "").strip()}
    return [
        value
        for value in dedupe_technologies(left)
        if technology_key(value) not in right_keys
    ]


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    ascii_text = re.sub(r"[^a-z0-9+#.]+", " ", ascii_text.casefold())
    return re.sub(r"\s+", " ", ascii_text).strip(" .")
