from __future__ import annotations

from joborchestrator.intelligence.cv_profile_extractor import (
    _extract_json_object,
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


def test_extract_json_object_repairs_common_llm_json_issues() -> None:
    parsed = _extract_json_object(
        """
```json
{
  'headline': 'Backend Developer',
  'target_roles': ['Backend Engineer',],
  'skills': [
    {'name': 'Python', 'category': 'Programming', 'level': 'strong',},
  ],
}
```
"""
    )

    assert parsed["headline"] == "Backend Developer"
    assert parsed["target_roles"] == ["Backend Engineer"]
    assert parsed["skills"][0]["name"] == "Python"
