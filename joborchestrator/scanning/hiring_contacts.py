from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from joborchestrator.scanning.models import HiringContact
from joborchestrator.scanning.normalization import clean_display_text

LINKEDIN_HIRING_CONTACT_SOURCE = "linkedin_hiring_team"
LEGACY_RECRUITER_SOURCE = "legacy_recruiter_fields"

HIRING_TEAM_HEADINGS = (
    "Meet the hiring team",
    "Conoce al equipo de contratación",
    "Conoce al equipo de contrataciÃ³n",
)

IGNORED_CONTACT_TEXTS = {
    "view profile",
    "ver perfil",
    "message",
    "enviar mensaje",
    "open linkedin",
    "linkedin",
}


@dataclass(slots=True)
class HiringContactsExtractionResult:
    status: str
    contacts: list[HiringContact]


def normalize_linkedin_profile_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(str(url).strip())
    if not parsed.netloc and parsed.path.startswith("/"):
        parsed = urlsplit(f"https://www.linkedin.com{parsed.path}")
    if parsed.netloc and "linkedin.com" not in parsed.netloc.lower():
        return None
    if not re.search(r"(^|/)+in/[^/]+", parsed.path):
        return None
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") + "/"
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "www.linkedin.com", path, "", ""))


def deduplicate_hiring_contacts(contacts: list[HiringContact]) -> list[HiringContact]:
    seen: set[str] = set()
    output: list[HiringContact] = []
    for contact in contacts:
        normalized = normalize_linkedin_profile_url(contact.profile_url)
        if not normalized or normalized in seen or not contact.name:
            continue
        seen.add(normalized)
        output.append(
            HiringContact(
                id=contact.id,
                name=clean_contact_text(contact.name),
                profile_url=normalized,
                headline=clean_contact_text(contact.headline),
                role=clean_contact_text(contact.role),
                is_primary=False,
                source=contact.source or LINKEDIN_HIRING_CONTACT_SOURCE,
            )
        )
    for index, contact in enumerate(output):
        contact.is_primary = index == 0
    return output


def hiring_contacts_to_json(contacts: list[HiringContact]) -> str:
    return json.dumps([asdict(contact) for contact in contacts], ensure_ascii=False)


def parse_hiring_contacts_value(value: Any) -> list[HiringContact]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        try:
            items = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return []
    contacts: list[HiringContact] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = clean_contact_text(item.get("name"))
        profile_url = normalize_linkedin_profile_url(item.get("profile_url") or item.get("linkedin_url"))
        if not name or not profile_url:
            continue
        contacts.append(
            HiringContact(
                id=str(item["id"]) if item.get("id") is not None else None,
                name=name,
                profile_url=profile_url,
                headline=clean_contact_text(item.get("headline")),
                role=clean_contact_text(item.get("role")),
                is_primary=bool(item.get("is_primary")),
                source=clean_contact_text(item.get("source")) or LINKEDIN_HIRING_CONTACT_SOURCE,
            )
        )
    return deduplicate_hiring_contacts(contacts)


def primary_contact(contacts: list[HiringContact]) -> HiringContact | None:
    if not contacts:
        return None
    return next((contact for contact in contacts if contact.is_primary), contacts[0])


def clean_contact_text(value: Any) -> str | None:
    text = clean_display_text(value)
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = [line for line in lines if line.lower() not in IGNORED_CONTACT_TEXTS]
    return useful[0] if useful else None


def extract_contact_name(text: str | None, fallback_url: str | None = None) -> str | None:
    candidate = clean_contact_text(text)
    if candidate and len(candidate) <= 120:
        return candidate
    if fallback_url:
        slug = urlsplit(fallback_url).path.strip("/").split("/")[-1]
        if slug:
            return clean_display_text(slug.replace("-", " ").replace("_", " ")).title()
    return None


def extract_contact_headline(card_text: str | None, name: str | None) -> str | None:
    if not card_text:
        return None
    for line in [clean_display_text(line) for line in card_text.splitlines()]:
        if not line or line == name or line.lower() in IGNORED_CONTACT_TEXTS:
            continue
        if any(heading.lower() == line.lower() for heading in HIRING_TEAM_HEADINGS):
            continue
        if len(line) <= 180:
            return line
    return None


def extract_hiring_contacts_from_html(html: str, base_url: str = "https://www.linkedin.com") -> HiringContactsExtractionResult:
    parser = _HiringTeamHTMLParser()
    parser.feed(html or "")
    if not parser.heading_seen:
        return HiringContactsExtractionResult("not_present", [])
    card_contacts = _extract_hiring_contacts_from_card_html(html or "", base_url)
    if card_contacts:
        return HiringContactsExtractionResult("found", deduplicate_hiring_contacts(card_contacts))
    contacts = []
    for href, text, card_text in parser.links:
        profile_url = normalize_linkedin_profile_url(_resolve_url(href, base_url))
        if not profile_url:
            continue
        name = extract_contact_name(text, profile_url)
        if not name:
            continue
        contacts.append(
            HiringContact(
                name=name,
                profile_url=profile_url,
                headline=extract_contact_headline(card_text, name),
                role=None,
                source=LINKEDIN_HIRING_CONTACT_SOURCE,
            )
        )
    return HiringContactsExtractionResult("found", deduplicate_hiring_contacts(contacts))


def _extract_hiring_contacts_from_card_html(html: str, base_url: str) -> list[HiringContact]:
    contacts: list[HiringContact] = []
    heading_match = re.search("|".join(re.escape(heading) for heading in HIRING_TEAM_HEADINGS), html, re.IGNORECASE)
    if not heading_match:
        return contacts
    section = html[heading_match.start() :]
    chunks = re.findall(r"<(?:li|div)\b[^>]*>(.*?)</(?:li|div)>", section, flags=re.IGNORECASE | re.DOTALL)
    for chunk in chunks:
        link = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", chunk, flags=re.IGNORECASE | re.DOTALL)
        if not link:
            continue
        profile_url = normalize_linkedin_profile_url(_resolve_url(link.group(1), base_url))
        if not profile_url:
            continue
        link_text = _strip_tags(link.group(2))
        paragraphs = [_strip_tags(match) for match in re.findall(r"<p\b[^>]*>(.*?)</p>", chunk, flags=re.IGNORECASE | re.DOTALL)]
        card_text = "\n".join([link_text, *paragraphs]) if paragraphs else _strip_tags(chunk)
        name = extract_contact_name(link_text, profile_url)
        if not name:
            continue
        contacts.append(
            HiringContact(
                name=name,
                profile_url=profile_url,
                headline=extract_contact_headline(card_text, name),
                role=None,
                source=LINKEDIN_HIRING_CONTACT_SOURCE,
            )
        )
    return contacts


def _strip_tags(html: str) -> str:
    return clean_display_text(re.sub(r"<[^>]+>", "\n", html))


def _resolve_url(url: str, base_url: str) -> str:
    if url.startswith("/"):
        base = urlsplit(base_url)
        return urlunsplit((base.scheme or "https", base.netloc or "www.linkedin.com", url, "", ""))
    return url


class _HiringTeamHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.heading_seen = False
        self._in_hiring_section = False
        self._section_depth = 0
        self._current_link: dict[str, Any] | None = None
        self._card_text: list[str] = []
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        aria = attrs_dict.get("aria-label") or ""
        class_name = attrs_dict.get("class") or ""
        if any(heading.lower() in aria.lower() for heading in HIRING_TEAM_HEADINGS):
            self.heading_seen = True
            self._in_hiring_section = True
        if self._in_hiring_section:
            self._section_depth += 1
        if tag == "section" and any(token in class_name.lower() for token in ["company", "description"]):
            if self._in_hiring_section and self.links:
                self._in_hiring_section = False
        if self._in_hiring_section and tag == "a":
            self._current_link = {"href": attrs_dict.get("href") or "", "text": []}

    def handle_endtag(self, tag: str) -> None:
        if self._current_link is not None and tag == "a":
            text = clean_display_text(" ".join(self._current_link["text"]))
            self.links.append((self._current_link["href"], text, "\n".join(self._card_text)))
            self._current_link = None
        if self._in_hiring_section:
            self._section_depth = max(0, self._section_depth - 1)

    def handle_data(self, data: str) -> None:
        text = clean_display_text(data)
        if not text:
            return
        if any(heading.lower() == text.lower() for heading in HIRING_TEAM_HEADINGS):
            self.heading_seen = True
            self._in_hiring_section = True
        if self._in_hiring_section:
            self._card_text.append(text)
        if self._current_link is not None:
            self._current_link["text"].append(text)
