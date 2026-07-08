from __future__ import annotations

from joborchestrator.ranking.profile import load_candidate_profile


def test_load_candidate_profile_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CANDIDATE_PROFILE_YAML",
        """
target_roles:
  - Backend Engineer
strong_skills:
  - Python
real_experience_years: 4
""",
    )

    profile = load_candidate_profile()

    assert profile.target_roles == ["Backend Engineer"]
    assert profile.strong_skills == ["Python"]
    assert profile.real_experience_years == 4
