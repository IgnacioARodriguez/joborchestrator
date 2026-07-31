from __future__ import annotations

import re
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
        elif issue.code == "FORBIDDEN_ALIAS":
            if not _repair_forbidden_aliases(repaired, issue):
                remaining.append(issue)
        else:
            remaining.append(issue)
    return repaired, remaining


_FORBIDDEN_ALIAS_REPLACEMENT = "some target stack items are not directly evidenced"


def _repair_forbidden_aliases(response: dict[str, Any], issue: ValidationIssue) -> bool:
    aliases = _aliases_from_issue(issue)
    if not aliases:
        return False
    fields = ["ats_cv_text"] if issue.field == "ats_cv_text" else ["recruiter_message", "cover_letter", "autofill_notes", "autofill"]
    changed = False
    for field in fields:
        if field not in response:
            continue
        repaired_value, field_changed = _replace_aliases(response[field], aliases)
        if field_changed:
            response[field] = repaired_value
            changed = True
    return changed


def _replace_aliases(value: Any, aliases: list[str]) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        repaired: dict[str, Any] = {}
        for key, item in value.items():
            repaired_item, item_changed = _replace_aliases(item, aliases)
            repaired[key] = repaired_item
            changed = changed or item_changed
        return repaired, changed
    if isinstance(value, list):
        changed = False
        repaired_items = []
        for item in value:
            repaired_item, item_changed = _replace_aliases(item, aliases)
            repaired_items.append(repaired_item)
            changed = changed or item_changed
        return repaired_items, changed
    if not isinstance(value, str):
        return value, False
    repaired = value
    for alias in aliases:
        repaired = re.sub(rf"(?i)(?<![\w.-]){re.escape(alias)}(?![\w.-])", _FORBIDDEN_ALIAS_REPLACEMENT, repaired)
    repaired = _collapse_repeated_repair_phrase(repaired)
    return repaired, repaired != value


def _collapse_repeated_repair_phrase(text: str) -> str:
    phrase = re.escape(_FORBIDDEN_ALIAS_REPLACEMENT)
    text = re.sub(rf"(?:{phrase})(?:\s*[,;/]\s*{phrase})+", _FORBIDDEN_ALIAS_REPLACEMENT, text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _aliases_from_issue(issue: ValidationIssue) -> list[str]:
    message = str(issue.details.get("message") or "")
    if ":" not in message:
        return []
    tail = message.split(":", 1)[1].split(". ", 1)[0]
    aliases: list[str] = []
    for parenthetical in re.findall(r"\(([^)]*)\)", tail):
        aliases.extend(_split_alias_items(parenthetical))
    tail_without_parentheticals = re.sub(r"\([^)]*\)", "", tail)
    aliases.extend(_split_alias_items(tail_without_parentheticals))
    return _dedupe_aliases(alias for alias in aliases if alias.lower() not in {"and", "or"})


def _split_alias_items(text: str) -> list[str]:
    return [item.strip(" .;:\n\t") for item in re.split(r",|/|\band\b|\bor\b", text, flags=re.IGNORECASE) if item.strip(" .;:\n\t")]


def _dedupe_aliases(items: Any) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = str(item).casefold()
        if key and key not in seen:
            seen.add(key)
            deduped.append(str(item))
    return deduped


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
