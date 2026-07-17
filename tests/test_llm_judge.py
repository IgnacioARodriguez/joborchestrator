from __future__ import annotations

import json

from joborchestrator.evals import llm_judge
from joborchestrator.evals.llm_judge import LLMJudgeError, judge_with_nvidia, judge_with_openai


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
        "issues",
        "rationale",
    ]


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
