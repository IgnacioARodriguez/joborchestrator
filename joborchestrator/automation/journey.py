from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


JourneyPhase = Literal[
    "surface_discovery",
    "schema_extracted",
    "answers_resolved",
    "actions_planned",
    "actions_executed",
    "validation_clean",
    "validation_failed",
    "final_review",
]


@dataclass(frozen=True)
class InteractionSurface:
    surface_id: str
    kind: Literal["page", "frame", "shadow_root", "popup"]
    origin: str
    parent_surface_id: str | None = None
    accessible: bool = True
    challenge_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlHandle:
    surface_id: str
    control_id: str
    semantic_role: str
    accessible_name: str
    native_type: str | None
    locator_strategies: list[str] = field(default_factory=list)
    required: bool = False
    enabled: bool = True
    visible: bool = True
    confidence: float = 0.5
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannedAction:
    action_type: str
    field_name: str
    canonical_key: str | None
    field_type: str
    policy: Literal["allow", "require_confirmation", "forbid"]
    surface_id: str | None = None
    control_handle: dict[str, Any] | None = None
    source: str | None = None
    value_preview: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApplicationActionPlan:
    phase: JourneyPhase
    provider: str
    actions: list[PlannedAction] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    forbidden: list[PlannedAction] = field(default_factory=list)
    expected_postconditions: list[dict[str, Any]] = field(default_factory=list)
    form_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "provider": self.provider,
            "actions": [action.to_dict() for action in self.actions],
            "unresolved": self.unresolved,
            "forbidden": [action.to_dict() for action in self.forbidden],
            "expected_postconditions": self.expected_postconditions,
            "form_fingerprint": self.form_fingerprint,
            "summary": {
                "actions": len(self.actions),
                "unresolved": len(self.unresolved),
                "forbidden": len(self.forbidden),
                "expected_postconditions": len(self.expected_postconditions),
            },
        }


@dataclass(frozen=True)
class JourneyStep:
    phase: JourneyPhase
    surface: InteractionSurface
    schema: dict[str, Any]
    mapping: dict[str, Any]
    action_plan: ApplicationActionPlan
    browser_surface: Any = field(repr=False, compare=False)
    surfaces: list[InteractionSurface] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "surface": self.surface.to_dict(),
            "surfaces": [surface.to_dict() for surface in self.surfaces],
            "schema": self.schema,
            "mapping": self.mapping,
            "action_plan": self.action_plan.to_dict(),
        }


class ApplicationJourneyEngine:
    """Builds an auditable application step without owning browser execution yet."""

    async def prepare_initial_step(
        self,
        *,
        page: Any,
        adapter: Any,
        capabilities: Any,
        html: str,
        profile: dict[str, Any],
        answer_bank: list[dict[str, Any]],
    ) -> JourneyStep:
        candidates = await self._discover_candidate_schemas(
            page=page,
            adapter=adapter,
            capabilities=capabilities,
            html=html,
        )
        selected = _select_schema_candidate(candidates)
        surface = selected["surface"]
        schema = selected["schema"]
        browser_surface = selected["browser_surface"]
        surfaces = [candidate["surface"] for candidate in candidates]
        return await self.inspect_surface(
            adapter=adapter,
            capabilities=capabilities,
            surface=surface,
            browser_surface=browser_surface,
            html=html,
            profile=profile,
            answer_bank=answer_bank,
            surfaces=surfaces,
        )

    async def inspect_surface(
        self,
        *,
        adapter: Any,
        capabilities: Any,
        surface: InteractionSurface,
        browser_surface: Any,
        html: str,
        profile: dict[str, Any],
        answer_bank: list[dict[str, Any]],
        surfaces: list[InteractionSurface] | None = None,
    ) -> JourneyStep:
        if capabilities.can_detect_fields:
            schema = await adapter.extract_form_schema_page(browser_surface)
            schema = _with_control_handles(schema, surface.surface_id)
        else:
            schema = adapter.extract_form_schema_html(html)
        mapping = adapter.map_answers(schema, profile, answer_bank)
        if capabilities.can_detect_fields and not (schema.get("fields") or []):
            mapping.setdefault("unknown_fields", []).append(
                {
                    "name": "form_detection",
                    "label": "No application form fields were detected.",
                    "type": "unknown",
                    "required": True,
                    "sensitive": False,
                    "classification": "unknown",
                }
            )
        action_plan = build_action_plan(
            provider=str(adapter.provider),
            schema=schema,
            mapping=mapping,
        )
        return JourneyStep(
            phase="actions_planned",
            surface=surface,
            schema=schema,
            mapping=mapping,
            action_plan=action_plan,
            browser_surface=browser_surface,
            surfaces=surfaces or [surface],
        )

    async def _discover_candidate_schemas(
        self,
        *,
        page: Any,
        adapter: Any,
        capabilities: Any,
        html: str,
    ) -> list[dict[str, Any]]:
        main_surface = InteractionSurface(
            surface_id="main",
            kind="page",
            origin=_origin_from_url(str(getattr(page, "url", "") or "")),
            accessible=True,
        )
        if not capabilities.can_detect_fields:
            return [{"surface": main_surface, "schema": adapter.extract_form_schema_html(html), "browser_surface": page}]

        candidates = [
            {
                "surface": main_surface,
                "schema": await adapter.extract_form_schema_page(page),
                "browser_surface": page,
            }
        ]
        for index, frame in enumerate(getattr(page, "frames", []) or []):
            if frame == getattr(page, "main_frame", None):
                continue
            surface = InteractionSurface(
                surface_id=f"frame:{index}",
                kind="frame",
                origin=_origin_from_url(str(getattr(frame, "url", "") or "")),
                parent_surface_id="main",
                accessible=True,
            )
            try:
                schema = await adapter.extract_form_schema_page(frame)
            except Exception:
                candidates.append(
                    {
                        "surface": InteractionSurface(
                            surface_id=surface.surface_id,
                            kind="frame",
                            origin=surface.origin,
                            parent_surface_id="main",
                            accessible=False,
                        ),
                        "schema": {"provider": str(adapter.provider), "fields": []},
                        "browser_surface": frame,
                    }
                )
                continue
            candidates.append({"surface": surface, "schema": schema, "browser_surface": frame})
        return candidates


def build_action_plan(*, provider: str, schema: dict[str, Any], mapping: dict[str, Any]) -> ApplicationActionPlan:
    actions: list[PlannedAction] = []
    forbidden: list[PlannedAction] = []
    control_by_field = _control_handles_by_field(schema)
    for answer in mapping.get("answers") or []:
        action = _planned_action_for_answer(answer, control_by_field.get(str(answer.get("field_name") or "")))
        if action is None:
            continue
        if action.policy == "allow":
            actions.append(action)
        elif action.policy == "forbid":
            forbidden.append(action)
    unresolved = list(mapping.get("unknown_fields") or [])
    return ApplicationActionPlan(
        phase="actions_planned",
        provider=provider,
        actions=actions,
        unresolved=unresolved,
        forbidden=forbidden,
        expected_postconditions=[
            {
                "field_name": action.field_name,
                "action_type": action.action_type,
                "canonical_key": action.canonical_key,
                "surface_id": action.surface_id,
                "control_fingerprint": (action.control_handle or {}).get("fingerprint"),
            }
            for action in actions
        ],
        form_fingerprint=_form_fingerprint(schema),
    )


def _planned_action_for_answer(answer: dict[str, Any], control_handle: dict[str, Any] | None = None) -> PlannedAction | None:
    field_name = str(answer.get("field_name") or "").strip()
    value = str(answer.get("value") or "").strip()
    canonical = str(answer.get("canonical_key") or "").strip() or None
    field_type = str(answer.get("field_type") or "text")
    if not field_name:
        return None
    if answer.get("requires_confirmation"):
        return PlannedAction(
            action_type="review_answer",
            field_name=field_name,
            canonical_key=canonical,
            field_type=field_type,
            policy="require_confirmation",
            surface_id=(control_handle or {}).get("surface_id"),
            control_handle=control_handle,
            source=answer.get("source"),
            reason="requires_confirmation",
        )
    if not value:
        return None
    if answer.get("source") != "approved_answer" and canonical not in {
        "full_name",
        "email",
        "phone",
        "linkedin",
        "portfolio",
        "preferred_location",
        "talent_pool",
    }:
        return PlannedAction(
            action_type="review_answer",
            field_name=field_name,
            canonical_key=canonical,
            field_type=field_type,
            policy="require_confirmation",
            surface_id=(control_handle or {}).get("surface_id"),
            control_handle=control_handle,
            source=answer.get("source"),
            reason="unapproved_non_profile_answer",
        )
    if field_type in {"select", "radio"} and _match_option(value, list(answer.get("options") or [])) is None:
        return PlannedAction(
            action_type="review_answer",
            field_name=field_name,
            canonical_key=canonical,
            field_type=field_type,
            policy="require_confirmation",
            surface_id=(control_handle or {}).get("surface_id"),
            control_handle=control_handle,
            source=answer.get("source"),
            reason="option_not_matched",
        )
    if field_type == "checkbox" and _normalized(value) not in {"yes", "true", "checked", "1"}:
        return None
    return PlannedAction(
        action_type=_action_type_for_field(field_type),
        field_name=field_name,
        canonical_key=canonical,
        field_type=field_type,
        policy="allow",
        surface_id=(control_handle or {}).get("surface_id"),
        control_handle=control_handle,
        source=answer.get("source"),
        value_preview=_preview_value(value),
    )


def _action_type_for_field(field_type: str) -> str:
    return {
        "select": "select_option",
        "radio": "choose_radio",
        "checkbox": "check",
        "file": "upload_file",
    }.get(field_type, "fill_text")


def _preview_value(value: str) -> str:
    if len(value) <= 80:
        return value
    return f"{value[:77]}..."


def _match_option(value: str, options: list[Any]) -> dict[str, str] | None:
    wanted = _normalized(value)
    matches: list[dict[str, str]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "")
        raw_value = str(option.get("value") or "")
        if wanted and wanted in {_normalized(label), _normalized(raw_value)}:
            matches.append({"label": label, "value": raw_value})
    return matches[0] if len(matches) == 1 else None


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", value.lower())).strip()


def _form_fingerprint(schema: dict[str, Any]) -> str:
    fields = [
        f"{field.get('name') or field.get('id') or ''}:{field.get('type') or ''}:{field.get('required') or False}"
        for field in schema.get("fields") or []
        if isinstance(field, dict)
    ]
    return "|".join(fields)


def _select_schema_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("No interaction surfaces were discovered.")
    return max(candidates, key=lambda candidate: _schema_score(candidate.get("schema") or {}))


def _schema_score(schema: dict[str, Any]) -> int:
    fields = [field for field in schema.get("fields") or [] if isinstance(field, dict)]
    score = len(fields)
    for field in fields:
        label = f"{field.get('label') or ''} {field.get('name') or ''}".lower()
        field_type = str(field.get("type") or "")
        if field_type == "file":
            score += 8
        if any(marker in label for marker in ("resume", "cv", "email", "phone", "linkedin", "portfolio")):
            score += 3
        if field.get("required"):
            score += 1
    for candidate in schema.get("form_candidates") or []:
        if isinstance(candidate, dict):
            score += int(candidate.get("score") or 0)
    return score


def _with_control_handles(schema: dict[str, Any], surface_id: str) -> dict[str, Any]:
    fields = []
    for index, field in enumerate(schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        enriched = dict(field)
        handle = _control_handle_for_field(enriched, surface_id, index)
        enriched["surface_id"] = surface_id
        enriched["control_handle"] = handle.to_dict()
        fields.append(enriched)
    return {**schema, "surface_id": surface_id, "fields": fields}


def _control_handle_for_field(field: dict[str, Any], surface_id: str, index: int) -> ControlHandle:
    name = str(field.get("name") or field.get("id") or field.get("label") or f"field-{index}")
    label = str(field.get("label") or name)
    native_type = str(field.get("type") or "text")
    role = {
        "select": "choice",
        "radio": "choice",
        "checkbox": "boolean",
        "file": "file",
        "textarea": "text",
    }.get(native_type, "text")
    locator_strategy = str(field.get("locator_strategy") or "")
    strategies = [locator_strategy] if locator_strategy else []
    fingerprint = f"{surface_id}:{name}:{native_type}:{bool(field.get('required'))}"
    return ControlHandle(
        surface_id=surface_id,
        control_id=name,
        semantic_role=role,
        accessible_name=label,
        native_type=native_type,
        locator_strategies=strategies,
        required=bool(field.get("required")),
        confidence=float(field.get("confidence") or 0.5),
        fingerprint=fingerprint,
    )


def _control_handles_by_field(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}
    for field in schema.get("fields") or []:
        if not isinstance(field, dict):
            continue
        handle = field.get("control_handle")
        if not isinstance(handle, dict):
            continue
        for key in {str(field.get("name") or ""), str(field.get("id") or ""), str(field.get("label") or "")}:
            if key:
                controls[key] = handle
    return controls


def _origin_from_url(url: str) -> str:
    if "://" not in url:
        return url or "about:blank"
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"
