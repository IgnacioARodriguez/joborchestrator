from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SurfaceNode:
    surface_id: str
    kind: str
    origin: str
    parent_surface_id: str | None = None
    accessible: bool = True
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LogicalControlIdentity:
    surface_id: str
    semantic_category: str
    role: str
    native_type: str
    accessible_name: str
    label: str
    option_fingerprint: str
    required: bool
    locator_strategies: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_surface_fingerprint(*, kind: str, origin: str, parent_surface_id: str | None = None, index: int | None = None) -> str:
    parts = [kind, origin, parent_surface_id or "", "" if index is None else str(index)]
    return _digest("|".join(parts))


def logical_control_identity(field: dict[str, Any], *, surface_id: str, index: int = 0) -> LogicalControlIdentity:
    native_type = str(field.get("type") or "text").lower()
    label = str(field.get("label") or field.get("name") or field.get("id") or "").strip()
    semantic = str(field.get("key") or field.get("classification") or "").strip() or _safe_key(label)
    role = {
        "select": "choice",
        "radio": "choice",
        "checkbox": "boolean",
        "file": "file",
        "textarea": "text",
    }.get(native_type, "text")
    options = [
        _normalized(str(option.get("label") or option.get("value") or ""))
        for option in field.get("options") or []
        if isinstance(option, dict)
    ]
    locator_strategy = str(field.get("locator_strategy") or "")
    strategies = [locator_strategy] if locator_strategy else []
    if field.get("in_shadow_root"):
        strategies.append("shadow_root")
    option_fingerprint = _digest("|".join(sorted(item for item in options if item)))
    stable_parts = [
        surface_id,
        semantic,
        role,
        native_type,
        _normalized(label),
        option_fingerprint,
        str(bool(field.get("required"))),
    ]
    fingerprint = _digest("|".join(stable_parts))
    return LogicalControlIdentity(
        surface_id=surface_id,
        semantic_category=semantic,
        role=role,
        native_type=native_type,
        accessible_name=label,
        label=label,
        option_fingerprint=option_fingerprint,
        required=bool(field.get("required")),
        locator_strategies=strategies,
        fingerprint=fingerprint,
    )


def rebind_control(schema: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any] | None:
    wanted = str(identity.get("fingerprint") or "")
    fields = [field for field in schema.get("fields") or [] if isinstance(field, dict)]
    exact_matches = []
    for field in fields:
        handle = field.get("control_handle") if isinstance(field.get("control_handle"), dict) else {}
        current = str(handle.get("fingerprint") or "")
        if wanted and current == wanted:
            exact_matches.append(field)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None
    candidates = []
    for field in fields:
        handle = field.get("control_handle") if isinstance(field.get("control_handle"), dict) else {}
        logical = handle.get("logical_identity") if isinstance(handle.get("logical_identity"), dict) else {}
        score = _identity_match_score(identity, logical)
        if score >= 4:
            candidates.append((score, field))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def _identity_match_score(expected: dict[str, Any], actual: dict[str, Any]) -> int:
    score = 0
    for key in ("surface_id", "semantic_category", "role", "native_type", "option_fingerprint"):
        if expected.get(key) and expected.get(key) == actual.get(key):
            score += 1
    expected_label = _normalized(str(expected.get("label") or expected.get("accessible_name") or ""))
    actual_label = _normalized(str(actual.get("label") or actual.get("accessible_name") or ""))
    if expected_label and expected_label == actual_label:
        score += 2
    if bool(expected.get("required")) == bool(actual.get("required")):
        score += 1
    return score


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "field"


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", value.lower())).strip()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
