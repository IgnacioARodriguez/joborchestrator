from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MATERIAL_TARGETS = ("ats_cv", "cover_letter", "recruiter_message", "autofill")


def normalize_material_targets(targets: Iterable[str] | None) -> list[str] | None:
    if not targets:
        return None
    normalized: list[str] = []
    for target in targets:
        value = str(target)
        if value not in MATERIAL_TARGETS:
            raise ValueError(f"Unsupported material target: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized or None


def operation_covers_targets(existing_targets: object, requested_targets: list[str] | None) -> bool:
    existing = normalize_material_targets(existing_targets if isinstance(existing_targets, list) else None)
    if existing is None:
        return True
    if requested_targets is None:
        return False
    return set(requested_targets).issubset(existing)


def next_material_review_states(
    current_states: Mapping[str, Any] | None,
    targets: Iterable[str] | None,
    generated: Mapping[str, Any],
) -> dict[str, str]:
    states = {str(key): str(value) for key, value in (current_states or {}).items()}
    selected = normalize_material_targets(targets) or list(MATERIAL_TARGETS)
    for material in selected:
        value = str(generated.get(material) or "").strip()
        if value:
            states[material] = "ready_for_review"
        elif material == "cover_letter":
            states[material] = "not_required"
        else:
            states[material] = "pending"
    return states
