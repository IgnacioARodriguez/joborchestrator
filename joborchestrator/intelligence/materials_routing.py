from __future__ import annotations

import os
from typing import Literal

CvStrategy = Literal["auto", "controlled", "legacy"]


def controlled_cv_enabled() -> bool:
    return _flag_enabled("MATERIALS_CONTROLLED_CV_ENABLED")


def nvidia_planner_enabled() -> bool:
    return _flag_enabled("MATERIALS_NVIDIA_PLANNER_ENABLED")


def openai_fallback_enabled() -> bool:
    return _flag_enabled("MATERIALS_OPENAI_FALLBACK_ENABLED")


def resolve_cv_pipeline(strategy: str | None = None) -> str:
    requested = str(strategy or "auto").strip().lower()
    if requested not in {"auto", "controlled", "legacy"}:
        raise ValueError(f"Unsupported CV generation strategy: {strategy!r}")
    if requested == "controlled":
        return "controlled_cv"
    if requested == "legacy":
        return "legacy_freeform"
    return (
        "controlled_cv"
        if controlled_cv_enabled() and nvidia_planner_enabled()
        else "legacy_freeform"
    )


def materials_routing_snapshot(strategy: str | None = None) -> dict:
    requested = str(strategy or "auto").strip().lower()
    return {
        "requested_cv_strategy": requested,
        "selected_pipeline": resolve_cv_pipeline(requested),
        "effective_flags": {
            "controlled_cv_enabled": controlled_cv_enabled(),
            "nvidia_planner_enabled": nvidia_planner_enabled(),
            "openai_fallback_enabled": openai_fallback_enabled(),
        },
    }


def max_semantic_repairs() -> int:
    return max(0, int(os.getenv("MATERIALS_MAX_SEMANTIC_REPAIRS", "1")))


def max_transport_retries() -> int:
    return max(0, int(os.getenv("MATERIALS_MAX_TRANSPORT_RETRIES", "2")))


def should_auto_generate_materials(ranking: dict | None, *, override: bool = False) -> bool:
    decision = str((ranking or {}).get("decision") or "").upper()
    if decision in {"AVOID", "SKIP"} and not override:
        return False
    return True


def _flag_enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
