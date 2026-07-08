from __future__ import annotations

import json

import pandas as pd

from joborchestrator.ranking import openai_batch
from joborchestrator.ranking.openai_batch import (
    create_ranking_batch_jsonl,
    import_ranking_batch_output,
    submit_ranking_batch,
)
from joborchestrator.ranking.llm_ranker import llm_ranking_version


def test_create_ranking_batch_jsonl_uses_responses_endpoint(tmp_path):
    jobs = pd.DataFrame(
        [
            {
                "id": 123,
                "title": "Backend Engineer",
                "company": "Acme",
                "description_text": "Python APIs " * 1000,
            }
        ]
    )

    path = create_ranking_batch_jsonl(jobs, model="gpt-5.4-mini", output_dir=tmp_path, max_description_chars=120)
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert line["custom_id"] == "job_ranking_123"
    assert line["method"] == "POST"
    assert line["url"] == "/v1/responses"
    assert line["body"]["model"] == "gpt-5.4-mini"
    assert "[truncated]" in line["body"]["input"][1]["content"]


def test_submit_ranking_batch_uploads_file_and_creates_batch(tmp_path, monkeypatch):
    jsonl_path = tmp_path / "batch.jsonl"
    jsonl_path.write_text('{"custom_id":"job_ranking_1"}\n', encoding="utf-8")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/files"):
            return FakeResponse({"id": "file_123"})
        return FakeResponse({"id": "batch_123", "status": "validating", "input_file_id": "file_123"})

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_batch.httpx, "post", fake_post)
    monkeypatch.setattr(openai_batch, "_write_batch_metadata", lambda metadata: None)

    metadata = submit_ranking_batch(jsonl_path)

    assert metadata["id"] == "batch_123"
    assert calls[0][0].endswith("/files")
    assert calls[0][1]["data"]["purpose"] == "batch"
    assert calls[1][0].endswith("/batches")
    assert calls[1][1]["json"]["endpoint"] == "/v1/responses"
    assert calls[1][1]["json"]["completion_window"] == "24h"


def test_import_ranking_batch_output_saves_rankings(monkeypatch):
    saved = {}

    def fake_save(job_id, ranking):
        saved[job_id] = ranking
        return 1

    monkeypatch.setattr(openai_batch.db, "save_job_ranking", fake_save)
    monkeypatch.setattr(openai_batch.db, "get_job_posting", lambda job_id: {"id": job_id})

    ranking_payload = {
        "final_score": 81,
        "decision": "APPLY_NOW",
        "confidence": 0.9,
        "scores": {
            "technical_fit": 82,
            "seniority_fit": 75,
            "role_fit": 80,
            "opportunity_quality": 70,
            "application_roi": 85,
            "market_alignment": 70,
            "risk_penalty": 2,
        },
        "evidence": {
            "strong_matches": ["Python", "FastAPI"],
            "partial_matches": [],
            "missing_requirements": [],
            "nice_to_have_matches": [],
            "dealbreakers": [],
            "red_flags": [],
        },
        "reasoning_summary": "Strong backend fit.",
        "recommended_application_angle": "Emphasize Python APIs.",
        "cv_keywords_to_emphasize": ["Python", "FastAPI"],
        "cv_keywords_to_avoid_overclaiming": [],
    }
    output_line = {
        "custom_id": "job_ranking_123",
        "response": {
            "status_code": 200,
            "body": {"output_text": json.dumps(ranking_payload)},
        },
    }

    summary = import_ranking_batch_output(json.dumps(output_line))

    assert summary["processed"] == 1
    assert summary["saved"] == 1
    assert summary["APPLY_NOW"] == 1
    assert saved[123].final_score == 81
    assert saved[123].ranking_version == llm_ranking_version(openai_batch.DEFAULT_LLM_MODEL)
    assert "openai_batch_ranking_applied" in saved[123].evidence.llm_escalation_reasons
