from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    control_identity: dict[str, Any]
    surface_id: str | None
    required: bool
    required_evidence: list[str]
    semantic_category: str
    confidence: float
    resolved_answer: dict[str, Any] | None
    answer_source: str | None
    policy_decision: dict[str, Any] | None
    planned_action: dict[str, Any] | None
    execution_result: dict[str, Any]
    validation_result: dict[str, Any]
    blocker: dict[str, Any] | None
    reason_codes: list[str] = field(default_factory=list)
    final_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_obligation_ledger(
    *,
    schema: dict[str, Any],
    mapping: dict[str, Any],
    action_plan: dict[str, Any],
    validation_report: dict[str, Any] | None = None,
    fill_result: dict[str, Any] | None = None,
    resume_upload: dict[str, Any] | None = None,
    repair_report: dict[str, Any] | None = None,
    forbidden_submit_controls: list[dict[str, Any]] | None = None,
    surfaces: list[dict[str, Any]] | None = None,
    step_transitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation_report = validation_report or {"status": "not_attempted", "issues": []}
    fill_result = fill_result or {}
    resume_upload = resume_upload or {"status": "not_attempted"}
    repair_report = repair_report or {"status": "not_attempted"}
    action_plan = action_plan or {}
    answers = _answers_by_field(mapping)
    actions = _actions_by_field(action_plan)
    forbidden = _forbidden_by_field(action_plan)
    executed_fields = {str(item) for item in fill_result.get("filled_fields") or [] if str(item).strip()}
    skipped_fields = {str(item) for item in fill_result.get("skipped_fields") or [] if str(item).strip()}
    validation_issues = [issue for issue in validation_report.get("issues") or [] if isinstance(issue, dict)]
    issue_fields = {str(issue.get("field_name") or "") for issue in validation_issues}
    obligations: list[Obligation] = []
    for index, field in enumerate(schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("name") or field.get("id") or field.get("label") or f"field-{index}")
        answer = answers.get(field_name)
        action = actions.get(field_name)
        forbidden_action = forbidden.get(field_name)
        field_type = str(field.get("type") or "").lower()
        if field_type == "file" and resume_upload.get("status") == "uploaded":
            answer = answer or {
                "canonical_key": "resume_upload",
                "source": "verified_upload",
                "value": str(resume_upload.get("filename") or "uploaded_file"),
                "match_strategy": str(resume_upload.get("strategy") or "upload"),
            }
            action = action or {"field_name": field_name, "action_type": "upload_file"}
        policy_decision = (action or forbidden_action or {}).get("policy_decision") or (answer or {}).get("policy_decision")
        if field_type == "file" and resume_upload.get("status") == "uploaded" and not policy_decision:
            policy_decision = {
                "outcome": "ALLOW",
                "reason_code": "required_upload_verified",
                "action": "upload_file",
                "semantic_category": "resume_upload",
            }
        reason_codes: list[str] = []
        blocker = None
        if policy_decision and policy_decision.get("reason_code"):
            reason_codes.append(str(policy_decision["reason_code"]))
        if forbidden_action:
            blocker = {"reason_code": str(forbidden_action.get("reason_code") or forbidden_action.get("reason") or "policy_blocked")}
        if field_name in skipped_fields:
            blocker = {"reason_code": "planned_action_not_executed"}
            reason_codes.append("planned_action_not_executed")
        if field_name in issue_fields:
            blocker = {"reason_code": "validation_failed"}
            reason_codes.append("validation_failed")
        executed = field_name in executed_fields
        verified = False
        if field_type == "file":
            executed = resume_upload.get("status") == "uploaded"
            verified = executed
            if bool(field.get("required")) and not verified:
                blocker = {"reason_code": "required_upload_not_verified"}
                reason_codes.append("required_upload_not_verified")
        elif action:
            verified = validation_report.get("status") == "validation_clean" and executed
        if bool(field.get("required")) and not answer:
            blocker = blocker or {"reason_code": "missing_required_answer"}
            reason_codes.append("missing_required_answer")
        if bool(field.get("required")) and answer and not action and not forbidden_action and field_type != "file":
            blocker = blocker or {"reason_code": "required_action_not_planned"}
            reason_codes.append("required_action_not_planned")
        obligations.append(
            Obligation(
                obligation_id=_obligation_id(field, index),
                control_identity=_control_identity(field),
                surface_id=str(field.get("surface_id") or (field.get("control_handle") or {}).get("surface_id") or "") or None,
                required=bool(field.get("required")),
                required_evidence=_required_evidence(field),
                semantic_category=str((answer or {}).get("canonical_key") or field.get("key") or field.get("classification") or "unknown"),
                confidence=float(field.get("confidence") or 0.5),
                resolved_answer=_public_answer(answer),
                answer_source=str((answer or {}).get("source") or "") or None,
                policy_decision=policy_decision,
                planned_action=action,
                execution_result={"status": "executed" if executed else "not_executed"},
                validation_result={"status": "verified" if verified else "not_verified"},
                blocker=blocker,
                reason_codes=sorted(set(reason_codes)),
                final_evidence=_final_evidence(field, answer, action, executed, verified),
            )
        )
    unknown_requireds = _unknown_requireds(mapping)
    readiness = evaluate_submit_only_readiness(
        obligations=[item.to_dict() for item in obligations],
        validation_report=validation_report,
        repair_report=repair_report,
        forbidden_submit_controls=forbidden_submit_controls or [],
        surfaces=surfaces or [],
        step_transitions=step_transitions or [],
    )
    return {
        "version": 1,
        "obligations": [item.to_dict() for item in obligations],
        "unknown_requireds": unknown_requireds,
        "summary": {
            "total": len(obligations),
            "required": sum(1 for item in obligations if item.required),
            "resolved_required": sum(1 for item in obligations if item.required and item.resolved_answer),
            "executed_required": sum(1 for item in obligations if item.required and item.execution_result["status"] == "executed"),
            "verified_required": sum(1 for item in obligations if item.required and item.validation_result["status"] == "verified"),
            "blocked": sum(1 for item in obligations if item.blocker),
            "unknown_required": len(unknown_requireds),
        },
        "readiness": readiness,
    }


def evaluate_submit_only_readiness(
    *,
    obligations: list[dict[str, Any]],
    validation_report: dict[str, Any],
    repair_report: dict[str, Any],
    forbidden_submit_controls: list[dict[str, Any]],
    surfaces: list[dict[str, Any]],
    step_transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    required = [item for item in obligations if item.get("required")]
    if not surfaces:
        blockers.append("surfaces_not_inspected")
    if any(surface.get("accessible") is False for surface in surfaces):
        blockers.append("inaccessible_surface")
    if not required and not obligations:
        blockers.append("no_controls_registered")
    for item in required:
        if not item.get("resolved_answer"):
            blockers.append("required_answer_missing")
        policy = item.get("policy_decision") or {}
        if policy.get("outcome") != "ALLOW":
            blockers.append(str(policy.get("reason_code") or "required_policy_not_allowed"))
        if item.get("execution_result", {}).get("status") != "executed":
            blockers.append("required_action_not_executed")
        if item.get("validation_result", {}).get("status") != "verified":
            blockers.append("required_action_not_verified")
        blocker = item.get("blocker") or {}
        if blocker.get("reason_code"):
            blockers.append(str(blocker["reason_code"]))
    if validation_report.get("status") != "validation_clean":
        blockers.append("validation_not_clean")
    if int(repair_report.get("dynamic_required_count") or 0) > 0:
        blockers.append("repair_pending_dynamic_required")
    if str(repair_report.get("status") or "") not in {"", "not_attempted", "no_repair_needed", "repaired"}:
        blockers.append("repair_not_terminal")
    if len(forbidden_submit_controls) != 1:
        blockers.append("submit_boundary_missing_or_ambiguous")
    if any((transition.get("result") or {}).get("status") not in {"advanced"} for transition in step_transitions):
        blockers.append("step_transition_unverified")
    unique = sorted(set(blockers))
    return {
        "ready": not unique,
        "terminal_state": "SUBMIT_ONLY" if not unique else "NEEDS_USER_INPUT",
        "blockers": unique,
    }


def _answers_by_field(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    answers = {}
    for answer in mapping.get("answers") or []:
        if isinstance(answer, dict):
            key = str(answer.get("field_name") or "")
            if key:
                answers[key] = answer
    return answers


def _actions_by_field(action_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(action.get("field_name") or ""): action
        for action in action_plan.get("actions") or []
        if isinstance(action, dict) and str(action.get("field_name") or "")
    }


def _forbidden_by_field(action_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(action.get("field_name") or ""): action
        for action in action_plan.get("forbidden") or []
        if isinstance(action, dict) and str(action.get("field_name") or "")
    }


def _unknown_requireds(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        field for field in mapping.get("unknown_fields") or []
        if isinstance(field, dict) and (field.get("required") or field.get("sensitive") or field.get("type") == "validation")
    ]


def _obligation_id(field: dict[str, Any], index: int) -> str:
    handle = field.get("control_handle") if isinstance(field.get("control_handle"), dict) else {}
    return str(handle.get("fingerprint") or f"{field.get('surface_id') or 'main'}:{field.get('name') or field.get('id') or index}")


def _control_identity(field: dict[str, Any]) -> dict[str, Any]:
    handle = field.get("control_handle") if isinstance(field.get("control_handle"), dict) else {}
    return {
        "name": str(field.get("name") or ""),
        "id": str(field.get("id") or ""),
        "label": str(field.get("label") or ""),
        "type": str(field.get("type") or ""),
        "fingerprint": str(handle.get("fingerprint") or ""),
        "locator_strategies": list(handle.get("locator_strategies") or []),
    }


def _required_evidence(field: dict[str, Any]) -> list[str]:
    if not field.get("required"):
        return []
    evidence = ["required_attribute"]
    label = str(field.get("label") or "")
    if "*" in label:
        evidence.append("label_required_marker")
    if field.get("locator_strategy"):
        evidence.append(f"locator:{field['locator_strategy']}")
    return evidence


def _public_answer(answer: dict[str, Any] | None) -> dict[str, Any] | None:
    if not answer:
        return None
    value = str(answer.get("value") or "")
    return {
        "canonical_key": answer.get("canonical_key"),
        "source": answer.get("source"),
        "status": answer.get("answer_status"),
        "has_value": bool(value.strip()),
        "value_preview": value[:80] if value else None,
        "match_strategy": answer.get("match_strategy"),
    }


def _final_evidence(
    field: dict[str, Any],
    answer: dict[str, Any] | None,
    action: dict[str, Any] | None,
    executed: bool,
    verified: bool,
) -> list[str]:
    evidence = []
    if answer and str(answer.get("value") or "").strip():
        evidence.append("answer_resolved")
    if action:
        evidence.append("action_planned")
    if executed:
        evidence.append("action_executed")
    if verified:
        evidence.append("postcondition_verified")
    if field.get("control_handle"):
        evidence.append("control_fingerprinted")
    return evidence
