from joborchestrator.intelligence.materials_cv_ir import parse_candidate_cv_ir


def test_career_journey_heading_parses_roles() -> None:
    cv_ir = parse_candidate_cv_ir(
        """Ignacio Rodriguez
ignacio@example.com

Career Journey:
Backend Developer April 2025 - March 2026
Fiction Express
- Built analytics APIs with Python.

Education:
Computer Science""",
        ["Python"],
    )
    assert cv_ir.human_review_required is False
    assert len(cv_ir.roles) == 1
    assert cv_ir.roles[0].company == "Fiction Express"


def test_summary_stops_at_career_journey() -> None:
    cv_ir = parse_candidate_cv_ir(
        """Ignacio Rodriguez

Professional Summary:
Backend developer with Python API experience.

Career Journey:
Backend Developer April 2025 - March 2026
Fiction Express
- Built analytics APIs with Python.

Education:
Computer Science""",
        ["Python"],
    )
    assert [fact.source_text for fact in cv_ir.summary_facts] == ["Backend developer with Python API experience."]
