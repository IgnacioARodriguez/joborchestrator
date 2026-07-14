from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from joborchestrator.automation.answer_bank import map_answers as map_schema_answers


@dataclass(frozen=True)
class AdapterResult:
    ok: bool
    data: dict[str, Any]
    error: str | None = None


class ApplicationAdapter(Protocol):
    provider: str

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool: ...
    def extract_form_schema_html(self, html: str) -> dict[str, Any]: ...
    def map_answers(self, schema: dict[str, Any], profile: dict[str, Any], answer_bank: list[dict[str, Any]]) -> dict[str, Any]: ...
    def fill_fields_html(self, html: str, mapping: dict[str, Any], *, dry_run: bool = True) -> AdapterResult: ...
    def prepare_review(self, schema: dict[str, Any], mapping: dict[str, Any], fill: AdapterResult) -> dict[str, Any]: ...


class GenericAssistedAdapter:
    provider = "generic"

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        return True

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


class GreenhouseAdapter(GenericAssistedAdapter):
    provider = "greenhouse"

    def detect_html(self, html: str, job: dict[str, Any] | None = None) -> bool:
        url = str((job or {}).get("apply_url") or (job or {}).get("url") or "").lower()
        return "greenhouse.io" in url or "grnh.se" in url or "boards.greenhouse.io" in html.lower() or 'id="application_form"' in html

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


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[ApplicationAdapter] = [GreenhouseAdapter(), GenericAssistedAdapter()]

    def detect(self, html: str, job: dict[str, Any] | None = None) -> ApplicationAdapter:
        for adapter in self._adapters:
            if adapter.detect_html(html, job):
                return adapter
        return self._adapters[-1]


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=[\"']([^\"']+)[\"']", tag, re.I)
    return match.group(1) if match else None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip().rstrip("*").strip()
