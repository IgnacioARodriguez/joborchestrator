from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from joborchestrator.ranking.schemas import VALID_DECISIONS


@dataclass(slots=True)
class SemanticEvalResult:
    passed: bool
    score: int
    issues: list[str]
    metrics: dict[str, Any]


def evaluate_application_materials(case: dict[str, Any], materials: Any) -> SemanticEvalResult:
    payload = _to_dict(materials)
    expectations = case.get("materials_expectations") or {}
    candidate = case.get("candidate") or {}
    job = case.get("job") or {}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    required_fields = expectations.get("required_fields") or ["recruiter_message", "ats_cv_text", "autofill_notes"]
    missing_fields = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing_fields:
        issues.append(f"missing_required_fields:{','.join(missing_fields)}")

    full_text = _joined_text(payload)
    normalized_full_text = _normalize(full_text)

    forbidden_claims = candidate.get("forbidden_claims") or expectations.get("forbidden_claims") or []
    unsupported_claims = [term for term in forbidden_claims if _contains_phrase(normalized_full_text, term)]
    if unsupported_claims:
        issues.append(f"unsupported_claims:{','.join(unsupported_claims)}")
    metrics["unsupported_claims"] = unsupported_claims

    required_terms = expectations.get("required_terms") or []
    missing_required_terms = [term for term in required_terms if not _contains_phrase(normalized_full_text, term)]
    if missing_required_terms:
        issues.append(f"missing_required_terms:{','.join(missing_required_terms)}")
    metrics["missing_required_terms"] = missing_required_terms

    base_experience_terms = candidate.get("required_experience_terms") or []
    ats_cv_text = str(payload.get("ats_cv_text") or "")
    normalized_ats_cv = _normalize(ats_cv_text)
    omitted_experiences = [term for term in base_experience_terms if not _contains_phrase(normalized_ats_cv, term)]
    if omitted_experiences:
        issues.append(f"omitted_base_experience:{','.join(omitted_experiences)}")
    metrics["omitted_base_experience"] = omitted_experiences

    recruiter_message = str(payload.get("recruiter_message") or "").strip()
    max_recruiter_chars = int(expectations.get("max_recruiter_message_chars") or 320)
    metrics["recruiter_message_chars"] = len(recruiter_message)
    if len(recruiter_message) > max_recruiter_chars:
        issues.append(f"recruiter_message_too_long:{len(recruiter_message)}>{max_recruiter_chars}")

    cover_letter_markers = _cover_letter_markers(recruiter_message)
    if cover_letter_markers:
        issues.append(f"recruiter_message_cover_letter_style:{','.join(cover_letter_markers)}")
    metrics["recruiter_message_cover_letter_markers"] = cover_letter_markers

    specificity_terms = expectations.get("specificity_terms") or [job.get("company"), job.get("title")]
    matched_specificity = [term for term in specificity_terms if term and _contains_phrase(normalized_full_text, str(term))]
    if specificity_terms and not matched_specificity:
        issues.append("missing_job_specificity")
    metrics["matched_specificity_terms"] = matched_specificity

    return _result(issues, metrics)


def evaluate_ranking_result(case: dict[str, Any], ranking: Any) -> SemanticEvalResult:
    payload = _to_dict(ranking)
    expectations = case.get("ranking_expectations") or {}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    decision = str(payload.get("decision") or "").strip()
    final_score = _int_or_none(payload.get("final_score"))
    metrics["decision"] = decision
    metrics["final_score"] = final_score

    if decision not in VALID_DECISIONS:
        issues.append(f"invalid_decision:{decision}")

    allowed_decisions = expectations.get("allowed_decisions") or []
    if allowed_decisions and decision not in allowed_decisions:
        issues.append(f"decision_outside_expected_band:{decision}")

    min_score = expectations.get("min_score")
    max_score = expectations.get("max_score")
    if min_score is not None and (final_score is None or final_score < int(min_score)):
        issues.append(f"score_below_expected:{final_score}<{min_score}")
    if max_score is not None and (final_score is None or final_score > int(max_score)):
        issues.append(f"score_above_expected:{final_score}>{max_score}")

    evidence_text = _ranking_evidence_text(payload)
    normalized_evidence = _normalize(evidence_text)
    required_evidence_terms = expectations.get("required_evidence_terms") or []
    missing_evidence_terms = [
        term for term in required_evidence_terms if not _contains_phrase(normalized_evidence, term)
    ]
    if missing_evidence_terms:
        issues.append(f"missing_evidence_terms:{','.join(missing_evidence_terms)}")
    metrics["missing_evidence_terms"] = missing_evidence_terms

    dealbreaker_terms = expectations.get("dealbreaker_terms") or []
    mentioned_dealbreakers = [term for term in dealbreaker_terms if _contains_phrase(normalized_evidence, term)]
    if dealbreaker_terms and decision == "APPLY_NOW":
        issues.append("apply_now_with_expected_dealbreaker")
    if dealbreaker_terms and not mentioned_dealbreakers:
        issues.append(f"missing_dealbreaker_evidence:{','.join(dealbreaker_terms)}")
    metrics["mentioned_dealbreakers"] = mentioned_dealbreakers

    avoid_overclaiming = payload.get("cv_keywords_to_avoid_overclaiming") or []
    forbidden_claims = (case.get("candidate") or {}).get("forbidden_claims") or []
    unsafe_emphasis = [
        term
        for term in forbidden_claims
        if _contains_phrase(_normalize(" ".join(map(str, payload.get("cv_keywords_to_emphasize") or []))), term)
        and not _contains_phrase(_normalize(" ".join(map(str, avoid_overclaiming))), term)
    ]
    if unsafe_emphasis:
        issues.append(f"unsafe_cv_keyword_emphasis:{','.join(unsafe_emphasis)}")
    metrics["unsafe_cv_keyword_emphasis"] = unsafe_emphasis

    return _result(issues, metrics)


def build_llm_judge_payload(case: dict[str, Any], candidate_output: Any, artifact_type: str) -> dict[str, Any]:
    if artifact_type not in {"application_materials", "ranking"}:
        raise ValueError("artifact_type must be one of: application_materials, ranking")
    return {
        "artifact_type": artifact_type,
        "case_id": case.get("id"),
        "rubric_version": "semantic-eval-v1",
        "rubric": {
            "pass_fail_rules": [
                "Fail if the output invents employers, degrees, certifications, tools, years, or projects not supported by the candidate source.",
                "Fail if a ranking recommends APPLY_NOW despite an explicit central requirement mismatch or dealbreaker.",
                "Fail if evidence does not cite the strongest match and the most important gap for the candidate.",
                "Fail if application materials are generic and do not reference the target company, role, or truthful candidate strengths.",
            ],
            "scores": {
                "faithfulness": "0-100 based on whether claims are supported by candidate data.",
                "job_specificity": "0-100 based on target role/company/requirement specificity.",
                "decision_quality": "0-100 based on ranking decision, score band, and evidence.",
                "actionability": "0-100 based on readiness to apply or clear next steps.",
            },
        },
        "source_case": {
            "job": case.get("job"),
            "candidate": case.get("candidate"),
            "expectations": {
                "materials": case.get("materials_expectations"),
                "ranking": case.get("ranking_expectations"),
            },
        },
        "candidate_output": _to_dict(candidate_output),
        "expected_response_schema": {
            "passed": "boolean",
            "score": "integer 0-100",
            "issues": ["string"],
            "rationale": "short evidence-backed explanation",
        },
    }


def _result(issues: list[str], metrics: dict[str, Any]) -> SemanticEvalResult:
    score = max(0, 100 - (15 * len(issues)))
    return SemanticEvalResult(passed=not issues, score=score, issues=issues, metrics=metrics)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _joined_text(payload: dict[str, Any]) -> str:
    return "\n".join(str(value) for value in payload.values() if value is not None)


def _ranking_evidence_text(payload: dict[str, Any]) -> str:
    fields: list[str] = []
    for key in [
        "reasoning_summary",
        "recommended_application_angle",
        "cv_keywords_to_emphasize",
        "cv_keywords_to_avoid_overclaiming",
    ]:
        fields.append(str(payload.get(key) or ""))
    evidence = payload.get("evidence") or {}
    if is_dataclass(evidence):
        evidence = asdict(evidence)
    if isinstance(evidence, dict):
        fields.extend(str(value) for value in evidence.values())
    return "\n".join(fields)


def _cover_letter_markers(text: str) -> list[str]:
    normalized = _normalize(text)
    markers = [
        "dear hiring manager",
        "dear recruiter",
        "i am writing to express",
        "i'm writing to express",
        "sincerely",
        "best regards",
    ]
    return [marker for marker in markers if marker in normalized]


def _normalize(text: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    return _normalize(phrase) in normalized_text


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
