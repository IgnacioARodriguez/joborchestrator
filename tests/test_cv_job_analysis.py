from joborchestrator.intelligence.cv_job_analysis import build_cv_job_analysis
from joborchestrator.intelligence.materials_context import build_generation_context


def test_cv_job_analysis_is_cv_specific_and_does_not_expose_ranking_score():
    payload = {
        "job": {"title": "Backend Engineer", "company": "Acme", "description_text": "Python AWS"},
        "ranking": {
            "score": 82,
            "decision": "APPLY",
            "recommended_application_angle": "Backend delivery",
            "evidence": {"central_requirements": ["Python"], "strong_matches": ["Python"]},
        },
        "ats_fit_analysis": {"supported_keywords": ["Python"], "adjacent_or_review_keywords": []},
    }

    analysis = build_cv_job_analysis(payload)

    assert analysis["target_role"] == "Backend Engineer"
    assert analysis["core_requirements"] == ["Python"]
    assert "score" not in analysis
    assert "decision" not in analysis


def test_formal_generation_context_always_includes_cv_job_analysis():
    context = build_generation_context({"job": {"title": "Backend Engineer"}})

    assert "cv_job_analysis" in context
    assert context["cv_job_analysis"]["target_role"] == "Backend Engineer"
