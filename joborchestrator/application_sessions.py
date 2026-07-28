from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any


STATES = {
    "created",
    "preparing",
    "preflight",
    "preparing_materials",
    "materials_ready",
    "opened",
    "ready_to_fill",
    "filling",
    "prefilled",
    "needs_user_input",
    "ready_for_review",
    "approved",
    "submitting",
    "submitted",
    "submitted_manually",
    "submission_verified",
    "verification_failed",
    "rejected",
    "withdrawn",
    "failed",
    "cancelled",
}

TRANSITIONS = {
    "created": {"preparing", "preflight", "cancelled", "failed"},
    "preparing": {"preflight", "preparing_materials", "materials_ready", "opened", "needs_user_input", "failed", "cancelled"},
    "preflight": {"preparing_materials", "materials_ready", "opened", "ready_to_fill", "needs_user_input", "failed", "cancelled"},
    "preparing_materials": {"materials_ready", "ready_to_fill", "needs_user_input", "failed", "cancelled"},
    "materials_ready": {"opened", "ready_to_fill", "needs_user_input", "failed", "cancelled"},
    "opened": {"ready_to_fill", "filling", "needs_user_input", "failed", "cancelled"},
    "ready_to_fill": {"filling", "prefilled", "needs_user_input", "cancelled"},
    "filling": {"prefilled", "ready_for_review", "needs_user_input", "failed", "cancelled"},
    "prefilled": {"ready_for_review", "needs_user_input", "failed", "cancelled"},
    "needs_user_input": {"ready_to_fill", "filling", "ready_for_review", "submitted_manually", "cancelled"},
    "ready_for_review": {"submitted_manually", "approved", "cancelled"},
    "approved": {"submitting", "cancelled"},
    "submitting": {"submitted", "verification_failed", "failed"},
    "submitted": {"submission_verified"},
    "submitted_manually": {"submission_verified", "rejected", "withdrawn"},
    "submission_verified": {"rejected", "withdrawn"},
    "verification_failed": {"submitting", "failed", "cancelled"},
    "rejected": set(),
    "withdrawn": set(),
    "failed": {"preflight", "cancelled"},
    "cancelled": set(),
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
