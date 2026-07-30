from __future__ import annotations

from pathlib import Path

from scripts.run_materials_offline_integration import run_offline_integration


def test_materials_offline_integration_covers_required_scenarios():
    report = run_offline_integration(Path("tests/fixtures/materials_controlled_offline_cases.json"))

    assert report["missing_scenarios"] == []
    assert set(report["scenario_coverage"]) == set(report["required_scenarios"])
    assert report["failed"] == 0, report["cases"]


def test_materials_offline_integration_records_parse_review_case():
    report = run_offline_integration(Path("tests/fixtures/materials_controlled_offline_cases.json"))
    parse_case = next(case for case in report["cases"] if case["case_id"] == "incomplete_cv_parse_requires_review")

    assert parse_case["passed"] is True
    assert "incomplete_cv_parse" in parse_case["scenarios"]
