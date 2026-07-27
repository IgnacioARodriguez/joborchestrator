from argparse import Namespace

import pandas as pd

from scripts import run_llm_eval_baseline as baseline


def test_llm_eval_baseline_builds_materials_case_with_ranking_constraints(monkeypatch):
    row = {
        "job_id": 105,
        "title": "AWS Backend Developer",
        "company": "PSS",
        "location": "Remote",
        "description_text": "Build AWS serverless architecture APIs with Python.",
        "final_score": 78,
        "decision": "APPLY_WITH_TAILORED_CV",
        "confidence": 0.9,
        "scores_json": "{}",
        "evidence_json": "{}",
        "reasoning_summary": "AWS and Python fit, but avoid overstating serverless.",
        "recommended_application_angle": "Lead with AWS APIs.",
        "cv_keywords_to_emphasize_json": '["AWS", "Python"]',
        "cv_keywords_to_avoid_overclaiming_json": '["Serverless Architecture"]',
        "recruiter_message": "Hi PSS, AWS and Python API work fits this role.",
        "cover_letter": "AWS Backend Developer fit through Python APIs.",
        "ats_cv_text": (
            "Professional Summary\nAWS Python API backend developer.\n"
            "Skills\nAWS, Python, API\n"
            "Experience\nBuilt Python APIs on AWS.\n"
            "Delivered backend services, integrations, data workflows, and application support for product teams. "
            "Improved reliability through clear debugging, API design, SQL-backed workflows, and operational handoff. "
            "Collaborated with stakeholders to define requirements, ship maintainable features, and document delivery. "
            "Supported production fixes, data validation, and automation for recurring business processes. "
            "Education\nRelevant coursework in software engineering and backend systems."
        ),
        "autofill_notes": "Mention AWS and Python APIs.",
    }
    monkeypatch.setattr(
        baseline.db,
        "get_candidate_profile_payload",
        lambda: {
            "base_cv_text": "Experience\nPython APIs on AWS.",
            "skills": [
                {"name": "AWS", "level": "strong"},
                {"name": "Serverless", "level": "medium"},
                {"name": "Python", "level": "strong"},
                {"name": "API", "level": "strong"},
            ],
        },
    )
    monkeypatch.setattr(baseline.db, "get_ranked_jobs", lambda **kwargs: pd.DataFrame([row]))
    captured = {}
    original_evaluate_ats_cv_result = baseline.evaluate_ats_cv_result

    def fake_evaluate_ats_cv_result(case, output):
        captured["case"] = case
        return original_evaluate_ats_cv_result(case, output)

    monkeypatch.setattr(baseline, "evaluate_ats_cv_result", fake_evaluate_ats_cv_result)

    summary = baseline.run_baseline(
        Namespace(
            ranking_version="ranking-test",
            min_score=None,
            limit=1,
            artifact="ats_cv",
            include_records=True,
            save_db=False,
            provider="baseline",
            model="deterministic",
            notes=None,
        )
    )

    assert summary["evaluated"] == 1
    assert captured["case"]["ats_cv_expectations"]["required_keywords"] == [
        "AWS",
        "Python",
        "API",
    ]
    assert not any("Serverless" in issue for issue in summary["records"][0]["issues"])
