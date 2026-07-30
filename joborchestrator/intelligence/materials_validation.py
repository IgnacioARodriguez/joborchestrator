from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

IssueSeverity = Literal["hard", "soft"]
RepairStrategy = Literal[
    "derive",
    "inject_source",
    "remove_span",
    "regenerate_field",
    "fallback",
    "human_review",
]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    severity: IssueSeverity
    repair_strategy: RepairStrategy
    details: dict[str, Any]


ISSUE_CODES = {
    "MISSING_REQUIRED_FIELD",
    "INVALID_SCHEMA",
    "CV_TOO_SHORT",
    "ROLE_OMITTED",
    "ROLE_OVERCOMPRESSED",
    "MISSING_CANONICAL_ROLE_TECH",
    "UNSUPPORTED_ROLE_TECH",
    "KEYWORD_METADATA_MISMATCH",
    "FORBIDDEN_ALIAS",
    "UNSUPPORTED_YEARS_CLAIM",
    "UNSUPPORTED_GENERAL_CLAIM",
    "INTERNAL_LANGUAGE_LEAK",
    "OVERCONFIDENT_TONE",
    "LANGUAGE_MISMATCH",
    "AUTOFILL_SHAPE_INVALID",
}

_RISK_FLAG_BY_ISSUE_CODE = {
    "KEYWORD_METADATA_MISMATCH": "keywords_used_derived_from_cv_text",
    "FORBIDDEN_ALIAS": "unsupported_target_stack_terms_required_repair",
    "UNSUPPORTED_YEARS_CLAIM": "unsupported_experience_years_claim_required_repair",
    "UNSUPPORTED_ROLE_TECH": "role_technology_attribution_required_repair",
    "MISSING_CANONICAL_ROLE_TECH": "role_technology_evidence_required_repair",
    "ROLE_OMITTED": "cv_completeness_required_repair",
    "ROLE_OVERCOMPRESSED": "cv_completeness_required_repair",
    "CV_TOO_SHORT": "cv_completeness_required_repair",
    "INTERNAL_LANGUAGE_LEAK": "internal_review_language_required_repair",
    "OVERCONFIDENT_TONE": "tone_required_cautious_review",
    "LANGUAGE_MISMATCH": "output_language_required_repair",
    "AUTOFILL_SHAPE_INVALID": "autofill_shape_required_repair",
    "MISSING_REQUIRED_FIELD": "generation_required_human_review",
    "INVALID_SCHEMA": "generation_required_human_review",
    "UNSUPPORTED_GENERAL_CLAIM": "generation_required_human_review",
}


def derive_risk_flags_from_issues(issues: list[ValidationIssue]) -> list[str]:
    flags: list[str] = []
    for issue in issues:
        flag = _RISK_FLAG_BY_ISSUE_CODE.get(issue.code)
        if flag is None and issue.severity == "hard":
            flag = "generation_required_human_review"
        if flag and flag not in flags:
            flags.append(flag)
    return flags


def issues_to_messages(issues: list[ValidationIssue]) -> list[str]:
    return [issue_to_message(issue) for issue in issues]


def issues_to_dicts(issues: list[ValidationIssue]) -> list[dict[str, Any]]:
    return [asdict(issue) for issue in issues]


def issue_to_message(issue: ValidationIssue) -> str:
    detail = ", ".join(f"{key}={value}" for key, value in issue.details.items())
    return f"{issue.code} in {issue.field}: {detail}" if detail else f"{issue.code} in {issue.field}"


def validation_feedback_to_issues(feedback: str | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for part in _split_feedback(feedback):
        normalized = part.lower()
        if "keywords_used contains terms not present" in normalized:
            issues.append(_issue("KEYWORD_METADATA_MISMATCH", "keywords_used", "hard", "derive", part))
        elif "omitted base cv experience entries" in normalized:
            issues.append(_issue("ROLE_OMITTED", "ats_cv_text", "hard", "inject_source", part))
        elif "overcompressed for base cv experience roles" in normalized:
            issues.append(_issue("ROLE_OVERCOMPRESSED", "ats_cv_text", "hard", "inject_source", part))
        elif "overcompressed compared with base cv" in normalized or "too short" in normalized:
            issues.append(_issue("CV_TOO_SHORT", "ats_cv_text", "hard", "inject_source", part))
        elif "missing canonical role technologies" in normalized:
            issues.append(_issue("MISSING_CANONICAL_ROLE_TECH", "ats_cv_text", "hard", "inject_source", part))
        elif "unsupported role-specific technologies" in normalized:
            issues.append(_issue("UNSUPPORTED_ROLE_TECH", "ats_cv_text", "hard", "remove_span", part))
        elif "unsupported ranking avoid-overclaiming terms" in normalized:
            field = "ats_cv_text" if normalized.startswith("ats_cv_text") else "application_materials"
            issues.append(_issue("FORBIDDEN_ALIAS", field, "hard", "remove_span", part))
        elif "unsupported years-of-experience claims" in normalized:
            issues.append(_issue("UNSUPPORTED_YEARS_CLAIM", "application_materials", "hard", "remove_span", part))
        elif "internal review/evaluation language" in normalized or "internal/non-cv notes" in normalized:
            issues.append(_issue("INTERNAL_LANGUAGE_LEAK", "application_materials", "hard", "remove_span", part))
        elif "overconfident tone" in normalized:
            issues.append(_issue("OVERCONFIDENT_TONE", "application_materials", "soft", "regenerate_field", part))
        elif "language mismatch" in normalized:
            issues.append(_issue("LANGUAGE_MISMATCH", "application_materials", "hard", "regenerate_field", part))
        elif "autofill" in normalized and ("json" in normalized or "shape" in normalized):
            issues.append(_issue("AUTOFILL_SHAPE_INVALID", "autofill", "hard", "regenerate_field", part))
        elif "required" in normalized:
            field_match = re.match(r"([a-z_]+) is required", normalized)
            issues.append(
                ValidationIssue(
                    code="MISSING_REQUIRED_FIELD",
                    field=field_match.group(1) if field_match else "response",
                    severity="hard",
                    repair_strategy="regenerate_field",
                    details={"message": part},
                )
            )
        elif "must be an array" in normalized:
            issues.append(_issue("INVALID_SCHEMA", "response", "hard", "fallback", part))
        else:
            issues.append(_issue("UNSUPPORTED_GENERAL_CLAIM", "response", "hard", "human_review", part))
    return issues


def _issue(
    code: str,
    field: str,
    severity: IssueSeverity,
    repair_strategy: RepairStrategy,
    message: str,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        field=field,
        severity=severity,
        repair_strategy=repair_strategy,
        details={"message": message},
    )


def _split_feedback(feedback: str | None) -> list[str]:
    return [part.strip() for part in str(feedback or "").split("; ") if part.strip()]
