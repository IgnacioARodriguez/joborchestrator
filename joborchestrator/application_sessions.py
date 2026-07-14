from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any


STATES = {
    "created",
    "preflight",
    "preparing_materials",
    "ready_to_fill",
    "filling",
    "needs_user_input",
    "ready_for_review",
    "approved",
    "submitting",
    "submitted",
    "verification_failed",
    "failed",
    "cancelled",
}

TRANSITIONS = {
    "created": {"preflight", "cancelled", "failed"},
    "preflight": {"preparing_materials", "ready_to_fill", "needs_user_input", "failed", "cancelled"},
    "preparing_materials": {"ready_to_fill", "needs_user_input", "failed", "cancelled"},
    "ready_to_fill": {"filling", "needs_user_input", "cancelled"},
    "filling": {"ready_for_review", "needs_user_input", "failed", "cancelled"},
    "needs_user_input": {"ready_to_fill", "filling", "cancelled"},
    "ready_for_review": {"approved", "cancelled"},
    "approved": {"submitting", "cancelled"},
    "submitting": {"submitted", "verification_failed", "failed"},
    "verification_failed": {"submitting", "failed", "cancelled"},
    "failed": {"preflight", "cancelled"},
    "cancelled": set(),
    "submitted": set(),
}


@dataclass(frozen=True)
class SessionTransition:
    from_state: str
    to_state: str
    idempotent: bool = False


def validate_transition(current: str, target: str) -> SessionTransition:
    if current not in STATES or target not in STATES:
        raise ValueError(f"Unknown application session state: {current} -> {target}")
    if current == target:
        return SessionTransition(current, target, True)
    if target not in TRANSITIONS[current]:
        raise ValueError(f"Invalid application session transition: {current} -> {target}")
    return SessionTransition(current, target)


def new_idempotency_key(job_id: int, provider: str, mode: str) -> str:
    return f"{job_id}:{provider}:{mode}:{secrets.token_hex(8)}"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
