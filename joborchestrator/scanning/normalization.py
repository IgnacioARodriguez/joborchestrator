from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "li", "div", "section", "h1", "h2", "h3"}:
            self._parts.append(" ")

    def get_text(self) -> str:
        return clean_display_text(" ".join(self._parts))


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    parser = _HTMLTextExtractor()
    parser.feed(html)
    text = parser.get_text()
    return text or None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def clean_display_text(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value))
    return text.strip()


def normalize_job_identity(title: str | None, company: str | None, location: str | None) -> str:
    return "|".join(
        [
            normalize_text(title),
            normalize_text(company),
            normalize_text(location),
        ]
    )


def compute_content_hash(
    title: str | None,
    company: str | None,
    location: str | None,
    description: str | None,
    apply_url: str | None,
) -> str:
    normalized = "|".join(
        [
            normalize_text(title),
            normalize_text(company),
            normalize_text(location),
            normalize_text(description),
            normalize_text(apply_url),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None
