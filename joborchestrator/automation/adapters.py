from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol, TYPE_CHECKING

from joborchestrator.automation.answer_bank import classify_field, map_answers as map_schema_answers

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    can_open_application: bool
    can_follow_apply_redirects: bool
    can_detect_fields: bool
    can_fill_text_fields: bool
    can_fill_selects: bool
    can_fill_radios: bool
    can_fill_checkboxes: bool
    can_upload_resume: bool
    can_prepare_custom_answers: bool
    can_handle_multistep: bool
    can_resume_browser_session: bool
    requires_login: bool
    requires_final_review: bool
    can_observe_submission: bool
    can_submit: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdapterResult:
    ok: bool
    data: dict[str, Any]
    error: str | None = None


class ApplicationAdapter(Protocol):
    provider: str

    def capabilities(self) -> ProviderCapabilities: ...
    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool: ...
    async def detect_page(self, page: "Page", job: dict[str, Any] | None = None) -> bool: ...
    async def extract_form_schema_page(self, page: "Page") -> dict[str, Any]: ...
    def extract_form_schema_html(self, html: str) -> dict[str, Any]: ...
    def map_answers(self, schema: dict[str, Any], profile: dict[str, Any], answer_bank: list[dict[str, Any]]) -> dict[str, Any]: ...
    def fill_fields_html(self, html: str, mapping: dict[str, Any], *, dry_run: bool = True) -> AdapterResult: ...
    def prepare_review(self, schema: dict[str, Any], mapping: dict[str, Any], fill: AdapterResult) -> dict[str, Any]: ...


class GenericAssistedAdapter:
    provider = "generic"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.provider,
            can_open_application=True,
            can_follow_apply_redirects=True,
            can_detect_fields=False,
            can_fill_text_fields=False,
            can_fill_selects=False,
            can_fill_radios=False,
            can_fill_checkboxes=False,
            can_upload_resume=False,
            can_prepare_custom_answers=True,
            can_handle_multistep=False,
            can_resume_browser_session=False,
            requires_login=False,
            requires_final_review=True,
            can_observe_submission=False,
            can_submit=False,
        )

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        return True

    async def detect_page(self, page: "Page", job: dict[str, Any] | None = None) -> bool:
        return self.detect_html(await page.content(), job)

    async def extract_form_schema_page(self, page: "Page") -> dict[str, Any]:
        return self.extract_form_schema_html(await page.content())

    def extract_form_schema_html(self, html: str) -> dict[str, Any]:
        return {"provider": self.provider, "fields": []}

    def map_answers(self, schema: dict[str, Any], profile: dict[str, Any], answer_bank: list[dict[str, Any]]) -> dict[str, Any]:
        return map_schema_answers(schema, profile, answer_bank)

    def fill_fields_html(self, html: str, mapping: dict[str, Any], *, dry_run: bool = True) -> AdapterResult:
        return AdapterResult(True, {"dry_run": dry_run, "fields_autofilled": 0, "html_changed": False})

    def prepare_review(self, schema: dict[str, Any], mapping: dict[str, Any], fill: AdapterResult) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "fields_detected": len(schema.get("fields") or []),
            "fields_autofilled": fill.data.get("fields_autofilled", 0),
            "unknown_fields": mapping.get("unknown_fields") or [],
            "requires_review": True,
        }


class BrowserFormAdapter(GenericAssistedAdapter):
    provider = "generic_form"
    form_selector = "form"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.provider,
            can_open_application=True,
            can_follow_apply_redirects=True,
            can_detect_fields=True,
            can_fill_text_fields=True,
            can_fill_selects=True,
            can_fill_radios=True,
            can_fill_checkboxes=True,
            can_upload_resume=True,
            can_prepare_custom_answers=True,
            can_handle_multistep=False,
            can_resume_browser_session=True,
            requires_login=False,
            requires_final_review=True,
            can_observe_submission=False,
            can_submit=False,
        )

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        normalized = html.lower()
        return "<form" in normalized and any(marker in normalized for marker in ("<input", "<textarea", "<select"))

    async def detect_page(self, page: "Page", job: dict[str, Any] | None = None) -> bool:
        return await page.locator(self.form_selector).count() > 0

    async def extract_form_schema_page(self, page: "Page") -> dict[str, Any]:
        candidate = await _extract_best_form_candidate(page, self.form_selector)
        return {
            "provider": self.provider,
            "fields": candidate["fields"],
            "form_candidates": candidate["form_candidates"],
            "selected_form_index": candidate["selected_form_index"],
        }

    def extract_form_schema_html(self, html: str) -> dict[str, Any]:
        fields: list[dict[str, Any]] = []
        for match in re.finditer(r"<label[^>]*for=[\"'](?P<for>[^\"']+)[\"'][^>]*>(?P<label>.*?)</label>", html, re.I | re.S):
            field_id = match.group("for")
            label = _clean_html(match.group("label"))
            input_match = re.search(
                rf"<(?P<tag>input|textarea|select)\b[^>]*(?:id|name)=[\"']{re.escape(field_id)}[\"'][^>]*>",
                html,
                re.I | re.S,
            )
            if not input_match:
                continue
            raw = input_match.group(0)
            field_type = "textarea" if input_match.group("tag").lower() == "textarea" else _attr(raw, "type") or input_match.group("tag").lower()
            fields.append(
                {
                    "id": field_id,
                    "name": _attr(raw, "name") or field_id,
                    "label": label,
                    "type": field_type,
                    "required": "required" in raw.lower() or "*" in label,
                }
            )
        if re.search(r"<input[^>]+type=[\"']file[\"']", html, re.I):
            fields.append({"id": "resume", "name": "resume", "label": "Resume", "type": "file", "required": True})
        return {"provider": self.provider, "fields": fields}

    def fill_fields_html(self, html: str, mapping: dict[str, Any], *, dry_run: bool = True) -> AdapterResult:
        safe_answers = [
            answer for answer in mapping.get("answers", [])
            if answer.get("value") and not answer.get("requires_confirmation")
        ]
        return AdapterResult(
            True,
            {
                "dry_run": dry_run,
                "fields_autofilled": len(safe_answers),
                "html_changed": False,
                "filled_fields": [answer["field_name"] for answer in safe_answers],
            },
        )


class GreenhouseAdapter(BrowserFormAdapter):
    provider = "greenhouse"
    form_selector = "#application_form, form"

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        url = str((job or {}).get("apply_url") or (job or {}).get("url") or "").lower()
        return "greenhouse.io" in url or "grnh.se" in url or "boards.greenhouse.io" in html.lower() or 'id="application_form"' in html

    async def detect_page(self, page: "Page", job: dict[str, Any] | None = None) -> bool:
        url = page.url.lower()
        if "greenhouse.io" in url or "grnh.se" in url:
            return True
        return await page.locator("#application_form, form[action*='greenhouse' i]").count() > 0


class LeverAdapter(BrowserFormAdapter):
    provider = "lever"

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        url = str((job or {}).get("apply_url") or (job or {}).get("url") or "").lower()
        normalized_html = html.lower()
        return (
            "jobs.lever.co" in url
            or "lever.co" in url
            or "jobs.lever.co" in normalized_html
            or 'data-qa="btn-apply"' in normalized_html
            or "lever-application-form" in normalized_html
        )

    async def detect_page(self, page: "Page", job: dict[str, Any] | None = None) -> bool:
        url = page.url.lower()
        if "jobs.lever.co" in url or "lever.co" in url:
            return True
        return await page.locator('[data-qa="btn-apply"], .lever-application-form').count() > 0

    async def extract_form_schema_page(self, page: "Page") -> dict[str, Any]:
        if await page.locator("form").count() == 0:
            apply_button = page.locator('[data-qa="btn-apply"], a[href$="/apply"], a:has-text("Apply")').first
            try:
                if await apply_button.count() > 0 and await apply_button.is_visible(timeout=1000):
                    await apply_button.click(timeout=3000)
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
        candidate = await _extract_best_form_candidate(page, "form")
        return {
            "provider": self.provider,
            "fields": candidate["fields"],
            "form_candidates": candidate["form_candidates"],
            "selected_form_index": candidate["selected_form_index"],
        }


class GenericFormAdapter(BrowserFormAdapter):
    provider = "generic_form"

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        normalized = html.lower()
        return super().detect_html(html, job) or bool(
            re.search(r"\b(apply|apply now|i'?m interested|start application|submit application|aplicar|solicitar)\b", normalized)
        )

    async def extract_form_schema_page(self, page: "Page") -> dict[str, Any]:
        schema = await super().extract_form_schema_page(page)
        if not schema.get("fields"):
            cta = page.locator("a, button").filter(
                has_text=re.compile(
                    r"\b(apply|apply now|i'?m interested|start application|aplicar|solicitar)\b",
                    re.IGNORECASE,
                )
            ).first
            try:
                if await cta.count() > 0 and await cta.is_visible(timeout=1000):
                    await cta.click(timeout=3000)
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                    await page.wait_for_timeout(1000)
            except Exception:
                pass
            schema = await super().extract_form_schema_page(page)
        return schema


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[ApplicationAdapter] = [GreenhouseAdapter(), LeverAdapter(), GenericFormAdapter(), GenericAssistedAdapter()]
        self._declared: dict[str, ProviderCapabilities] = {
            adapter.provider: adapter.capabilities() for adapter in self._adapters
        }
        self._declared.update(
            {
                "ashby": _recognition_only_capabilities("ashby"),
                "workday": _recognition_only_capabilities("workday", requires_login=True),
                "linkedin_easy_apply": ProviderCapabilities(
                    provider="linkedin_easy_apply",
                    can_open_application=True,
                    can_follow_apply_redirects=False,
                    can_detect_fields=False,
                    can_fill_text_fields=False,
                    can_fill_selects=False,
                    can_fill_radios=False,
                    can_fill_checkboxes=False,
                    can_upload_resume=False,
                    can_prepare_custom_answers=False,
                    can_handle_multistep=False,
                    can_resume_browser_session=False,
                    requires_login=True,
                    requires_final_review=True,
                    can_observe_submission=False,
                    can_submit=False,
                ),
            }
        )

    def detect(self, html: str, job: dict[str, Any] | None = None) -> ApplicationAdapter:
        for adapter in self._adapters:
            if adapter.detect_html(html, job):
                return adapter
        return self._adapters[-1]

    def get(self, provider: str) -> ApplicationAdapter:
        for adapter in self._adapters:
            if adapter.provider == provider:
                return adapter
        raise KeyError(f"Unknown executable application adapter: {provider}")

    def capabilities(self, provider: str | None = None) -> list[ProviderCapabilities] | ProviderCapabilities:
        if provider:
            return self._declared.get(provider, self._declared["generic"])
        return [self._declared[key] for key in sorted(self._declared)]


def _recognition_only_capabilities(provider: str, *, requires_login: bool = False) -> ProviderCapabilities:
    return ProviderCapabilities(
        provider=provider,
        can_open_application=True,
        can_follow_apply_redirects=True,
        can_detect_fields=False,
        can_fill_text_fields=False,
        can_fill_selects=False,
        can_fill_radios=False,
        can_fill_checkboxes=False,
        can_upload_resume=False,
        can_prepare_custom_answers=False,
        can_handle_multistep=False,
        can_resume_browser_session=False,
        requires_login=requires_login,
        requires_final_review=True,
        can_observe_submission=False,
        can_submit=False,
    )


async def _extract_best_form_candidate(page: "Page", selector: str) -> dict[str, Any]:
    forms = page.locator(selector)
    count = await forms.count()
    candidates: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for index in range(count):
        form = forms.nth(index)
        try:
            raw_fields = await form.evaluate(_APPLICATION_FORM_DISCOVERY_JS)
            metadata = await form.evaluate(_FORM_METADATA_JS)
        except Exception:
            continue
        normalized_fields = [_normalize_dom_field(field) for field in raw_fields]
        score = _score_form_candidate(normalized_fields, metadata)
        candidate = {
            "index": index,
            "score": score,
            "fields": normalized_fields,
            "field_count": len(normalized_fields),
            "submit_controls": int(metadata.get("submit_controls") or 0),
            "text": str(metadata.get("text") or "")[:160],
        }
        candidates.append({key: value for key, value in candidate.items() if key != "fields"})
        if best is None or score > int(best["score"]):
            best = candidate
    if best is None:
        return {"fields": [], "form_candidates": [], "selected_form_index": None}
    return {
        "fields": best["fields"],
        "form_candidates": candidates,
        "selected_form_index": best["index"],
    }


def _score_form_candidate(fields: list[dict[str, Any]], metadata: dict[str, Any]) -> int:
    if not fields:
        return 0
    score = len(fields)
    score += min(int(metadata.get("submit_controls") or 0), 2) * 3
    labels = " ".join(str(field.get("label") or field.get("name") or "") for field in fields).lower()
    names = " ".join(str(field.get("name") or "") for field in fields).lower()
    field_text = f"{labels} {names}"
    for marker in ("resume", "cv", "curriculum"):
        if marker in field_text:
            score += 6
            break
    for marker in ("email", "phone", "linkedin", "portfolio", "cover letter"):
        if marker in field_text:
            score += 2
    if any(str(field.get("type") or "") == "file" for field in fields):
        score += 8
    if int(metadata.get("password_fields") or 0):
        score -= 8
    text = str(metadata.get("text") or "").lower()
    if any(marker in text for marker in ("newsletter", "search jobs", "job alert", "sign up", "log in", "login")):
        score -= 4
    return score


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=[\"']([^\"']+)[\"']", tag, re.I)
    return match.group(1) if match else None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip().rstrip("*").strip()


def _normalize_dom_field(field: dict[str, Any]) -> dict[str, Any]:
    label = str(field.get("label") or field.get("name") or field.get("id") or "").strip()
    raw_type = str(field.get("type") or "text").lower()
    field_type = {
        "text": "text",
        "email": "email",
        "tel": "tel",
        "url": "url",
        "textarea": "textarea",
        "select-one": "select",
        "select-multiple": "select",
        "radio": "radio",
        "checkbox": "checkbox",
        "file": "file",
    }.get(raw_type, raw_type)
    canonical, classification = classify_field(label, field_type)
    confidence = {
        "label_for": 0.98,
        "wrapping_label": 0.95,
        "aria_label": 0.9,
        "aria_labelledby": 0.88,
        "question_container": 0.86,
        "nearby_text": 0.72,
        "name": 0.62,
        "id": 0.58,
        "placeholder": 0.45,
    }.get(str(field.get("locator_strategy") or ""), 0.5)
    return {
        "id": str(field.get("id") or field.get("name") or label),
        "key": canonical or _safe_key(label or str(field.get("name") or field.get("id") or "field")),
        "name": str(field.get("name") or field.get("id") or label),
        "label": label,
        "type": field_type,
        "required": bool(field.get("required")),
        "sensitive": classification == "sensitive",
        "confidence": confidence,
        "locator_strategy": str(field.get("locator_strategy") or "unknown"),
        "in_shadow_root": bool(field.get("in_shadow_root")),
        "options": field.get("options") or [],
    }


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "field"


_APPLICATION_FORM_DISCOVERY_JS = """
form => {
  const TECHNICAL_RE = /(^_|^hp_|csrf|token|utf8|captcha|g-recaptcha|h-captcha|honeypot|bot-field|website_url)/i;
  function collectDeep(root, selector) {
    const found = [];
    const visit = node => {
      if (!node) return;
      if (node.querySelectorAll) found.push(...Array.from(node.querySelectorAll(selector)));
      const descendants = node.querySelectorAll ? Array.from(node.querySelectorAll('*')) : [];
      for (const descendant of descendants) {
        if (descendant.shadowRoot) visit(descendant.shadowRoot);
      }
    };
    visit(root);
    return found;
  }
  function queryDeepFirst(root, selector) {
    return collectDeep(root, selector)[0] || null;
  }
  function inShadowRoot(element) {
    return Boolean(element.getRootNode && window.ShadowRoot && element.getRootNode() instanceof ShadowRoot);
  }
  const controls = collectDeep(form, 'input, textarea, select');
  const ariaControls = collectDeep(form, '[role="combobox"], [role="listbox"], [role="radiogroup"], [role="radio"], [role="checkbox"]');
  const fileWidgets = collectDeep(form, 'button, a, [role="button"], [data-testid], [aria-label], .dropzone, [class*="dropzone"], [class*="upload"]');
  const controlledAriaIds = new Set(
    ariaControls
      .flatMap(element => String(element.getAttribute('aria-controls') || element.getAttribute('aria-owns') || '').split(/\\s+/))
      .filter(Boolean)
  );
  const byNameRadio = new Map();
  const fields = [];
  const seenControlKeys = new Set();

  function text(value) {
    return String(value || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '').trim();
  }

  function isHidden(element) {
    const inputType = String(element.getAttribute('type') || '').toLowerCase();
    const style = window.getComputedStyle(element);
    return inputType === 'hidden'
      || element.hidden
      || !element.getClientRects().length
      || style.display === 'none'
      || style.visibility === 'hidden'
      || element.getAttribute('aria-hidden') === 'true';
  }

  function labelFor(element) {
    function questionText() {
      const question = element.closest('.application-question, .custom-question, .question, .posting-field, .field-group');
      if (!question) return '';
      const clone = question.cloneNode(true);
      collectDeep(clone, 'input, textarea, select, option, script, style, label').forEach(node => node.remove());
      return text(clone.innerText || clone.textContent);
    }

    const id = element.id;
    if (id) {
      const explicit = queryDeepFirst(form, `label[for="${CSS.escape(id)}"]`) || document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (explicit) return { label: text(explicit.innerText || explicit.textContent), strategy: 'label_for' };
    }
    const wrapping = element.closest('label');
    if (wrapping) return { label: text(wrapping.innerText || wrapping.textContent), strategy: 'wrapping_label' };
    const aria = element.getAttribute('aria-label');
    if (aria) return { label: text(aria), strategy: 'aria_label' };
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) {
      const label = labelledBy.split(/\\s+/).map(part => document.getElementById(part)?.innerText || document.getElementById(part)?.textContent || queryDeepFirst(form, `#${CSS.escape(part)}`)?.innerText || queryDeepFirst(form, `#${CSS.escape(part)}`)?.textContent || '').join(' ');
      if (text(label)) return { label: text(label), strategy: 'aria_labelledby' };
    }
    const placeholder = text(element.getAttribute('placeholder'));
    if (placeholder) return { label: placeholder, strategy: 'placeholder' };
    const container = element.closest('.field, .field-group, .application-field, .question, div, li');
    if (container) {
      const clone = container.cloneNode(true);
      collectDeep(clone, 'input, textarea, select, option, script, style').forEach(node => node.remove());
      const nearby = text(clone.innerText || clone.textContent);
      if (nearby) return { label: nearby, strategy: 'nearby_text' };
    }
    const question = questionText();
    if (question) return { label: question, strategy: 'question_container' };
    const name = element.getAttribute('name');
    if (name) return { label: text(name.replace(/[_.-]+/g, ' ')), strategy: 'name' };
    if (id) return { label: text(id.replace(/[_.-]+/g, ' ')), strategy: 'id' };
    return { label: '', strategy: 'unknown' };
  }

  function baseField(element) {
    const labelled = labelFor(element);
    const tag = element.tagName.toLowerCase();
    const type = tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : String(element.getAttribute('type') || 'text').toLowerCase();
    return {
      id: element.id || element.getAttribute('name') || labelled.label,
      name: element.getAttribute('name') || element.id || labelled.label,
      label: labelled.label,
      type,
      required: element.required || element.getAttribute('aria-required') === 'true' || /[\\*✱]/.test(element.closest('label, .application-question, .custom-question, .posting-field')?.textContent || ''),
      locator_strategy: labelled.strategy,
      in_shadow_root: inShadowRoot(element),
      options: [],
    };
  }

  function elementKey(element, fallbackLabel) {
    return element.getAttribute('name') || element.id || element.getAttribute('aria-label') || element.getAttribute('data-testid') || fallbackLabel || '';
  }

  function optionLabel(element) {
    return text(element.innerText || element.textContent || element.getAttribute('aria-label') || element.getAttribute('data-value') || element.getAttribute('value'));
  }

  function ariaOptions(element) {
    const owns = element.getAttribute('aria-controls') || element.getAttribute('aria-owns') || '';
    const containers = [element];
    for (const part of owns.split(/\\s+/).filter(Boolean)) {
      const owned = document.getElementById(part) || queryDeepFirst(form, `#${CSS.escape(part)}`);
      if (owned) containers.push(owned);
    }
    const options = [];
    for (const container of containers) {
      for (const option of collectDeep(container, '[role="option"], [role="radio"]')) {
        const label = optionLabel(option);
        if (label) options.push({ value: option.getAttribute('data-value') || option.getAttribute('value') || label, label });
      }
    }
    return options;
  }

  function ariaField(element) {
    const role = String(element.getAttribute('role') || '').toLowerCase();
    const labelled = labelFor(element);
    const label = labelled.label || text(element.getAttribute('aria-label'));
    const key = elementKey(element, label);
    if (!key || isHidden(element)) return null;
    if (role === 'combobox' || role === 'listbox') {
      return {
        id: key,
        name: key,
        label,
        type: 'select',
        required: element.getAttribute('aria-required') === 'true' || /[\\*âœ±]/.test(element.closest('label, .application-question, .custom-question, .posting-field')?.textContent || ''),
        locator_strategy: 'aria_role',
        in_shadow_root: inShadowRoot(element),
        options: ariaOptions(element),
      };
    }
    if (role === 'radiogroup') {
      return {
        id: key,
        name: key,
        label,
        type: 'radio',
        required: element.getAttribute('aria-required') === 'true' || /[\\*âœ±]/.test(element.closest('label, .application-question, .custom-question, .posting-field')?.textContent || ''),
        locator_strategy: 'aria_role',
        in_shadow_root: inShadowRoot(element),
        options: ariaOptions(element),
      };
    }
    if (role === 'checkbox') {
      return {
        id: key,
        name: key,
        label,
        type: 'checkbox',
        required: element.getAttribute('aria-required') === 'true' || /[\\*âœ±]/.test(element.closest('label, .application-question, .custom-question, .posting-field')?.textContent || ''),
        locator_strategy: 'aria_role',
        in_shadow_root: inShadowRoot(element),
        options: [{ value: element.getAttribute('data-value') || 'checked', label }],
      };
    }
    return null;
  }

  function fileWidgetField(element) {
    const labelled = labelFor(element);
    const label = labelled.label || text(element.innerText || element.textContent || element.getAttribute('aria-label') || element.getAttribute('title'));
    if (!/(resume|cv|curriculum|attach|upload|file|document|adjuntar|subir|curr)/i.test(label)) return null;
    if (/(submit|send|apply|enviar|solicitar|finalizar)/i.test(label)) return null;
    const key = elementKey(element, label);
    if (!key || isHidden(element)) return null;
    return {
      id: key,
      name: key,
      label,
      type: 'file',
      required: element.getAttribute('aria-required') === 'true' || /[\\*âœ±]/.test(element.closest('label, .application-question, .custom-question, .posting-field')?.textContent || ''),
      locator_strategy: 'file_widget',
      in_shadow_root: inShadowRoot(element),
      options: [],
    };
  }

  for (const element of controls) {
    const name = element.getAttribute('name') || '';
    const id = element.id || '';
    if (element.disabled || isHidden(element) || TECHNICAL_RE.test(name) || TECHNICAL_RE.test(id)) continue;
    const field = baseField(element);
    if (!field.label && !field.name) continue;
    seenControlKeys.add(elementKey(element, field.label));
    if (field.type === 'radio') {
      const groupKey = name || id || field.label;
      const legendRoot = element.closest('fieldset');
      const legend = text(queryDeepFirst(legendRoot, 'legend')?.innerText || queryDeepFirst(legendRoot, 'legend')?.textContent);
      const question = labelFor(element.closest('.application-question, .custom-question, .question') || element).label;
      if (!byNameRadio.has(groupKey)) {
        byNameRadio.set(groupKey, { ...field, id: groupKey, name: groupKey, label: legend || question || field.label, options: [] });
      }
      const optionLabel = labelFor(element).label || element.value;
      byNameRadio.get(groupKey).options.push({ value: element.value || optionLabel, label: optionLabel });
      continue;
    }
    if (field.type === 'checkbox') {
      field.options = [{ value: element.value || 'checked', label: field.label }];
    }
    if (field.type === 'select') {
      field.options = Array.from(element.options)
        .filter(option => option.value || text(option.innerText || option.textContent))
        .map(option => ({ value: option.value, label: text(option.innerText || option.textContent) }));
    }
    fields.push(field);
  }
  fields.push(...Array.from(byNameRadio.values()));
  for (const element of ariaControls) {
    const role = String(element.getAttribute('role') || '').toLowerCase();
    if (element.matches('input, textarea, select') || element.disabled || isHidden(element)) continue;
    if (role === 'listbox' && element.id && controlledAriaIds.has(element.id)) continue;
    if (role === 'radio' && element.closest('[role="radiogroup"]')) continue;
    const field = ariaField(element);
    if (!field || seenControlKeys.has(field.name)) continue;
    if ((field.type === 'select' || field.type === 'radio') && !field.options.length) continue;
    fields.push(field);
    seenControlKeys.add(field.name);
  }
  if (!fields.some(field => field.type === 'file')) {
    for (const element of fileWidgets) {
      if (element.matches('input, textarea, select') || element.disabled || isHidden(element)) continue;
      const field = fileWidgetField(element);
      if (!field || seenControlKeys.has(field.name)) continue;
      fields.push(field);
      seenControlKeys.add(field.name);
      break;
    }
  }
  return fields;
}
"""

_FORM_METADATA_JS = """
form => {
  function text(value) {
    return String(value || '').replace(/\\s+/g, ' ').trim();
  }
  const controls = Array.from(form.querySelectorAll('button, input[type="submit"], input[type="button"]'));
  const submitControls = controls.filter(element => {
    const label = text(element.innerText || element.textContent || element.getAttribute('value') || element.getAttribute('aria-label') || element.getAttribute('type'));
    return /submit|send|apply|enviar|solicitar|finalizar/i.test(label);
  }).length;
  return {
    text: text(form.innerText || form.textContent).slice(0, 500),
    submit_controls: submitControls,
    password_fields: form.querySelectorAll('input[type="password"]').length,
  };
}
"""

_GREENHOUSE_FORM_DISCOVERY_JS = _APPLICATION_FORM_DISCOVERY_JS
