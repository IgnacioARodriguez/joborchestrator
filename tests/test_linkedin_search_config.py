from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.scanning.linkedin import (
    FRESHNESS_WINDOW_SECONDS,
    SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS,
    TARGET_ROLE_FRESHNESS_WINDOW_SECONDS,
    build_busquedas_from_profile,
    build_linkedin_search_params,
    resolve_output_dir,
)


def test_resolve_output_dir_uses_tmp_on_vercel(monkeypatch):
    monkeypatch.delenv("LINKEDIN_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    assert resolve_output_dir().as_posix() == "/tmp/salidas_todas_posiciones_raw"


def test_build_busquedas_from_profile_adds_freshness_by_role_priority():
    profile = CandidateProfile(
        target_roles=["Backend Engineer"],
        secondary_roles=["Solutions Engineer"],
        role_aliases={"Backend Engineer": ["Python Engineer"]},
        preferred_locations=["Spain"],
    )

    searches = build_busquedas_from_profile(profile)
    by_keyword = {search["keywords"]: search for search in searches}

    assert by_keyword["Backend Engineer"]["ubicacion"] == "Spain"
    assert by_keyword["Backend Engineer"]["categoria"] == "backend_engineer"
    assert by_keyword["Backend Engineer"]["role_priority"] == "target"
    assert by_keyword["Backend Engineer"]["freshness_window_seconds"] == TARGET_ROLE_FRESHNESS_WINDOW_SECONDS
    assert by_keyword["Python Engineer"]["freshness_window_seconds"] == TARGET_ROLE_FRESHNESS_WINDOW_SECONDS
    assert by_keyword["Solutions Engineer"]["role_priority"] == "secondary"
    assert by_keyword["Solutions Engineer"]["freshness_window_seconds"] == SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS


def test_build_linkedin_search_params_uses_date_sort_and_freshness_filter():
    params = build_linkedin_search_params(
        {
            "keywords": "Backend Engineer",
            "ubicacion": "Spain",
            "freshness_window_seconds": 172800,
            "filtros": {"geoId": "105646813"},
        },
        start=25,
    )

    assert params["keywords"] == "Backend Engineer"
    assert params["location"] == "Spain"
    assert params["start"] == 25
    assert params["sortBy"] == "DD"
    assert params["f_TPR"] == "r172800"
    assert params["geoId"] == "105646813"


def test_build_linkedin_search_params_defaults_to_global_freshness_window():
    params = build_linkedin_search_params({"keywords": "Data", "ubicacion": "Remote"}, start=0)

    assert params["f_TPR"] == f"r{FRESHNESS_WINDOW_SECONDS}"
