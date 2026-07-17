from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_ROOT = PROJECT_ROOT / "prompts"
REGISTRY_PATH = PROMPTS_ROOT / "registry.json"


class PromptRegistryError(RuntimeError):
    pass


def load_prompt(surface: str, sub_case: str, *, environment: str | None = None) -> str:
    version = active_prompt_version(surface, sub_case, environment=environment)
    path = PROMPTS_ROOT / surface / sub_case / f"{version}.md"
    if not path.exists():
        raise PromptRegistryError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def active_prompt_version(surface: str, sub_case: str, *, environment: str | None = None) -> str:
    registry = _registry()
    env = environment or os.getenv("PROMPT_ENV") or registry.get("active_environment") or "default"
    environments = registry.get("environments") or {}
    active = environments.get(env)
    if not isinstance(active, dict):
        raise PromptRegistryError(f"Prompt environment not configured: {env}")
    key = f"{surface}/{sub_case}"
    version = active.get(key)
    if not version:
        raise PromptRegistryError(f"Prompt version not configured for {key!r} in environment {env!r}")
    return str(version)


def active_prompt_versions(*, environment: str | None = None) -> dict[str, str]:
    registry = _registry()
    env = environment or os.getenv("PROMPT_ENV") or registry.get("active_environment") or "default"
    active = (registry.get("environments") or {}).get(env)
    if not isinstance(active, dict):
        raise PromptRegistryError(f"Prompt environment not configured: {env}")
    return {str(key): str(value) for key, value in active.items()}


def _registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise PromptRegistryError(f"Prompt registry not found: {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
