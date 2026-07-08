from __future__ import annotations

SPEED_RANKING_VERSION = "ranking_v1.1.0-speed"
NVIDIA_RANKING_VERSION = "ranking_v1.1.0-nvidia"

RANKING_VERSION_PRIORITY = {
    NVIDIA_RANKING_VERSION: 0,
    SPEED_RANKING_VERSION: 10,
}


def ranking_version_sort_key(version: str) -> tuple[int, str]:
    return (RANKING_VERSION_PRIORITY.get(version, 100), version)
