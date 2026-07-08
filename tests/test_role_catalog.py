from __future__ import annotations

from joborchestrator.ranking.role_catalog import classify_profile_role, profile_search_terms, role_fit_score
from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.scanning.linkedin import build_busquedas_from_profile


def test_profile_role_aliases_drive_classification() -> None:
    profile = CandidateProfile(
        target_roles=["Presales Engineer"],
        secondary_roles=["Customer Success Manager"],
        role_aliases={"Presales Engineer": ["Consultor preventa", "Solutions Consultant"]},
    )

    role = classify_profile_role("Buscamos consultor preventa para demos tecnicas", profile)

    assert role["primary_role"] == "Presales Engineer"
    assert role["priority"] == "target"
    assert role_fit_score(role) >= 80


def test_profile_search_terms_are_profile_driven() -> None:
    profile = CandidateProfile(
        target_roles=["Registered Nurse"],
        role_aliases={"Registered Nurse": ["RN", "Clinical Nurse"]},
        preferred_locations=["Spain"],
        preferred_work_modes=["remote"],
    )

    terms = profile_search_terms(profile)
    searches = build_busquedas_from_profile(profile)

    assert terms == ["Registered Nurse", "RN", "Clinical Nurse"]
    assert {"keywords": "RN", "ubicacion": "Spain", "categoria": "rn"} in searches
    assert {"keywords": "Clinical Nurse", "ubicacion": "European Union", "categoria": "clinical_nurse"} in searches
