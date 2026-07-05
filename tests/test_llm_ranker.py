from joborchestrator.ranking import llm_ranker
from joborchestrator.ranking.llm_ranker import llm_ranking_version, rank_job_with_llm
from joborchestrator.ranking.ranker import RANKING_VERSION


def make_job():
    return {
        "id": 1,
        "title": "Solutions Engineer",
        "company": "Acme",
        "source": "greenhouse",
        "location": "Spain remote",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
        "description_text": "Requirements: APIs, integrations, Python, technical consulting. Responsibilities: customer demos and implementation.",
    }


def test_llm_ranking_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = rank_job_with_llm(make_job(), model="test-model")

    assert result.ranking_version == RANKING_VERSION
    assert 0 <= result.final_score <= 100


def test_llm_ranking_uses_structured_payload(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_call(payload, api_key, model, timeout):
        assert payload["heuristic_ranking"]
        return {
            "final_score": 78,
            "decision": "APPLY_WITH_TAILORED_CV",
            "confidence": 0.82,
            "scores": {
                "technical_fit": 74,
                "seniority_fit": 80,
                "role_fit": 72,
                "opportunity_quality": 75,
                "application_roi": 78,
                "market_alignment": 76,
                "risk_penalty": 4,
            },
            "evidence": {
                "strong_matches": ["Python", "APIs"],
                "partial_matches": ["Pre-sales: adjacent customer-facing route"],
                "missing_requirements": [],
                "nice_to_have_matches": [],
                "dealbreakers": [],
                "red_flags": ["No salary range"],
            },
            "reasoning_summary": "Technical pre-sales role with relevant API and integration overlap.",
            "recommended_application_angle": "Position as developer with customer-facing implementation experience.",
            "cv_keywords_to_emphasize": ["Python", "APIs", "Integrations"],
            "cv_keywords_to_avoid_overclaiming": ["Quota ownership"],
        }

    monkeypatch.setattr(llm_ranker, "_call_openai_responses", fake_call)

    result = rank_job_with_llm(make_job(), model="test-model")

    assert result.ranking_version == llm_ranking_version("test-model")
    assert result.final_score == 78
    assert result.decision == "APPLY_WITH_TAILORED_CV"
    assert "APIs" in result.evidence.strong_matches
