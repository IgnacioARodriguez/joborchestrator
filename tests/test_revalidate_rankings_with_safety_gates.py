from __future__ import annotations

import json

from scripts import revalidate_rankings_with_safety_gates as revalidate


def test_revalidation_defaults_to_optimistic_decisions(monkeypatch, capsys):
    calls = {}

    def fake_fetch_rows(**kwargs):
        calls["fetch_rows"] = kwargs
        return []

    monkeypatch.setattr(revalidate, "fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(revalidate, "revalidate_rows", lambda rows: ([], []))

    assert revalidate.main(["--ranking-job-id", "9"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert calls["fetch_rows"]["decisions"] == ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]
    assert output["decisions"] == ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]


def test_revalidation_decision_flag_overrides_default(monkeypatch, capsys):
    calls = {}

    def fake_fetch_rows(**kwargs):
        calls["fetch_rows"] = kwargs
        return []

    monkeypatch.setattr(revalidate, "fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(revalidate, "revalidate_rows", lambda rows: ([], []))

    assert revalidate.main(["--ranking-job-id", "9", "--decision", "MAYBE"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert calls["fetch_rows"]["decisions"] == ["MAYBE"]
    assert output["decisions"] == ["MAYBE"]


def test_revalidation_applies_profile_backed_evidence_terms(monkeypatch):
    calls = []
    row = {
        "job_id": 1,
        "title": "Python Developer",
        "company": "Acme",
        "location": "Remote",
        "workplace_type": "remote",
        "description_text": "Python and FastAPI APIs.",
        "data_quality_flags": None,
        "final_score": 85,
        "decision": "APPLY_NOW",
        "confidence": 0.9,
        "scores_json": json.dumps(
            {
                "technical_fit": 85,
                "seniority_fit": 85,
                "role_fit": 85,
                "opportunity_quality": 85,
                "application_roi": 85,
                "market_alignment": 85,
                "risk_penalty": 0,
                "technical_readiness": 85,
                "central_requirement_coverage": 85,
                "role_confidence": 85,
                "application_effort_signal": 85,
                "data_quality_signal": 85,
                "source_reliability_signal": 85,
            }
        ),
        "evidence_json": json.dumps(
            {
                "strong_matches": [],
                "partial_matches": [],
                "missing_requirements": [],
                "nice_to_have_matches": [],
                "dealbreakers": [],
                "red_flags": [],
                "central_requirement_coverage": 0.85,
                "central_requirement_raw_coverage": 0.85,
                "central_requirement_evidence_quality": 0.85,
                "requirement_backed_signal_count": 2,
                "central_requirement_thresholds": {},
                "central_requirements": [],
                "requires_llm_review": False,
                "llm_escalation_reasons": [],
            }
        ),
        "reasoning_summary": "Good fit.",
        "recommended_application_angle": "Apply directly.",
        "cv_keywords_to_emphasize_json": "[]",
        "cv_keywords_to_avoid_overclaiming_json": "[]",
        "ranking_version": revalidate.NVIDIA_RANKING_VERSION,
    }

    safety_context = {"profile_skill_labels": [{"name": "Python", "level": "strong"}]}
    monkeypatch.setattr(revalidate.nvidia_ranker, "_active_profile_safety_context", lambda: safety_context)
    monkeypatch.setattr(revalidate.nvidia_ranker, "_apply_ranking_safety_gate", lambda *args: None)
    monkeypatch.setattr(revalidate.nvidia_ranker, "_apply_evidence_consistency_gate", lambda *args: None)

    def fake_apply(job, ranking, safety_context):
        calls.append((job["job_id"], safety_context))
        ranking.evidence.strong_matches.append("Python")

    monkeypatch.setattr(revalidate.nvidia_ranker, "_apply_profile_backed_evidence_terms", fake_apply)

    changed, unchanged = revalidate.revalidate_rows([row])

    assert not unchanged
    assert changed[0]["job_id"] == 1
    assert calls == [(1, safety_context)]
