from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

from joborchestrator.llm.provider import LLMProviderError, ProviderRegistry
from joborchestrator.prompts import load_prompt
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranking_rules import OPENAI_INSTRUCTIONS
from joborchestrator.ranking.requirements_extractor import extract_requirements
from joborchestrator.ranking.schemas import CandidateProfile, RankingEvidence, RankingResult, RankingScores
from joborchestrator.ranking.versions import OPENAI_RANKING_VERSION_BASE

DEFAULT_LLM_MODEL = os.getenv("OPENAI_RANKING_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"


class LLMRankingError(RuntimeError):
    pass


def llm_ranking_version(model: str | None = None) -> str:
    safe_model = (model or DEFAULT_LLM_MODEL).replace(":", "_").replace("/", "_")
    return f"{OPENAI_RANKING_VERSION_BASE}:{safe_model}"


def rank_job_with_llm(
    job: Any,
    profile: CandidateProfile | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 45.0,
) -> RankingResult:
    profile = profile or load_candidate_profile()
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise LLMRankingError("OPENAI_API_KEY is required to rank jobs with OpenAI.")

    model_name = model or DEFAULT_LLM_MODEL
    requirements = extract_requirements(job)
    payload = {
        "profile": asdict(profile),
        "job": _job_to_dict(job),
        "extracted_requirements": asdict(requirements),
        "instructions": OPENAI_INSTRUCTIONS,
    }
    response = _call_openai_responses(payload, key, model_name, timeout)
    return _ranking_from_payload(response, llm_ranking_version(model_name))


def _call_openai_responses(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    try:
        provider = ProviderRegistry().get("ranking", provider_name="openai", api_key=api_key, timeout=timeout)
        response = provider.complete(
            _ranking_messages(payload),
            model=model,
            response_format="json",
            response_schema=_ranking_json_schema(),
            schema_name="ranking_result",
        )
    except LLMProviderError as exc:
        raise LLMRankingError(f"OpenAI ranking request failed: {exc}") from exc

    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise LLMRankingError("OpenAI ranking response was not valid JSON") from exc


def build_ranking_response_body(payload: dict[str, Any], model: str) -> dict[str, Any]:
    user_content = _response_contract() + "\n\nContext:\n" + json.dumps(payload, ensure_ascii=False)
    return {
        "model": model,
        "store": False,
        "reasoning": {"effort": "low"},
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a strict job-ranking evaluator. Return only the requested structured JSON. "
                    "Score the opportunity for this candidate, not generic attractiveness. "
                    "Use the candidate profile, extracted requirements, and job text as the source of truth."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ranking_result",
                "strict": True,
                "schema": _ranking_json_schema(),
            }
        },
    }


def _ranking_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    user_content = _response_contract() + "\n\nContext:\n" + json.dumps(payload, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "You are a strict job-ranking evaluator. Return only the requested structured JSON. "
                "Score the opportunity for this candidate, not generic attractiveness. "
                "Use the candidate profile, extracted requirements, and job text as the source of truth."
            ),
        },
        {"role": "user", "content": user_content},
    ]


def _response_contract() -> str:
    return load_prompt("ranking", "nvidia_response_contract")


def _extract_response_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return response["output_text"]
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    raise LLMRankingError("OpenAI ranking response did not include text output")


def _ranking_from_payload(payload: dict[str, Any], ranking_version: str) -> RankingResult:
    scores = RankingScores(**payload["scores"])
    evidence = RankingEvidence(**payload["evidence"])
    return RankingResult(
        final_score=payload["final_score"],
        decision=payload["decision"],
        confidence=payload["confidence"],
        scores=scores,
        evidence=evidence,
        reasoning_summary=payload["reasoning_summary"],
        recommended_application_angle=payload["recommended_application_angle"],
        cv_keywords_to_emphasize=payload["cv_keywords_to_emphasize"],
        cv_keywords_to_avoid_overclaiming=payload["cv_keywords_to_avoid_overclaiming"],
        ranking_version=ranking_version,
    )


def _job_to_dict(job: Any) -> dict[str, Any]:
    if isinstance(job, dict):
        return job
    if is_dataclass(job):
        return asdict(job)
    if hasattr(job, "to_dict"):
        return job.to_dict()
    if hasattr(job, "__dict__"):
        return vars(job)
    return {}


def _ranking_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "final_score",
            "decision",
            "confidence",
            "scores",
            "evidence",
            "reasoning_summary",
            "recommended_application_angle",
            "cv_keywords_to_emphasize",
            "cv_keywords_to_avoid_overclaiming",
        ],
        "properties": {
            "final_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "decision": {
                "type": "string",
                "enum": ["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "technical_fit",
                    "seniority_fit",
                    "role_fit",
                    "opportunity_quality",
                    "application_roi",
                    "market_alignment",
                    "risk_penalty",
                    "technical_readiness",
                    "central_requirement_coverage",
                    "role_confidence",
                    "application_effort_signal",
                    "data_quality_signal",
                    "source_reliability_signal",
                ],
                "properties": {
                    "technical_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "seniority_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "role_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "opportunity_quality": {"type": "integer", "minimum": 0, "maximum": 100},
                    "application_roi": {"type": "integer", "minimum": 0, "maximum": 100},
                    "market_alignment": {"type": "integer", "minimum": 0, "maximum": 100},
                    "risk_penalty": {"type": "integer", "minimum": 0, "maximum": 40},
                    "technical_readiness": {"type": "number", "minimum": 0, "maximum": 100},
                    "central_requirement_coverage": {"type": "number", "minimum": 0, "maximum": 100},
                    "role_confidence": {"type": "number", "minimum": 0, "maximum": 100},
                    "application_effort_signal": {"type": "number", "minimum": 0, "maximum": 100},
                    "data_quality_signal": {"type": "number", "minimum": 0, "maximum": 100},
                    "source_reliability_signal": {"type": "number", "minimum": 0, "maximum": 100},
                },
            },
            "evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "strong_matches",
                    "partial_matches",
                    "missing_requirements",
                    "nice_to_have_matches",
                    "dealbreakers",
                    "red_flags",
                    "central_requirement_coverage",
                    "central_requirement_raw_coverage",
                    "central_requirement_evidence_quality",
                    "requirement_backed_signal_count",
                    "central_requirement_thresholds",
                    "central_requirements",
                    "requires_llm_review",
                    "llm_escalation_reasons",
                ],
                "properties": {
                    "strong_matches": {"type": "array", "items": {"type": "string"}},
                    "partial_matches": {"type": "array", "items": {"type": "string"}},
                    "missing_requirements": {"type": "array", "items": {"type": "string"}},
                    "nice_to_have_matches": {"type": "array", "items": {"type": "string"}},
                    "dealbreakers": {"type": "array", "items": {"type": "string"}},
                    "red_flags": {"type": "array", "items": {"type": "string"}},
                    "central_requirement_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "central_requirement_raw_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "central_requirement_evidence_quality": {"type": "number", "minimum": 0, "maximum": 1},
                    "requirement_backed_signal_count": {"type": "integer", "minimum": 0},
                    "central_requirement_thresholds": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                    },
                    "central_requirements": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "requires_llm_review": {"type": "boolean"},
                    "llm_escalation_reasons": {"type": "array", "items": {"type": "string"}},
                },
            },
            "reasoning_summary": {"type": "string"},
            "recommended_application_angle": {"type": "string"},
            "cv_keywords_to_emphasize": {"type": "array", "items": {"type": "string"}},
            "cv_keywords_to_avoid_overclaiming": {"type": "array", "items": {"type": "string"}},
        },
    }
