from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from joborchestrator.paths import PROJECT_ROOT
from joborchestrator.ranking.schemas import CandidateProfile

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "candidate_profile.yml"


def load_candidate_profile(path: str | Path | None = None) -> CandidateProfile:
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    data: dict[str, Any] = {}
    if profile_path.exists():
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    return CandidateProfile(**data)
