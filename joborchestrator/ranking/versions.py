from __future__ import annotations

SPEED_RANKING_VERSION = "ranking_v1.1.0-speed"
NVIDIA_RANKING_VERSION = "ranking_v1.1.0-nvidia"
LEGACY_HEURISTIC_RANKING_VERSION = "ranking_v1.0.0"
OPENAI_RANKING_VERSION_BASE = "ranking_v1.1.0-openai"

RANKING_VERSION_PRIORITY = {
    NVIDIA_RANKING_VERSION: 0,
    SPEED_RANKING_VERSION: 10,
}


def ranking_version_sort_key(version: str) -> tuple[int, str]:
    return (RANKING_VERSION_PRIORITY.get(version, 100), version)


def is_heuristic_ranking_version(version: str | None) -> bool:
    if not version:
        return False
    normalized = version.lower()
    return normalized in {SPEED_RANKING_VERSION, LEGACY_HEURISTIC_RANKING_VERSION} or "speed" in normalized


def is_llm_ranking_version(version: str | None) -> bool:
    if not version or is_heuristic_ranking_version(version):
        return False
    normalized = version.lower()
    return normalized.startswith("ranking_") or "nvidia" in normalized or "openai" in normalized


def filter_llm_ranking_versions(versions: list[str]) -> list[str]:
    return sorted([version for version in versions if is_llm_ranking_version(version)], key=ranking_version_sort_key)
