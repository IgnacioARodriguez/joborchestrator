from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AutofillNotes:
    core_pitch: str
    availability: str | None = None
    work_authorization: str | None = None
    location_note: str | None = None
    application_caveats: list[str] = field(default_factory=list)


def parse_autofill(value: object) -> AutofillNotes:
    if isinstance(value, dict):
        return AutofillNotes(
            core_pitch=str(value.get("core_pitch") or "").strip(),
            availability=_optional_string(value.get("availability")),
            work_authorization=_optional_string(value.get("work_authorization")),
            location_note=_optional_string(value.get("location_note")),
            application_caveats=[str(item).strip() for item in value.get("application_caveats") or [] if str(item).strip()],
        )
    if isinstance(value, str) and value.strip().startswith("{"):
        raise ValueError("autofill must be an object internally, not a JSON-encoded string")
    return AutofillNotes(core_pitch=str(value or "").strip())


def render_autofill(notes: AutofillNotes) -> str:
    lines = [notes.core_pitch.strip()] if notes.core_pitch.strip() else []
    for label, value in [
        ("Availability", notes.availability),
        ("Work authorization", notes.work_authorization),
        ("Location", notes.location_note),
    ]:
        if value:
            lines.append(f"{label}: {value}")
    if notes.application_caveats:
        lines.append("Caveats: " + "; ".join(notes.application_caveats))
    return "\n".join(lines)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
