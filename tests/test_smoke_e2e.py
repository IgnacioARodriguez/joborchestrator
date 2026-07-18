from __future__ import annotations

from scripts.smoke_e2e import run_guardrail_smoke, run_smoke_e2e


def test_smoke_e2e_offline_covers_core_application_flow(tmp_path):
    result = run_smoke_e2e(db_path=tmp_path / "smoke.db")

    assert result["passed"] is True
    assert result["mode"] == "offline"
    assert result["processed"]["ranking_worker"] is True
    assert result["processed"]["materials_worker"] is True
    assert result["api"]["ranking_decision"] == "APPLY_NOW"
    assert result["api"]["pipeline_status"] == "shortlisted"
    assert result["api"]["application_status"] == "submitted"
    assert result["evals"]["ranking"]["passed"] is True
    assert result["evals"]["application_materials"]["passed"] is True
    assert result["evals"]["ats_cv"]["passed"] is True
    assert result["judge_results"] == {}


def test_guardrail_smoke_rejects_known_bad_outputs():
    result = run_guardrail_smoke()

    assert result["passed"] is True
    assert result["mode"] == "guardrail_offline"
    assert result["evals"]["ranking"]["rejected_as_expected"] is True
    assert "decision_outside_expected_band:APPLY_NOW" in result["evals"]["ranking"]["issues"]
    assert "apply_now_with_expected_dealbreaker" in result["evals"]["ranking"]["issues"]
    assert result["evals"]["application_materials"]["rejected_as_expected"] is True
    assert any(
        issue.startswith("unsupported_claims:")
        for issue in result["evals"]["application_materials"]["issues"]
    )
    assert result["evals"]["ats_cv"]["rejected_as_expected"] is True
    assert any(issue.startswith("ats_cv_contains_internal_notes:") for issue in result["evals"]["ats_cv"]["issues"])
