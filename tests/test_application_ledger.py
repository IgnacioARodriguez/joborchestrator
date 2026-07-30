from __future__ import annotations

from joborchestrator.automation.ledger import build_obligation_ledger


def test_obligation_ledger_reaches_submit_only_only_when_required_actions_are_verified() -> None:
    ledger = build_obligation_ledger(
        schema={
            "fields": [
                {
                    "name": "email",
                    "label": "Email",
                    "type": "email",
                    "required": True,
                    "surface_id": "main",
                    "control_handle": {"fingerprint": "main:email:email:true", "locator_strategies": ["label_for"]},
                }
            ]
        },
        mapping={
            "answers": [
                {
                    "field_name": "email",
                    "canonical_key": "email",
                    "field_type": "email",
                    "value": "candidate@example.test",
                    "source": "confirmed_profile",
                }
            ],
            "unknown_fields": [],
        },
        action_plan={
            "actions": [
                {
                    "field_name": "email",
                    "action_type": "fill_text",
                    "policy_decision": {"outcome": "ALLOW", "reason_code": "authorized_answer"},
                }
            ],
            "forbidden": [],
        },
        validation_report={"status": "validation_clean", "issues": [], "checked_postconditions": 1, "satisfied_postconditions": 1},
        fill_result={"filled_fields": ["email"], "skipped_fields": []},
        resume_upload={"status": "not_applicable"},
        repair_report={"status": "no_repair_needed", "dynamic_required_count": 0},
        forbidden_submit_controls=[{"text": "Submit application"}],
        surfaces=[{"surface_id": "main", "accessible": True}],
        step_transitions=[],
    )

    assert ledger["summary"]["required"] == 1
    assert ledger["summary"]["verified_required"] == 1
    assert ledger["readiness"]["terminal_state"] == "SUBMIT_ONLY"
    assert ledger["readiness"]["blockers"] == []


def test_obligation_ledger_fails_closed_for_unverified_required_upload() -> None:
    ledger = build_obligation_ledger(
        schema={
            "fields": [
                {
                    "name": "resume",
                    "label": "Resume",
                    "type": "file",
                    "required": True,
                    "surface_id": "main",
                }
            ]
        },
        mapping={
            "answers": [
                {
                    "field_name": "resume",
                    "canonical_key": "resume",
                    "field_type": "file",
                    "value": "resume.pdf",
                    "source": "approved_answer",
                }
            ],
            "unknown_fields": [],
        },
        action_plan={"actions": [{"field_name": "resume", "action_type": "upload_file", "policy_decision": {"outcome": "ALLOW"}}]},
        validation_report={"status": "validation_clean", "issues": []},
        fill_result={"filled_fields": [], "skipped_fields": []},
        resume_upload={"status": "unresolved", "reason": "missing_resume_file"},
        repair_report={"status": "no_repair_needed", "dynamic_required_count": 0},
        forbidden_submit_controls=[{"text": "Submit application"}],
        surfaces=[{"surface_id": "main", "accessible": True}],
        step_transitions=[],
    )

    assert ledger["readiness"]["terminal_state"] == "NEEDS_USER_INPUT"
    assert "required_upload_not_verified" in ledger["readiness"]["blockers"]
    assert "required_action_not_verified" in ledger["readiness"]["blockers"]
