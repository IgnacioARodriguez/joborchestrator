from joborchestrator.intelligence.cv_job_analysis import build_cv_job_analysis


def test_cv_job_analysis_contains_source_backed_candidate_narrative():
    analysis = build_cv_job_analysis(
        {
            "job": {"title": "Backend Engineer"},
            "ranking": {
                "evidence": {
                    "strong_matches": ["Python"],
                    "partial_matches": ["AWS"],
                    "missing_requirements": ["Kubernetes"],
                }
            },
            "ats_fit_analysis": {"supported_keywords": ["Python", "AWS"]},
        }
    )

    narrative = analysis["candidate_narrative"]
    assert "Backend Engineer" in narrative["professional_identity"]
    assert "Python" in narrative["target_relevance"]
    assert narrative["limitations"] == ["Kubernetes"]
    assert narrative["source_evidence"] == ["Python", "AWS"]
