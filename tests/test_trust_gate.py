from __future__ import annotations

import json

from scripts import run_trust_gate as gate


def test_trust_gate_runs_offline_checks_and_writes_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "run_smoke_e2e", lambda db_path: {"passed": True, "database": str(db_path)})
    monkeypatch.setattr(gate, "run_guardrail_smoke", lambda: {"passed": True})
    monkeypatch.setattr(gate, "run_scan_smoke", lambda db_path: {"passed": True, "database": str(db_path)})
    fixture_dir = tmp_path / "golden"
    fixture_dir.mkdir()
    _write_fixture(fixture_dir / "ranking.json", "ranking-good", "ranking")
    _write_fixture(fixture_dir / "materials.json", "materials-good", "application_materials")
    _write_fixture(fixture_dir / "ats.json", "ats-good", "ats_cv")
    output = tmp_path / "trust-gate.json"

    summary = gate.run_trust_gate(
        gate.parse_args(
            [
                "--golden-cases",
                str(fixture_dir),
                "--min-reviewed-golden",
                "3",
                "--min-per-surface",
                "1",
                "--min-restraint-cases",
                "1",
                "--output",
                str(output),
            ]
        )
    )

    assert summary["passed"] is True
    assert summary["checks"]["golden_fixtures"]["by_surface"] == {
        "ranking": 1,
        "application_materials": 1,
        "ats_cv": 1,
    }
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True


def test_golden_fixture_audit_requires_minimum_coverage(tmp_path):
    fixture_dir = tmp_path / "golden"
    fixture_dir.mkdir()
    _write_fixture(fixture_dir / "ranking.json", "ranking-only", "ranking", restraint=False)

    result = gate.audit_golden_fixtures(fixture_dir, min_reviewed=3, min_per_surface=1, min_restraint_cases=1)

    assert result["passed"] is False
    assert "reviewed_golden_below_minimum:1<3" in result["issues"]
    assert "surface_below_minimum:application_materials:0<1" in result["issues"]
    assert "surface_below_minimum:ats_cv:0<1" in result["issues"]
    assert "restraint_cases_below_minimum:0<1" in result["issues"]


def _write_fixture(path, case_id: str, surface: str, *, restraint: bool = True) -> None:
    expected = {"allowed_decisions": ["MAYBE", "SKIP", "AVOID"]} if restraint else {}
    path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "surface": surface,
                "review_status": "reviewed",
                "source": {"job_id": 1},
                "raw_input": {
                    "title": "Backend Engineer",
                    "company": "Acme",
                    "job_html_or_text": "Build Python APIs.",
                },
                "candidate_profile_snapshot": {
                    "profile": {
                        "base_cv_text": "Backend engineer with Python.",
                        "skills": [{"name": "Python", "level": "strong"}],
                    }
                },
                "expected": expected,
            }
        ),
        encoding="utf-8",
    )
