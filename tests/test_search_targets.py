from joborchestrator.scanning.search_targets import build_search_intents, targets_from_profile


def test_build_search_intents_expands_each_target_work_mode():
    intents = build_search_intents(
        application_targets=[
            {"label": "Malaga", "location": "Malaga, Spain", "work_modes": ["onsite", "hybrid", "remote"]},
            {"label": "Europe Remote", "location": "Europe", "work_modes": ["remote"]},
            {"label": "Barcelona", "location": "Barcelona, Spain", "work_modes": ["onsite"]},
        ]
    )

    assert [(intent.location, intent.work_mode) for intent in intents] == [
        ("Malaga, Spain", "onsite"),
        ("Malaga, Spain", "hybrid"),
        ("Malaga, Spain", "remote"),
        ("Europe", "remote"),
        ("Barcelona, Spain", "onsite"),
    ]


def test_targets_from_profile_prefers_explicit_targets():
    profile = {
        "preferred_locations": ["Spain"],
        "preferred_work_modes": ["remote"],
        "application_targets": [
            {"label": "Barcelona", "location": "Barcelona, Spain", "work_modes": ["onsite"]},
        ],
    }

    assert targets_from_profile(profile) == [
        {"label": "Barcelona", "location": "Barcelona, Spain", "work_modes": ["onsite"]}
    ]
