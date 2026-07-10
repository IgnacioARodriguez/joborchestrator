from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_WORK_MODES = {"onsite", "hybrid", "remote"}


@dataclass(slots=True)
class ApplicationTarget:
    label: str
    location: str
    work_modes: list[str]


@dataclass(slots=True)
class SearchIntent:
    label: str
    location: str
    work_mode: str


def normalize_application_targets(value: Any) -> list[ApplicationTarget]:
    targets: list[ApplicationTarget] = []
    if not isinstance(value, list):
        return targets
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        location = str(item.get("location") or "").strip()
        if not location:
            locations = item.get("locations")
            if isinstance(locations, list) and locations:
                location = str(locations[0] or "").strip()
        if not location:
            continue
        work_modes = _clean_work_modes(item.get("work_modes"))
        if not work_modes:
            work_modes = ["remote"]
        label = str(item.get("label") or item.get("name") or f"{location} ({', '.join(work_modes)})").strip()
        targets.append(ApplicationTarget(label=label or f"Target {index + 1}", location=location, work_modes=work_modes))
    return targets


def build_search_intents(
    *,
    application_targets: list[dict[str, Any]] | None = None,
    location: str | None = None,
    remote: bool = True,
) -> list[SearchIntent]:
    targets = normalize_application_targets(application_targets)
    if not targets:
        mode = "remote" if remote else "onsite"
        return [SearchIntent(label=f"{location or 'Spain'} {mode}", location=location or "Spain", work_mode=mode)]
    intents: list[SearchIntent] = []
    seen = set()
    for target in targets:
        for mode in target.work_modes:
            key = (target.location.lower(), mode)
            if key in seen:
                continue
            seen.add(key)
            intents.append(SearchIntent(label=f"{target.label} / {mode}", location=target.location, work_mode=mode))
    return intents


def targets_from_profile(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not profile:
        return []
    explicit = normalize_application_targets(profile.get("application_targets"))
    if explicit:
        return [_target_dict(target) for target in explicit]
    locations = _clean_strings(profile.get("preferred_locations")) or ["Spain"]
    modes = _clean_work_modes(profile.get("preferred_work_modes")) or ["remote"]
    return [{"label": location, "location": location, "work_modes": modes} for location in locations]


def _target_dict(target: ApplicationTarget) -> dict[str, Any]:
    return {"label": target.label, "location": target.location, "work_modes": target.work_modes}


def _clean_work_modes(value: Any) -> list[str]:
    modes = []
    for item in _clean_strings(value):
        normalized = item.lower()
        if normalized in {"presencial", "on-site", "on site"}:
            normalized = "onsite"
        if normalized in {"híbrido", "hibrido"}:
            normalized = "hybrid"
        if normalized in {"remoto", "remota"}:
            normalized = "remote"
        if normalized in VALID_WORK_MODES and normalized not in modes:
            modes.append(normalized)
    return modes


def _clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out
