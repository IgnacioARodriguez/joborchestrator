from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from joborchestrator.paths import PROJECT_ROOT
from joborchestrator.ranking.schemas import CandidateProfile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "candidate_profile.yml"
PROFILE_ENV_VAR = "CANDIDATE_PROFILE_YAML"


def load_candidate_profile(path: str | Path | None = None) -> CandidateProfile:
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    data: dict[str, Any] = {}
    env_profile = os.getenv(PROFILE_ENV_VAR) if path is None else None
    if env_profile:
        data = yaml.safe_load(env_profile) or {}
    elif profile_path.exists():
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    return CandidateProfile(**data)
