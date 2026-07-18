from __future__ import annotations

import json

from joborchestrator.evals import llm_judge
from joborchestrator.evals.llm_judge import (
    LLMJudgeError,
    judge_with_configured_providers,
    judge_with_nvidia,
    judge_with_openai,
)


def test_openai_judge_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        judge_with_openai({"case_id": "case-1"})
    except LLMJudgeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected LLMJudgeError")


def test_openai_judge_parses_structured_result(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output_text": json.dumps(
                    {
                        "passed": True,
                        "score": 91,
                        "issues": [],
                        "rationale": "Evidence supports the decision.",
                    }
                )
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(llm_judge.httpx, "post", fake_post)

    result = judge_with_openai({"case_id": "case-1"}, api_key="test-key", model="judge-test")

    assert result["passed"] is True
    assert result["score"] == 91
    assert result["issues"] == []
    assert calls[0][0] == "https://api.openai.com/v1/responses"
    assert calls[0][1]["json"]["model"] == "judge-test"
    assert calls[0][1]["json"]["text"]["format"]["schema"]["required"] == [
        "passed",
        "score",
        "issue_codes",
        "issues",
        "rationale",
    ]
    assert "unsupported_claims" in calls[0][1]["json"]["text"]["format"]["schema"]["properties"]["issue_codes"]["items"]["enum"]


def test_nvidia_judge_parses_json_object_content(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "passed": False,
                                    "score": 42,
                                    "issues": ["invented certification"],
                                    "rationale": "The output invents an unsupported claim.",
                                }
                            )
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(llm_judge.httpx, "post", fake_post)

    result = judge_with_nvidia({"case_id": "case-1"}, api_key="nvapi-test", model="judge-nv")

    assert result["passed"] is False
    assert result["score"] == 42
    assert result["issues"] == ["invented certification"]
    assert calls[0][0].endswith("/chat/completions")
    assert calls[0][1]["json"]["model"] == "judge-nv"


def test_configured_judge_marks_provider_disagreement_as_disputed(monkeypatch):
    def fake_judge(payload, *, provider=None, model=None, timeout=None):
        return {
            "passed": provider == "openai",
            "score": 90 if provider == "openai" else 40,
            "issues": [] if provider == "openai" else ["missing_evidence"],
            "rationale": f"{provider} rationale",
        }

    monkeypatch.setattr(llm_judge, "judge_with_provider", fake_judge)

    result = judge_with_configured_providers(
        {"case_id": "case-1"},
        provider="openai",
        secondary_provider="nvidia",
    )

    assert result["passed"] is False
    assert result["disputed"] is True
    assert result["judge_provider"] == "openai"
    assert result["secondary_judge_provider"] == "nvidia"
    assert result["issue_codes"] == ["judge_disputed"]
    assert "judge_disputed" in result["issues"]


def test_configured_judge_allows_same_provider_with_distinct_models(monkeypatch):
    calls = []

    def fake_judge(payload, *, provider=None, model=None, timeout=None):
        calls.append((provider, model))
        return {
            "passed": model == "nvidia-primary",
            "score": 90 if model == "nvidia-primary" else 40,
            "issues": [] if model == "nvidia-primary" else ["missing_evidence"],
            "rationale": f"{provider}/{model} rationale",
        }

    monkeypatch.setattr(llm_judge, "judge_with_provider", fake_judge)

    result = judge_with_configured_providers(
        {"case_id": "case-1"},
        provider="nvidia",
        model="nvidia-primary",
        secondary_provider="nvidia",
        secondary_model="nvidia-secondary",
    )

    assert calls == [("nvidia", "nvidia-primary"), ("nvidia", "nvidia-secondary")]
    assert result["disputed"] is True
    assert result["secondary_crosscheck_kind"] == "model_crosscheck"
    assert result["secondary_judge_model"] == "nvidia-secondary"


def test_configured_judge_skips_same_provider_and_model(monkeypatch):
    calls = []

    def fake_judge(payload, *, provider=None, model=None, timeout=None):
        calls.append((provider, model))
        return {"passed": True, "score": 95, "issues": [], "rationale": "ok"}

    monkeypatch.setattr(llm_judge, "judge_with_provider", fake_judge)

    result = judge_with_configured_providers(
        {"case_id": "case-1"},
        provider="nvidia",
        model="same-model",
        secondary_provider="nvidia",
        secondary_model="same-model",
    )

    assert calls == [("nvidia", "same-model")]
    assert result["disputed"] is False
    assert result["secondary_judge_skipped"] == "same_provider_and_model"


def test_judge_normalization_merges_issue_codes_into_issues():
    result = llm_judge._normalize_judge_result(
        {
            "passed": False,
            "score": 45,
            "issue_codes": ["unsupported_claims", "unknown-new-thing"],
            "issues": ["Invented an AWS certification."],
            "rationale": "Unsupported claim.",
        }
    )

    assert result["issue_codes"] == ["unsupported_claims", "judge_other"]
    assert "Invented an AWS certification." in result["issues"]
    assert "unsupported_claims" in result["issues"]
    assert "judge_other" in result["issues"]


def test_judge_messages_use_versioned_prompt():
    messages = llm_judge._judge_messages({"case_id": "case-1"})

    assert "calibrated evaluator" in messages[0]["content"]
    assert '"case_id": "case-1"' in messages[1]["content"]
