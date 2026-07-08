from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.scanning.normalization import normalize_text


@dataclass(frozen=True)
class RoleCatalogEntry:
    name: str
    priority: str
    aliases: tuple[str, ...] = ()

    @property
    def search_terms(self) -> tuple[str, ...]:
        return _dedupe([self.name, *self.aliases])


def role_catalog_from_profile(profile: CandidateProfile) -> list[RoleCatalogEntry]:
    entries: list[RoleCatalogEntry] = []
    seen: set[str] = set()
    for role in profile.target_roles:
        _append_role(entries, seen, role, "target", profile.role_aliases.get(role, []))
    for role in profile.secondary_roles:
        _append_role(entries, seen, role, "secondary", profile.role_aliases.get(role, []))
    return entries


def classify_profile_role(text: str, profile: CandidateProfile) -> dict:
    catalog = role_catalog_from_profile(profile)
    if not catalog:
        return {
            "primary_role": "Other",
            "secondary_roles": [],
            "confidence": 0.35,
            "reason": "No target roles configured in profile.",
            "priority": "unknown",
            "explicit_match": False,
        }

    normalized = normalize_text(text).replace("fullstack", "full stack")
    scores: dict[str, int] = {entry.name: 0 for entry in catalog}
    priority_by_role = {entry.name: entry.priority for entry in catalog}
    for entry in catalog:
        for term in entry.search_terms:
            term_norm = normalize_text(term)
            if not term_norm:
                continue
            if _contains_term(normalized, term_norm):
                scores[entry.name] += 50 if term == entry.name else 42
            elif _has_meaningful_overlap(normalized, term_norm):
                scores[entry.name] += 30 if term == entry.name else 24

    primary = max(scores, key=scores.get)
    sorted_roles = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_score = sorted_roles[0][1]
    if top_score == 0:
        first = catalog[0]
        return {
            "primary_role": first.name,
            "secondary_roles": [entry.name for entry in catalog[1:3]],
            "confidence": 0.35,
            "reason": "No explicit role label found; using profile target role as prior.",
            "priority": first.priority,
            "explicit_match": False,
        }

    secondary = [role for role, score in sorted_roles[1:4] if score >= 25]
    return {
        "primary_role": primary,
        "secondary_roles": secondary,
        "confidence": round(min(0.95, max(0.4, top_score / 75)), 2),
        "reason": f"Matched profile role terms for {primary}.",
        "priority": priority_by_role.get(primary, "unknown"),
        "explicit_match": True,
    }


def role_fit_score(role_info: dict) -> int:
    priority = role_info.get("priority")
    confidence = float(role_info.get("confidence", 0.35))
    if not role_info.get("explicit_match"):
        return 35
    if priority == "target":
        base = 92
    elif priority == "secondary":
        base = 72
    else:
        base = 45
    return _clamp(base * (0.7 + min(confidence, 0.95) * 0.3))


def profile_search_terms(profile: CandidateProfile) -> list[str]:
    terms: list[str] = []
    for entry in role_catalog_from_profile(profile):
        terms.extend(entry.search_terms)
    return _dedupe(terms)


def _append_role(
    entries: list[RoleCatalogEntry],
    seen: set[str],
    role: str,
    priority: str,
    aliases: Iterable[str],
) -> None:
    name = str(role or "").strip()
    key = normalize_text(name)
    if not name or key in seen:
        return
    seen.add(key)
    entries.append(RoleCatalogEntry(name=name, priority=priority, aliases=tuple(_dedupe(aliases))))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = normalize_text(text)
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _contains_term(text: str, term: str) -> bool:
    padded = f" {text} "
    return f" {term} " in padded or term in text


def _has_meaningful_overlap(text: str, term: str) -> bool:
    generic = {"engineer", "developer", "manager", "consultant", "specialist", "senior", "junior", "mid", "role"}
    text_tokens = {token for token in text.split() if token not in generic}
    term_tokens = {token for token in term.replace("fullstack", "full stack").split() if token not in generic}
    overlap = text_tokens & term_tokens
    if len(overlap) >= 2:
        return True
    return any(len(token) >= 6 for token in overlap) and len(term_tokens) <= 3


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))
