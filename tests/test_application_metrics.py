from __future__ import annotations

from joborchestrator.automation.metrics import compute_outcome_metrics


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
    }
    assert metrics["strict_submit_only_rate"]["rate"] == 1.0
    assert metrics["answer_resolution_sources"]["profile"] == 1
