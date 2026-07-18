from __future__ import annotations

from scripts.smoke_e2e import run_smoke_e2e


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
