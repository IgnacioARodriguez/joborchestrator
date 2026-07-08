from __future__ import annotations

from joborchestrator.intelligence.cv_profile_extractor import (
    normalize_profile_payload,
    profile_payload_to_candidate_profile,
)


def test_profile_payload_to_candidate_profile_groups_skills_by_level() -> None:
    profile = normalize_profile_payload(
        {
            "target_roles": ["Backend Engineer"],
            "skills": [
                {"name": "Python", "category": "Programming", "level": "strong"},
                {"name": "React", "category": "Frontend", "level": "medium"},
                {"name": "Terraform", "category": "Cloud", "level": "weak"},
            ],
            "real_experience_years": 4,
        }
    )

    candidate = profile_payload_to_candidate_profile(profile)

    assert candidate["target_roles"] == ["Backend Engineer"]
    assert candidate["strong_skills"] == ["Python"]
    assert candidate["medium_skills"] == ["React"]
    assert candidate["weak_skills"] == ["Terraform"]
    assert candidate["real_experience_years"] == 4
