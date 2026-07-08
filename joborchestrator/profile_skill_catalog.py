from __future__ import annotations

import json
from pathlib import Path

SEED_PATH = Path(__file__).with_name("catalogs") / "skill_catalog_seed.json"


def load_default_skill_catalog() -> dict[str, list[str]]:
    with SEED_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        str(category): [str(skill) for skill in skills]
        for category, skills in payload.items()
        if isinstance(skills, list)
    }


DEFAULT_SKILL_CATALOG: dict[str, list[str]] = load_default_skill_catalog()
