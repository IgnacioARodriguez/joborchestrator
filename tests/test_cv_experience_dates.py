from __future__ import annotations

import pytest

from joborchestrator.intelligence.materials_cv_ir import parse_candidate_cv_ir


@pytest.mark.parametrize(
    "date_range",
    [
        "April 2025 - March 2026",
        "Apr. 2025 – Mar. 2026",
        "abril 2022 - marzo 2025",
        "abr. 2022 — actualidad",
        "04/2022 - 03/2025",
        "4-2022 – Present",
        "2022.04 - 2025.03",
        "01/04/2022 - 31/03/2025",
        "2022-04-01 - 2025-03-31",
        "2022 - Current",
    ],
)
def test_common_experience_date_ranges_are_preserved(date_range: str) -> None:
    cv_ir = parse_candidate_cv_ir(
        f"""
Ignacio Rodriguez
ignacio@example.com

Professional Experience
Backend Developer {date_range}
Fiction Express
- Built analytics APIs with Python.
- Improved Redis data reliability.
Technologies: Python, REST APIs, Redis

Education
Computer Science
""".strip(),
        ["Python", "REST APIs", "Redis"],
    )

    assert cv_ir.human_review_required is False
    assert cv_ir.parse_warnings == []
    assert len(cv_ir.roles) == 1
    assert cv_ir.roles[0].title == "Backend Developer"
    assert cv_ir.roles[0].company == "Fiction Express"
    assert cv_ir.roles[0].dates == date_range


def test_date_range_inside_bullet_does_not_create_a_second_role() -> None:
    cv_ir = parse_candidate_cv_ir(
        """
Ignacio Rodriguez
ignacio@example.com

Professional Experience
Backend Developer 2022 - Present
Acme Systems
- Migrated records collected from 04/2022 - 03/2025 without downtime.
- Built Python API workflows.
Technologies: Python, REST APIs

Education
Computer Science
""".strip(),
        ["Python", "REST APIs"],
    )

    assert len(cv_ir.roles) == 1
    assert [bullet.source_text for bullet in cv_ir.roles[0].bullets] == [
        "Migrated records collected from 04/2022 - 03/2025 without downtime.",
        "Built Python API workflows.",
    ]


@pytest.mark.parametrize(
    "date_range",
    [
        "13/2022 - 03/2025",
        "2022.13 - 2025.03",
        "April 22 - March 25",
    ],
)
def test_invalid_or_ambiguous_date_ranges_do_not_parse(date_range: str) -> None:
    cv_ir = parse_candidate_cv_ir(
        f"""
Ignacio Rodriguez
ignacio@example.com

Professional Experience
Backend Developer {date_range}
Fiction Express
- Built analytics APIs with Python.
""".strip(),
        ["Python"],
    )

    assert cv_ir.roles == []
    assert cv_ir.human_review_required is True
    assert cv_ir.parse_warnings == ["experience_roles_not_parsed"]
