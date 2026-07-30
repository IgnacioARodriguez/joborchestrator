from __future__ import annotations

from typing import Any


def compute_outcome_metrics(
    obligation_ledger: dict[str, Any],
    *,
    fixture_ground_truth: dict[str, Any] | None = None,
    fixture_id: str | None = None,
) -> dict[str, Any]:
    if fixture_ground_truth:
        return _compute_fixture_outcome_metrics(
            obligation_ledger,
            fixture_ground_truth=fixture_ground_truth,
            fixture_id=fixture_id or str(fixture_ground_truth.get("id") or "fixture"),
        )
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
        "sample_size": 1,
        "failed_cases": [],
        "failed_fixture_ids": [],
    }


def aggregate_outcome_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "required_control_discovery_recall",
        "semantic_mapping_precision",
        "answer_resolution_coverage",
        "verified_action_success",
        "repair_success",
        "stale_handle_recovery",
        "strict_submit_only_rate",
        "eligible_submit_only_rate",
    ]
    aggregated: dict[str, Any] = {}
    for name in metric_names:
        items = [(result.get("outcome_metrics") or {}).get(name) or result.get(name) for result in results]
        items = [item for item in items if isinstance(item, dict)]
        numerator = sum(int(item.get("numerator") or 0) for item in items)
        denominator = sum(int(item.get("denominator") or 0) for item in items)
        failed_cases = []
        failed_fixture_ids = []
        for item in items:
            failed_cases.extend(list(item.get("failed_cases") or []))
            failed_fixture_ids.extend(str(value) for value in item.get("failed_fixture_ids") or [])
        aggregated[name] = {
            "numerator": numerator,
            "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None,
            "numerator_name": str(items[0].get("numerator_name") or name) if items else name,
            "denominator_name": str(items[0].get("denominator_name") or name) if items else name,
            "sample_size": len(items),
            "failed_cases": failed_cases,
            "failed_fixture_ids": sorted(set(failed_fixture_ids)),
        }
    return aggregated


def _compute_fixture_outcome_metrics(
    obligation_ledger: dict[str, Any],
    *,
    fixture_ground_truth: dict[str, Any],
    fixture_id: str,
) -> dict[str, Any]:
    obligations = [item for item in obligation_ledger.get("obligations") or [] if isinstance(item, dict)]
    obligations_by_control = {_obligation_control_name(item): item for item in obligations}
    required_declared = [str(item) for item in fixture_ground_truth.get("required_controls") or []]
    expected_mappings = {
        str(key): str(value)
        for key, value in (fixture_ground_truth.get("expected_semantic_mappings") or {}).items()
    }
    expected_answers = {
        str(key): str(value)
        for key, value in (fixture_ground_truth.get("expected_answers") or {}).items()
    }
    expected_actions = [str(item) for item in fixture_ground_truth.get("expected_automatable_actions") or []]
    recoverable_failures = [str(item) for item in fixture_ground_truth.get("recoverable_failures") or []]
    stale_controls = [str(item) for item in fixture_ground_truth.get("stale_controls") or []]
    terminal = str((obligation_ledger.get("readiness") or {}).get("terminal_state") or "")
    expected_terminal = str(fixture_ground_truth.get("expected_terminal_state") or "")
    repair_report = obligation_ledger.get("repair_report") or fixture_ground_truth.get("repair_report") or {}

    detected_required = [
        _obligation_control_name(item)
        for item in obligations
        if item.get("required")
    ]
    required_correct = sum(1 for control in required_declared if control in detected_required)
    duplicate_penalty = max(0, len(detected_required) - len(set(detected_required)))
    optional_required = [
        control for control in detected_required
        if control and control not in set(required_declared)
    ]
    required_numerator = max(0, required_correct - duplicate_penalty - len(optional_required))

    attempted_mappings = {
        name: str(item.get("semantic_category") or "")
        for name, item in obligations_by_control.items()
        if str(item.get("semantic_category") or "") and str(item.get("semantic_category") or "") != "unknown"
    }
    semantic_correct = sum(
        1 for control, expected in expected_mappings.items()
        if attempted_mappings.get(control) == expected
    )

    answer_correct = 0
    for control in required_declared:
        obligation = obligations_by_control.get(control) or {}
        expected = expected_answers.get(control)
        if not expected:
            continue
        if _answer_source_bucket(obligation) == expected:
            answer_correct += 1

    verified_correct = sum(
        1 for control in expected_actions
        if ((obligations_by_control.get(control) or {}).get("validation_result") or {}).get("status") == "verified"
    )
    repaired = _repair_verified(repair_report)
    stale_rebound = _stale_rebound_verified(repair_report)
    strict_ok = terminal == expected_terminal == "SUBMIT_ONLY"
    eligible = bool(fixture_ground_truth.get("eligible_submit_only"))
    eligible_ok = eligible and terminal == "SUBMIT_ONLY"

    return {
        "required_control_discovery_recall": _fixture_metric(
            required_numerator,
            len(required_declared),
            "required_controls_detected_correctly",
            "required_controls_declared_in_fixture",
            fixture_id,
            required_numerator == len(required_declared),
        ),
        "semantic_mapping_precision": _fixture_metric(
            semantic_correct,
            len(attempted_mappings),
            "correct_semantic_mappings",
            "semantic_mappings_attempted",
            fixture_id,
            semantic_correct == len(attempted_mappings),
        ),
        "answer_resolution_coverage": _fixture_metric(
            answer_correct,
            len(required_declared),
            "required_answer_obligations_resolved_correctly",
            "required_answer_obligations_declared_in_fixture",
            fixture_id,
            answer_correct == len(required_declared),
        ),
        "verified_action_success": _fixture_metric(
            verified_correct,
            len(expected_actions),
            "actions_matching_expected_verified_postconditions",
            "expected_automatable_actions",
            fixture_id,
            verified_correct == len(expected_actions),
        ),
        "repair_success": _fixture_metric(
            len(recoverable_failures) if repaired else 0,
            len(recoverable_failures),
            "recoverable_failures_repaired_and_verified",
            "recoverable_failures_declared",
            fixture_id,
            repaired or not recoverable_failures,
        ),
        "stale_handle_recovery": _fixture_metric(
            len(stale_controls) if stale_rebound else 0,
            len(stale_controls),
            "stale_controls_rebound_and_completed",
            "stale_controls_declared",
            fixture_id,
            stale_rebound or not stale_controls,
        ),
        "strict_submit_only_rate": _fixture_metric(
            1 if strict_ok else 0,
            1,
            "fixtures_correctly_ending_in_SUBMIT_ONLY",
            "all_fixtures",
            fixture_id,
            strict_ok or expected_terminal != "SUBMIT_ONLY",
        ),
        "eligible_submit_only_rate": _fixture_metric(
            1 if eligible_ok else 0,
            1 if eligible else 0,
            "eligible_fixtures_ending_in_SUBMIT_ONLY",
            "eligible_fixtures_declared_in_fixture",
            fixture_id,
            eligible_ok or not eligible,
        ),
        "answer_resolution_sources": _answer_resolution_sources(obligations),
    }


def _fixture_metric(
    numerator: int,
    denominator: int,
    numerator_name: str,
    denominator_name: str,
    fixture_id: str,
    ok: bool,
) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "numerator_name": numerator_name,
        "denominator_name": denominator_name,
        "sample_size": 1,
        "failed_cases": [] if ok else [fixture_id],
        "failed_fixture_ids": [] if ok else [fixture_id],
    }


def _obligation_control_name(obligation: dict[str, Any]) -> str:
    identity = obligation.get("control_identity") if isinstance(obligation.get("control_identity"), dict) else {}
    action = obligation.get("planned_action") if isinstance(obligation.get("planned_action"), dict) else {}
    return str(identity.get("name") or identity.get("id") or action.get("field_name") or obligation.get("obligation_id") or "")


def _answer_source_bucket(obligation: dict[str, Any]) -> str:
    policy = obligation.get("policy_decision") or {}
    if policy.get("outcome") not in {None, "", "ALLOW"}:
        return "policy-blocked"
    answer = obligation.get("resolved_answer") or {}
    if not answer:
        return "missing"
    source = str(answer.get("source") or "")
    status = str(answer.get("status") or "")
    if status == "expired":
        return "expired"
    if source == "confirmed_profile":
        return "profile"
    if source == "approved_answer":
        return "approved_answer"
    if source == "verified_upload":
        return "verified_upload"
    if source == "generated":
        return "generated"
    return source or "ambiguous"


def _repair_verified(repair_report: dict[str, Any]) -> bool:
    if repair_report.get("status") == "repaired":
        return True
    return any((attempt.get("second_validation") or {}).get("status") == "validation_clean" for attempt in repair_report.get("retry_attempts") or [])


def _stale_rebound_verified(repair_report: dict[str, Any]) -> bool:
    return any(
        attempt.get("rebound") is True and (attempt.get("second_validation") or {}).get("status") == "validation_clean"
        for attempt in repair_report.get("retry_attempts") or []
        if isinstance(attempt, dict)
    )


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
