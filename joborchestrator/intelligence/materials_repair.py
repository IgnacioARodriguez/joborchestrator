from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from joborchestrator.intelligence.materials_keywords import derive_keywords_used
from joborchestrator.intelligence.materials_validation import ValidationIssue

SEMANTIC_REPAIR_FIELDS = {
    "OVERCONFIDENT_TONE": ["recruiter_message", "cover_letter", "autofill", "autofill_notes"],
    "FORBIDDEN_ALIAS": ["recruiter_message", "cover_letter", "autofill", "autofill_notes", "ats_cv_text"],
    "INTERNAL_LANGUAGE_LEAK": ["recruiter_message", "cover_letter", "autofill", "autofill_notes", "ats_cv_text"],
    "LANGUAGE_MISMATCH": ["recruiter_message", "cover_letter", "autofill", "autofill_notes"],
    "AUTOFILL_SHAPE_INVALID": ["autofill", "autofill_notes"],
}


@dataclass(frozen=True)
class RepairDirective:
    previous_response: dict[str, Any]
    issues: list[ValidationIssue]
    mutable_fields: list[str]
    frozen_fields: list[str]


def deterministic_repair(
    response: dict[str, Any],
    issues: list[ValidationIssue],
    *,
    supported_keywords: list[str],
) -> tuple[dict[str, Any], list[ValidationIssue]]:
    repaired = dict(response)
    remaining: list[ValidationIssue] = []
    for issue in issues:
        if issue.code == "KEYWORD_METADATA_MISMATCH":
            repaired["keywords_used"] = derive_keywords_used(str(repaired.get("ats_cv_text") or ""), supported_keywords)
        else:
            remaining.append(issue)
    return repaired, remaining


def build_repair_directive(previous_response: dict[str, Any], issues: list[ValidationIssue]) -> RepairDirective:
    mutable: list[str] = []
    for issue in issues:
        for field in SEMANTIC_REPAIR_FIELDS.get(issue.code, [issue.field]):
            if field not in mutable:
                mutable.append(field)
    if not mutable:
        mutable = ["ats_cv_text"]
    fields = [key for key in previous_response.keys() if not key.startswith("_")]
    frozen = [field for field in fields if field not in mutable]
    return RepairDirective(
        previous_response=dict(previous_response),
        issues=issues,
        mutable_fields=mutable,
        frozen_fields=frozen,
    )


def frozen_field_regressions(previous_response: dict[str, Any], repaired_response: dict[str, Any], frozen_fields: list[str]) -> list[str]:
    return [
        field
        for field in frozen_fields
        if previous_response.get(field) != repaired_response.get(field)
    ]


def repair_prompt_payload(directive: RepairDirective) -> dict[str, Any]:
    return {
        "previous_response": directive.previous_response,
        "issues": [
            {
                "code": issue.code,
                "field": issue.field,
                "severity": issue.severity,
                "repair_strategy": issue.repair_strategy,
                "details": issue.details,
            }
            for issue in directive.issues
        ],
        "only_these_fields_may_change": directive.mutable_fields,
        "all_other_fields_must_remain_byte_for_byte_identical": directive.frozen_fields,
        "instruction": "Return the complete JSON object with only the authorized field changes.",
    }
