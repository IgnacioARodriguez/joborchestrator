from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

import httpx

from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranker import RANKING_VERSION, rank_job, result_to_dict
from joborchestrator.ranking.requirements_extractor import extract_requirements
from joborchestrator.ranking.schemas import CandidateProfile, RankingEvidence, RankingResult, RankingScores

DEFAULT_LLM_MODEL = os.getenv("OPENAI_RANKING_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"


class LLMRankingError(RuntimeError):
    pass


def llm_ranking_version(model: str | None = None) -> str:
    safe_model = (model or DEFAULT_LLM_MODEL).replace(":", "_").replace("/", "_")
    return f"{RANKING_VERSION}+llm:{safe_model}"


def rank_job_with_llm(
    job: Any,
    profile: CandidateProfile | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 45.0,
) -> RankingResult:
    profile = profile or load_candidate_profile()
    heuristic = rank_job(job, profile)
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return heuristic

    model_name = model or DEFAULT_LLM_MODEL
    requirements = extract_requirements(job)
    payload = {
        "profile": asdict(profile),
        "job": _job_to_dict(job),
        "extracted_requirements": asdict(requirements),
        "heuristic_ranking": result_to_dict(heuristic),
        "instructions": {
            "goal": "Improve the ranking by reading nuanced job context while preserving explainability.",
            "adjacent_roles_rule": "Adjacent, translated or industry-specific role labels are viable when the job text supports transfer from the candidate profile.",
            "role_aliases": "Treat role_aliases as equivalent labels for user-defined roles, not as extra candidate skills.",
            "safety": "Do not invent candidate skills. Mark uncertain or adjacent skills as partial matches.",
        },
    }
    try:
        response = _call_openai_responses(payload, key, model_name, timeout)
        result = _ranking_from_payload(response, llm_ranking_version(model_name))
        return _apply_guards(result, job)
    except LLMRankingError:
        return heuristic


def _call_openai_responses(payload: dict[str, Any], api_key: str, model: str, timeout: float) -> dict[str, Any]:
    request_body = build_ranking_response_body(payload, model)
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMRankingError(f"OpenAI ranking request failed: {exc}") from exc

    text = _extract_response_text(response.json())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMRankingError("OpenAI ranking response was not valid JSON") from exc


def build_ranking_response_body(payload: dict[str, Any], model: str) -> dict[str, Any]:
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
                    "Use the heuristic ranking as a baseline, but correct it when the job text supports a better conclusion."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
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


def _apply_guards(result: RankingResult, job: Any | None = None) -> RankingResult:
    flags = [*(result.evidence.dealbreakers or []), *(result.evidence.red_flags or [])]
    joined = " ".join(flag.lower() for flag in flags)
    if "unpaid" in joined or "commission-only" in joined or "commission only" in joined:
        result.decision = "AVOID"
        result.final_score = min(result.final_score, 25)
    elif any(term in joined for term in ["relocation", "visa", "manual qa"]):
        result.decision = _cap_decision(result.decision, "SKIP")
        result.final_score = min(result.final_score, 45)
    if result.scores.technical_fit < 40:
        result.decision = _cap_decision(result.decision, "APPLY_WITH_TAILORED_CV")
    if result.scores.seniority_fit < 35 or result.scores.role_fit < 35:
        result.decision = _cap_decision(result.decision, "MAYBE")
    if job is not None:
        data = _job_to_dict(job)
        parse_confidence = data.get("parse_confidence")
        if parse_confidence is not None:
            confidence = float(parse_confidence)
            if confidence < 0.5:
                result.decision = _cap_decision(result.decision, "MAYBE")
                result.final_score = min(result.final_score, 64)
            elif confidence < 0.65:
                result.decision = _cap_decision(result.decision, "APPLY_WITH_TAILORED_CV")
                result.final_score = min(result.final_score, 79)
    return result


def _cap_decision(decision: str, max_decision: str) -> str:
    order = ["AVOID", "SKIP", "MAYBE", "APPLY_WITH_TAILORED_CV", "APPLY_NOW"]
    return order[min(order.index(decision), order.index(max_decision))]


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
                ],
                "properties": {
                    "technical_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "seniority_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "role_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "opportunity_quality": {"type": "integer", "minimum": 0, "maximum": 100},
                    "application_roi": {"type": "integer", "minimum": 0, "maximum": 100},
                    "market_alignment": {"type": "integer", "minimum": 0, "maximum": 100},
                    "risk_penalty": {"type": "integer", "minimum": 0, "maximum": 40},
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
                ],
                "properties": {
                    "strong_matches": {"type": "array", "items": {"type": "string"}},
                    "partial_matches": {"type": "array", "items": {"type": "string"}},
                    "missing_requirements": {"type": "array", "items": {"type": "string"}},
                    "nice_to_have_matches": {"type": "array", "items": {"type": "string"}},
                    "dealbreakers": {"type": "array", "items": {"type": "string"}},
                    "red_flags": {"type": "array", "items": {"type": "string"}},
                },
            },
            "reasoning_summary": {"type": "string"},
            "recommended_application_angle": {"type": "string"},
            "cv_keywords_to_emphasize": {"type": "array", "items": {"type": "string"}},
            "cv_keywords_to_avoid_overclaiming": {"type": "array", "items": {"type": "string"}},
        },
    }
