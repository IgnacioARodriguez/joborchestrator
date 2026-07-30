from __future__ import annotations

from joborchestrator.automation.metrics import aggregate_outcome_metrics, compute_outcome_metrics


def test_outcome_metrics_emit_explicit_numerators_and_denominators() -> None:
    metrics = compute_outcome_metrics(
        {
            "readiness": {"terminal_state": "SUBMIT_ONLY"},
            "obligations": [
                {
                    "required": True,
                    "semantic_category": "email",
                    "resolved_answer": {"source": "confirmed_profile"},
                    "policy_decision": {"outcome": "ALLOW"},
                    "planned_action": {"action_type": "fill_text"},
                    "execution_result": {"status": "executed"},
                    "validation_result": {"status": "verified"},
                }
            ],
        }
    )

    assert metrics["answer_resolution_coverage"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
        "numerator_name": "obligations_with_valid_resolved_answer",
        "denominator_name": "obligations_requiring_answer",
        "sample_size": 1,
        "failed_cases": [],
        "failed_fixture_ids": [],
    }
    assert metrics["strict_submit_only_rate"]["rate"] == 1.0
    assert metrics["answer_resolution_sources"]["profile"] == 1


def test_outcome_metrics_use_fixture_ground_truth_denominators() -> None:
    fixture = {
        "id": "fixture-a",
        "required_controls": ["name", "email", "resume"],
        "expected_semantic_mappings": {"name": "full_name", "email": "email", "resume": "resume_upload"},
        "expected_answers": {"name": "profile", "email": "profile", "resume": "verified_upload"},
        "expected_automatable_actions": ["name", "email", "resume"],
        "expected_terminal_state": "SUBMIT_ONLY",
        "eligible_submit_only": True,
        "recoverable_failures": ["name"],
        "stale_controls": ["name"],
    }
    ledger = {
        "readiness": {"terminal_state": "SUBMIT_ONLY"},
        "repair_report": {
            "status": "repaired",
            "retry_attempts": [{"rebound": True, "second_validation": {"status": "validation_clean"}}],
        },
        "obligations": [
            {
                "required": True,
                "semantic_category": "full_name",
                "control_identity": {"name": "name"},
                "resolved_answer": {"source": "confirmed_profile"},
                "policy_decision": {"outcome": "ALLOW"},
                "planned_action": {"field_name": "name", "action_type": "fill_text"},
                "execution_result": {"status": "executed"},
                "validation_result": {"status": "verified"},
            },
            {
                "required": True,
                "semantic_category": "email",
                "control_identity": {"name": "email"},
                "resolved_answer": {"source": "confirmed_profile"},
                "policy_decision": {"outcome": "ALLOW"},
                "planned_action": {"field_name": "email", "action_type": "fill_text"},
                "execution_result": {"status": "executed"},
                "validation_result": {"status": "verified"},
            },
            {
                "required": True,
                "semantic_category": "resume_upload",
                "control_identity": {"name": "resume"},
                "resolved_answer": {"source": "verified_upload"},
                "policy_decision": {"outcome": "ALLOW"},
                "planned_action": {"field_name": "resume", "action_type": "upload_file"},
                "execution_result": {"status": "executed"},
                "validation_result": {"status": "verified"},
            },
        ],
    }

    metrics = compute_outcome_metrics(ledger, fixture_ground_truth=fixture)

    assert metrics["required_control_discovery_recall"]["denominator"] == 3
    assert metrics["semantic_mapping_precision"]["denominator"] == 3
    assert metrics["answer_resolution_coverage"]["denominator"] == 3
    assert metrics["verified_action_success"]["denominator"] == 3
    assert metrics["repair_success"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
        "numerator_name": "recoverable_failures_repaired_and_verified",
        "denominator_name": "recoverable_failures_declared",
        "sample_size": 1,
        "failed_cases": [],
        "failed_fixture_ids": [],
    }
    assert metrics["stale_handle_recovery"]["denominator"] == 1
    assert metrics["eligible_submit_only_rate"]["denominator"] == 1


def test_outcome_metrics_report_failed_fixture_ids_for_ground_truth_misses() -> None:
    fixture = {
        "id": "wrong-control-assignment",
        "required_controls": ["email", "linkedin"],
        "expected_semantic_mappings": {"email": "email", "linkedin": "linkedin"},
        "expected_answers": {"email": "profile", "linkedin": "profile"},
        "expected_automatable_actions": ["email", "linkedin"],
        "expected_terminal_state": "SUBMIT_ONLY",
        "eligible_submit_only": True,
        "recoverable_failures": [],
        "stale_controls": [],
    }
    ledger = {
        "readiness": {"terminal_state": "SUBMIT_ONLY"},
        "obligations": [
            {
                "required": True,
                "semantic_category": "linkedin",
                "control_identity": {"name": "email"},
                "resolved_answer": {"source": "confirmed_profile"},
                "policy_decision": {"outcome": "ALLOW"},
                "planned_action": {"field_name": "email"},
                "execution_result": {"status": "executed"},
                "validation_result": {"status": "verified"},
            }
        ],
    }

    metrics = compute_outcome_metrics(ledger, fixture_ground_truth=fixture)

    assert metrics["required_control_discovery_recall"]["numerator"] == 1
    assert metrics["required_control_discovery_recall"]["denominator"] == 2
    assert metrics["semantic_mapping_precision"]["numerator"] == 0
    assert metrics["semantic_mapping_precision"]["failed_fixture_ids"] == ["wrong-control-assignment"]
    assert metrics["eligible_submit_only_rate"]["rate"] == 1.0


def test_aggregate_outcome_metrics_preserves_failed_fixture_ids() -> None:
    scorecard = aggregate_outcome_metrics(
        [
            {
                "outcome_metrics": {
                    "repair_success": {
                        "numerator": 0,
                        "denominator": 1,
                        "numerator_name": "recoverable_failures_repaired_and_verified",
                        "denominator_name": "recoverable_failures_declared",
                        "failed_cases": ["retry-exhaustion-terminal"],
                        "failed_fixture_ids": ["retry-exhaustion-terminal"],
                    }
                }
            },
            {
                "outcome_metrics": {
                    "repair_success": {
                        "numerator": 1,
                        "denominator": 1,
                        "numerator_name": "recoverable_failures_repaired_and_verified",
                        "denominator_name": "recoverable_failures_declared",
                        "failed_cases": [],
                        "failed_fixture_ids": [],
                    }
                }
            },
        ]
    )

    assert scorecard["repair_success"]["numerator"] == 1
    assert scorecard["repair_success"]["denominator"] == 2
    assert scorecard["repair_success"]["rate"] == 0.5
    assert scorecard["repair_success"]["failed_fixture_ids"] == ["retry-exhaustion-terminal"]
