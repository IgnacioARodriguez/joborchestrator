from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.scanning.linkedin import (
    FRESHNESS_WINDOW_SECONDS,
    SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS,
    TARGET_ROLE_FRESHNESS_WINDOW_SECONDS,
    build_linkedin_search_plan,
    build_busquedas_from_profile,
    build_linkedin_search_params,
    jobs_per_search_limit,
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
    by_key = {
        (search["keywords"], search["ubicacion"]): search
        for search in searches
    }

    backend = by_key[("Backend Engineer", "Spain")]
    assert backend["categoria"] == "backend_engineer"
    assert backend["role_priority"] == "target"
    assert backend["freshness_window_seconds"] == TARGET_ROLE_FRESHNESS_WINDOW_SECONDS
    assert by_key[("Python Engineer", "Spain")]["freshness_window_seconds"] == TARGET_ROLE_FRESHNESS_WINDOW_SECONDS
    assert by_key[("Solutions Engineer", "Spain")]["role_priority"] == "secondary"
    assert by_key[("Solutions Engineer", "Spain")]["freshness_window_seconds"] == SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS

    assert [
        (search["keywords"], search["ubicacion"])
        for search in searches[:3]
    ] == [
        ("Backend Engineer", "Spain"),
        ("Python Engineer", "Spain"),
        ("Solutions Engineer", "Spain"),
    ]


def test_linkedin_searches_deduplicate_work_modes_for_the_same_location():
    profile = CandidateProfile(
        target_roles=["Backend Engineer"],
        application_targets=[
            {
                "label": "Malaga",
                "location": "Malaga, Spain",
                "work_modes": ["onsite", "hybrid", "remote"],
            }
        ],
    )

    searches = build_busquedas_from_profile(profile)
    malaga = [
        search
        for search in searches
        if search["keywords"] == "Backend Engineer"
        and search["ubicacion"] == "Malaga, Spain"
    ]

    assert len(malaga) == 1


def test_linkedin_search_plan_balances_limit_across_search_combinations():
    searches = [
        {"keywords": "Backend Engineer", "ubicacion": "Spain"},
        {"keywords": "Python Engineer", "ubicacion": "Spain"},
        {"keywords": "Solutions Engineer", "ubicacion": "Spain"},
        {"keywords": "Backend Engineer", "ubicacion": "European Union"},
    ]

    assert jobs_per_search_limit(75, searches) == 19
    plan = build_linkedin_search_plan(searches, 75)
    assert plan["terms"] == ["Backend Engineer", "Python Engineer", "Solutions Engineer"]
    assert plan["locations"] == ["Spain", "European Union"]
    assert plan["total_searches"] == 4


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
