from __future__ import annotations

import json
import asyncio

import pandas as pd

from joborchestrator.ranking import nvidia_ranker
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MODEL,
    NvidiaRankingError,
    build_nvidia_ranking_payload,
    rank_jobs_with_nvidia_async,
    rank_jobs_with_nvidia,
)


def profile_payload() -> dict:
    return {
        "target_roles": ["Backend Engineer"],
        "role_aliases": {"Backend Engineer": ["API Engineer"]},
        "skills": [{"name": "Python", "category": "Programming", "level": "strong"}],
        "real_experience_years": 4,
    }


def test_build_nvidia_ranking_payload_compacts_jobs(monkeypatch):
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)

    payload = build_nvidia_ranking_payload(
        [
            {
                "id": 7,
                "title": "Backend Engineer",
                "company": "Acme",
                "description_text": "Python APIs " * 1000,
            }
        ]
    )

    assert payload["jobs"][0]["job_id"] == 7
    assert payload["jobs"][0]["title"] == "Backend Engineer"
    assert "[truncated]" in payload["jobs"][0]["description_text"]
    assert "candidate_profile" in payload
    assert payload["candidate_profile"]["strong_skills"] == ["Python"]
    assert payload["candidate_profile"]["role_aliases"] == {"Backend Engineer": ["API Engineer"]}


def test_build_nvidia_ranking_payload_requires_profile(monkeypatch):
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", lambda: None)

    try:
        build_nvidia_ranking_payload([{"id": 1, "title": "Backend Engineer"}])
    except NvidiaRankingError as exc:
        assert "No candidate profile configured" in str(exc)
    else:
        raise AssertionError("Expected NvidiaRankingError")


def test_rank_jobs_with_nvidia_saves_each_ranking(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python FastAPI"},
            {"id": 2, "title": "C++ Engineer", "company": "Widgets", "description_text": "C++ Qt"},
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {
            "rankings": [
                _ranking_payload(1, 82, "APPLY_NOW"),
                _ranking_payload(2, 35, "SKIP"),
            ]
        }

    def fake_save(job_id, ranking):
        saved[job_id] = ranking
        return 1

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", fake_save)

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=2)

    assert summary["processed"] == 2
    assert summary["saved"] == 2
    assert summary["APPLY_NOW"] == 1
    assert summary["SKIP"] == 1
    assert saved[1].final_score == 82
    assert "nvidia_ranking_applied" in saved[1].evidence.llm_escalation_reasons


def test_rank_jobs_with_nvidia_async_runs_batches_concurrently(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"},
            {"id": 2, "title": "API Engineer", "company": "Acme", "description_text": "FastAPI"},
            {"id": 3, "title": "C++ Engineer", "company": "Widgets", "description_text": "C++ Qt"},
        ]
    )
    saved = {}
    active = 0
    max_active = 0

    async def fake_call(batch, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"rankings": [_ranking_payload(int(row["id"]), 80, "APPLY_NOW") for row in batch]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking: saved.setdefault(job_id, ranking))

    summary = asyncio.run(rank_jobs_with_nvidia_async(jobs, request_batch_size=1, max_concurrency=2))

    assert summary["processed"] == 3
    assert summary["saved"] == 3
    assert max_active == 2
    assert set(saved) == {1, 2, 3}


def test_rank_jobs_with_nvidia_reports_progress(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"},
            {"id": 2, "title": "API Engineer", "company": "Acme", "description_text": "FastAPI"},
        ]
    )
    progress_events = []

    async def fake_call(batch, **kwargs):
        await asyncio.sleep(0)
        return {"rankings": [_ranking_payload(int(row["id"]), 80, "APPLY_NOW") for row in batch]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking: 1)

    summary = rank_jobs_with_nvidia(
        jobs,
        request_batch_size=1,
        max_concurrency=2,
        progress_callback=lambda done, total, current: progress_events.append((done, total, current["saved"])),
    )

    assert summary["saved"] == 2
    assert progress_events[-1] == (2, 2, 2)
    assert len(progress_events) == 2


def test_call_nvidia_batch_uses_chat_completions(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"rankings": [_ranking_payload(1, 80, "APPLY_NOW")]})
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(nvidia_ranker.httpx, "post", fake_post)
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)

    payload = nvidia_ranker._call_nvidia_batch(
        [{"id": 1, "title": "Backend Engineer", "description_text": "Python"}],
        model="test-model",
        api_key="nvapi-test",
        base_url="https://integrate.api.nvidia.com/v1",
        timeout=1,
    )

    assert payload["rankings"][0]["job_id"] == 1
    assert calls[0][0] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert calls[0][1]["json"]["model"] == "test-model"
    assert calls[0][1]["json"]["temperature"] == 0
    assert calls[0][1]["json"]["top_p"] == 0.95
    assert calls[0][1]["json"]["frequency_penalty"] == 0
    assert calls[0][1]["json"]["presence_penalty"] == 0
    assert calls[0][1]["json"]["stream"] is False
    assert calls[0][1]["json"]["response_format"] == {"type": "json_object"}


def test_default_nvidia_model_matches_nvidia_snippet():
    assert DEFAULT_NVIDIA_MODEL == "nvidia/llama-3.3-nemotron-super-49b-v1"


def _ranking_payload(job_id: int, score: int, decision: str) -> dict:
    return {
        "job_id": job_id,
        "final_score": score,
        "decision": decision,
        "confidence": 0.88,
        "scores": {
            "technical_fit": score,
            "seniority_fit": score,
            "role_fit": score,
            "opportunity_quality": score,
            "application_roi": score,
            "market_alignment": score,
            "risk_penalty": 5,
            "speed_signal": score,
            "technical_readiness": score,
            "central_requirement_coverage": score,
            "role_confidence": score,
            "application_effort_signal": score,
            "data_quality_signal": 80,
            "source_reliability_signal": 70,
        },
        "evidence": {
            "strong_matches": ["Python"] if decision == "APPLY_NOW" else [],
            "partial_matches": [],
            "missing_requirements": ["Core stack mismatch"] if decision == "SKIP" else [],
            "nice_to_have_matches": [],
            "dealbreakers": [],
            "red_flags": [],
            "central_requirement_coverage": score / 100,
            "central_requirement_raw_coverage": score / 100,
            "central_requirement_evidence_quality": 0.8,
            "requirement_backed_signal_count": 3,
            "central_requirement_thresholds": {},
            "central_requirements": [],
            "requires_llm_review": False,
            "llm_escalation_reasons": [],
        },
        "reasoning_summary": "Test ranking.",
        "recommended_application_angle": "Test angle.",
        "cv_keywords_to_emphasize": ["Python"],
        "cv_keywords_to_avoid_overclaiming": [],
    }
