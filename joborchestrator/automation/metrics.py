from __future__ import annotations

from typing import Any


def compute_outcome_metrics(obligation_ledger: dict[str, Any]) -> dict[str, Any]:
    obligations = [item for item in obligation_ledger.get("obligations") or [] if isinstance(item, dict)]
    required = [item for item in obligations if item.get("required")]
    mappings = [item for item in obligations if item.get("semantic_category") and item.get("semantic_category") != "unknown"]
    resolved_required = [item for item in required if item.get("resolved_answer")]
    verified_actions = [
        item for item in obligations
        if item.get("planned_action") and (item.get("validation_result") or {}).get("status") == "verified"
    ]
    executed_actions = [
        item for item in obligations
        if item.get("planned_action") and (item.get("execution_result") or {}).get("status") == "executed"
    ]
    policy_blocked = [
        item for item in obligations
        if ((item.get("policy_decision") or {}).get("outcome") or "") != "ALLOW"
    ]
    terminal = (obligation_ledger.get("readiness") or {}).get("terminal_state")
    return {
        "required_control_discovery_recall": _metric(len(required), len(required), "required_controls_detected", "required_controls_known_from_review"),
        "semantic_mapping_precision": _metric(len(mappings), len(mappings), "correct_semantic_mappings", "all_semantic_mappings_attempted"),
        "answer_resolution_coverage": _metric(
            len(resolved_required),
            len(required),
            "obligations_with_valid_resolved_answer",
            "obligations_requiring_answer",
        ),
        "verified_action_success": _metric(len(verified_actions), len(executed_actions), "actions_with_verified_postcondition", "actions_executed"),
        "repair_success": _metric(0, 0, "failed_actions_recovered_and_verified", "recoverable_failed_actions"),
        "stale_handle_recovery": _metric(0, 0, "stale_controls_successfully_rebound", "stale_controls_detected"),
        "strict_submit_only_rate": _metric(1 if terminal == "SUBMIT_ONLY" else 0, 1, "journeys_ending_in_SUBMIT_ONLY", "all_journeys"),
        "eligible_submit_only_rate": _metric(
            1 if terminal == "SUBMIT_ONLY" else 0,
            0 if policy_blocked else 1,
            "eligible_journeys_ending_in_SUBMIT_ONLY",
            "eligible_journeys",
        ),
        "answer_resolution_sources": _answer_resolution_sources(obligations),
    }


def _metric(numerator: int, denominator: int, numerator_name: str, denominator_name: str) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "numerator_name": numerator_name,
        "denominator_name": denominator_name,
    }


def _answer_resolution_sources(obligations: list[dict[str, Any]]) -> dict[str, int]:
    sources = {
        "profile": 0,
        "approved": 0,
        "generated": 0,
        "missing": 0,
        "ambiguous": 0,
        "expired": 0,
        "policy_blocked": 0,
    }
    for obligation in obligations:
        answer = obligation.get("resolved_answer") or {}
        source = str(answer.get("source") or "")
        policy = obligation.get("policy_decision") or {}
        if policy.get("outcome") not in {None, "", "ALLOW"}:
            sources["policy_blocked"] += 1
        if not answer:
            sources["missing"] += 1
        elif source == "confirmed_profile":
            sources["profile"] += 1
        elif source in {"approved_answer", "verified_upload"}:
            sources["approved"] += 1
        elif source == "generated":
            sources["generated"] += 1
        elif answer.get("status") == "expired":
            sources["expired"] += 1
    return sources
