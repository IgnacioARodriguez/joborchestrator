from joborchestrator.ranking.versions import (
    NVIDIA_RANKING_VERSION,
    filter_llm_ranking_versions,
    is_heuristic_ranking_version,
)


def test_filter_llm_ranking_versions_excludes_heuristics() -> None:
    versions = [
        "ranking_v1.1.0-speed",
        "ranking_v1.0.0",
        "ranking_v1.1.0+llm:gpt-5.4-mini",
        NVIDIA_RANKING_VERSION,
    ]

    filtered = filter_llm_ranking_versions(versions)

    assert filtered == [NVIDIA_RANKING_VERSION, "ranking_v1.1.0+llm:gpt-5.4-mini"]
    assert is_heuristic_ranking_version("ranking_v1.1.0-speed")
    assert is_heuristic_ranking_version("ranking_v1.0.0")
