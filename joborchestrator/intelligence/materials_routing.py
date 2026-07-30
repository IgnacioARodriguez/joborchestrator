from __future__ import annotations

import os


def controlled_cv_enabled() -> bool:
    return _flag_enabled("MATERIALS_CONTROLLED_CV_ENABLED")


def nvidia_planner_enabled() -> bool:
    return _flag_enabled("MATERIALS_NVIDIA_PLANNER_ENABLED")


def openai_fallback_enabled() -> bool:
    return _flag_enabled("MATERIALS_OPENAI_FALLBACK_ENABLED")


def max_semantic_repairs() -> int:
    return max(0, int(os.getenv("MATERIALS_MAX_SEMANTIC_REPAIRS", "1")))


def should_auto_generate_materials(ranking: dict | None, *, override: bool = False) -> bool:
    decision = str((ranking or {}).get("decision") or "").upper()
    if decision in {"AVOID", "SKIP"} and not override:
        return False
    return True


def _flag_enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
