from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldValidationIssue:
    field_name: str
    issue_type: str
    message: str
    surface_id: str | None = None
    action_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    status: str
    issues: list[FieldValidationIssue] = field(default_factory=list)
    checked_postconditions: int = 0
    satisfied_postconditions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_postconditions": self.checked_postconditions,
            "satisfied_postconditions": self.satisfied_postconditions,
            "summary": {
                "issues": len(self.issues),
                "checked_postconditions": self.checked_postconditions,
                "satisfied_postconditions": self.satisfied_postconditions,
            },
        }


async def validate_application_surface(surface: Any, action_plan: dict[str, Any]) -> ValidationReport:
    postconditions = list(action_plan.get("expected_postconditions") or [])
    scoped_field_names = {
        str(postcondition.get("field_name") or "").strip()
        for postcondition in postconditions
        if str(postcondition.get("field_name") or "").strip()
    }
    browser_issues = await _detect_browser_validation_issues(surface, scoped_field_names)
    postcondition_issues: list[FieldValidationIssue] = []
    satisfied = 0
    for postcondition in postconditions:
        result = await _check_postcondition(surface, postcondition)
        if result is None:
            satisfied += 1
        else:
            postcondition_issues.append(result)
    issues = browser_issues + postcondition_issues
    return ValidationReport(
        status="validation_clean" if not issues else "validation_failed",
        issues=issues,
        checked_postconditions=len(postconditions),
        satisfied_postconditions=satisfied,
    )


async def _detect_browser_validation_issues(surface: Any, scoped_field_names: set[str]) -> list[FieldValidationIssue]:
    raw_issues = await surface.evaluate(
        """({ scopedFieldNames }) => {
          const scoped = new Set(scopedFieldNames || []);
          function text(value) {
            return String(value || '').replace(/\\s+/g, ' ').trim();
          }
          function visible(element) {
            const style = window.getComputedStyle(element);
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && !element.hidden
              && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
          }
          function fieldName(element) {
            return element.getAttribute('name') || element.id || element.getAttribute('aria-label') || element.getAttribute('placeholder') || '';
          }
          function scopedIn(element) {
            if (!scoped.size) return true;
            const name = fieldName(element);
            return Boolean(name && scoped.has(name));
          }
          const issues = [];
          const invalidControls = Array.from(document.querySelectorAll('input, textarea, select'))
            .filter(element => {
              const type = String(element.getAttribute('type') || '').toLowerCase();
              return type !== 'file'
                && !element.disabled
                && visible(element)
                && scopedIn(element)
                && (element.matches(':invalid') || element.getAttribute('aria-invalid') === 'true');
            });
          for (const element of invalidControls) {
            issues.push({
              field_name: fieldName(element),
              issue_type: element.getAttribute('aria-invalid') === 'true' ? 'aria_invalid' : 'browser_invalid',
              message: text(element.validationMessage || element.getAttribute('aria-errormessage') || element.getAttribute('title') || 'Invalid field'),
            });
          }
          const errorNodes = Array.from(document.querySelectorAll(
            '[role="alert"], .error, .errors, .field-error, .invalid-feedback, [class*="error"], [data-testid*="error"]'
          )).filter(visible);
          for (const node of errorNodes) {
            const message = text(node.innerText || node.textContent);
            if (message) {
              issues.push({ field_name: '', issue_type: 'visible_error', message: message.slice(0, 240) });
            }
          }
          return issues;
        }""",
        {"scopedFieldNames": sorted(scoped_field_names)},
    )
    issues: list[FieldValidationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_issues:
        field_name = str(item.get("field_name") or "")
        issue_type = str(item.get("issue_type") or "validation_error")
        message = str(item.get("message") or "Validation error")
        key = (field_name, issue_type, message)
        if key in seen:
            continue
        seen.add(key)
        issues.append(FieldValidationIssue(field_name=field_name, issue_type=issue_type, message=message))
    return issues


async def _check_postcondition(surface: Any, postcondition: dict[str, Any]) -> FieldValidationIssue | None:
    field_name = str(postcondition.get("field_name") or "").strip()
    action_type = str(postcondition.get("action_type") or "")
    if not field_name or action_type in {"upload_file"}:
        return None
    result = await surface.evaluate(
        """({ fieldName, actionType }) => {
          const byName = `[name="${CSS.escape(fieldName)}"]`;
          const byId = `#${CSS.escape(fieldName)}`;
          const element = document.querySelector(byName) || document.querySelector(byId);
          if (!element) return { ok: false, issue_type: 'control_missing', message: 'Control could not be found after actions.' };
          if (element.getAttribute('data-joborchestrator-dry-run') === 'filled') return { ok: true };
          const tag = element.tagName.toLowerCase();
          const type = String(element.getAttribute('type') || '').toLowerCase();
          if (actionType === 'check') {
            return { ok: Boolean(element.checked), issue_type: 'postcondition_failed', message: 'Checkbox did not remain checked.' };
          }
          if (actionType === 'choose_radio') {
            const checked = document.querySelector(`[name="${CSS.escape(fieldName)}"]:checked`);
            return { ok: Boolean(checked), issue_type: 'postcondition_failed', message: 'Radio selection was not retained.' };
          }
          if (tag === 'select') {
            return { ok: Boolean(element.value), issue_type: 'postcondition_failed', message: 'Select value was not retained.' };
          }
          if (type === 'file') return { ok: true };
          return { ok: Boolean(String(element.value || '').trim()), issue_type: 'postcondition_failed', message: 'Field value was not retained.' };
        }""",
        {"fieldName": field_name, "actionType": action_type},
    )
    if result.get("ok"):
        return None
    return FieldValidationIssue(
        field_name=field_name,
        issue_type=str(result.get("issue_type") or "postcondition_failed"),
        message=str(result.get("message") or "Postcondition failed."),
        surface_id=postcondition.get("surface_id"),
        action_type=action_type,
    )
