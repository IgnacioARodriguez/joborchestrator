from __future__ import annotations

from typing import Any

from joborchestrator.automation.policy import evaluate_answer_action


def policy_intervention_items(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Return user-owned form actions omitted from unattended execution."""
    items: list[dict[str, Any]] = []
    for answer in mapping.get("answers") or []:
        if not isinstance(answer, dict):
            continue
        decision = evaluate_answer_action(answer, action=_action_type(answer))
        if decision.outcome == "ALLOW":
            continue
        field = str(answer.get("field_name") or answer.get("canonical_key") or "").strip()
        if not field:
            continue
        items.append(
            {
                "type": _intervention_type(decision.reason_code),
                "field": field,
                "label": str(answer.get("label") or field).strip(),
                "reason": decision.reason_code,
                "semantic_category": decision.semantic_category,
                "required": bool(answer.get("required")),
                "sensitive": bool(answer.get("sensitive")),
            }
        )
    return items


def _action_type(answer: dict[str, Any]) -> str:
    return {
        "select": "select_option",
        "radio": "choose_radio",
        "checkbox": "check",
        "file": "upload_file",
    }.get(str(answer.get("field_type") or "text"), "fill_text")


def _intervention_type(reason_code: str) -> str:
    if reason_code == "legal_consent_reserved_for_user":
        return "consent"
    if reason_code == "optional_demographic_reserved_for_user":
        return "demographic"
    if reason_code.endswith("_automation_denied"):
        return "challenge"
    return "answer"
