from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from joborchestrator.ranking.manual_llm_review import (
    ManualLLMReviewError,
    build_application_kit_prompt,
    build_manual_batch_review_prompt,
    build_manual_review_prompt,
    manual_review_status,
    parse_application_kit_response,
    parse_manual_batch_review_response,
    parse_manual_review_response,
    ranking_from_storage_row,
)
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION


def baseline() -> RankingResult:
    return RankingResult(
        final_score=45,
        decision="SKIP",
        confidence=0.5,
        scores=RankingScores(
            technical_fit=45,
            seniority_fit=60,
            role_fit=55,
            opportunity_quality=80,
            application_roi=55,
            market_alignment=0,
            risk_penalty=6,
            speed_signal=45,
            technical_readiness=45,
            central_requirement_coverage=34,
            role_confidence=50,
            application_effort_signal=55,
            data_quality_signal=80,
            source_reliability_signal=72,
        ),
        evidence=RankingEvidence(
            strong_matches=["Python"],
            missing_requirements=["Node"],
            central_requirement_coverage=0.34,
            requires_llm_review=True,
            llm_escalation_reasons=["central_requirement_coverage_requires_review"],
        ),
        reasoning_summary="Needs review.",
        recommended_application_angle="Backend angle.",
        cv_keywords_to_emphasize=["Python"],
        cv_keywords_to_avoid_overclaiming=["Node"],
        ranking_version=SPEED_RANKING_VERSION,
    )


def test_parse_manual_review_response_merges_json_fence_with_baseline() -> None:
    response = """
    ```json
    {
      "final_score": 58,
      "decision": "MAYBE",
      "confidence": 0.72,
      "scores": {"technical_fit": 62, "technical_readiness": 62},
      "evidence": {"strong_matches": ["Python", "FastAPI"]},
      "reasoning_summary": "Viable backend-adjacent role.",
      "recommended_application_angle": "Emphasize Python APIs.",
      "cv_keywords_to_emphasize": ["Python", "FastAPI"],
      "cv_keywords_to_avoid_overclaiming": ["Node"]
    }
    ```
    """

    result = parse_manual_review_response(response, baseline())

    assert result.final_score == 58
    assert result.decision == "MAYBE"
    assert result.confidence == 0.72
    assert result.scores.technical_fit == 62
    assert result.scores.seniority_fit == 60
    assert result.evidence.strong_matches == ["Python", "FastAPI"]
    assert result.evidence.requires_llm_review is False
    assert "manual_chatgpt_review_applied" in result.evidence.llm_escalation_reasons
    assert result.ranking_version == SPEED_RANKING_VERSION


def test_parse_manual_review_response_rejects_invalid_decision() -> None:
    with pytest.raises(ManualLLMReviewError):
        parse_manual_review_response('{"decision": "GOOD"}', baseline())


def test_ranking_from_storage_row_roundtrips() -> None:
    base = baseline()
    row = {
        "final_score": base.final_score,
        "decision": base.decision,
        "confidence": base.confidence,
        "scores_json": json.dumps(asdict(base.scores)),
        "evidence_json": json.dumps(asdict(base.evidence)),
        "reasoning_summary": base.reasoning_summary,
        "recommended_application_angle": base.recommended_application_angle,
        "cv_keywords_to_emphasize_json": json.dumps(base.cv_keywords_to_emphasize),
        "cv_keywords_to_avoid_overclaiming_json": json.dumps(base.cv_keywords_to_avoid_overclaiming),
        "ranking_version": base.ranking_version,
    }

    parsed = ranking_from_storage_row(row)

    assert parsed.final_score == base.final_score
    assert parsed.scores.technical_fit == base.scores.technical_fit
    assert parsed.evidence.requires_llm_review is True


def test_build_manual_review_prompt_includes_job_and_current_ranking() -> None:
    prompt = build_manual_review_prompt(
        {"id": 1, "title": "Backend Engineer", "description_text": "Python APIs"},
        baseline(),
    )

    assert "Backend Engineer" in prompt
    assert "current_ranking" in prompt
    assert "Return only valid JSON" in prompt


def test_build_manual_batch_review_prompt_includes_all_job_ids() -> None:
    rows = [
        {"job_id": 1, "title": "Backend Engineer", "description_text": "Python APIs"},
        {"job_id": 2, "title": "C++ Engineer", "description_text": "C++ Qt " * 2000},
    ]
    prompt = build_manual_batch_review_prompt(rows, {1: baseline(), 2: baseline()}, max_description_chars=120)

    assert '"job_id": 1' in prompt
    assert '"job_id": 2' in prompt
    assert "Return one result per input job_id" in prompt
    assert "[truncated]" in prompt


def test_parse_manual_batch_review_response_updates_each_baseline() -> None:
    response = """
    {
      "rankings": [
        {
          "job_id": 1,
          "final_score": 41,
          "decision": "SKIP",
          "confidence": 0.87,
          "scores": {"technical_fit": 44, "technical_readiness": 46},
          "evidence": {"red_flags": ["Dominant central requirements are outside profile"]},
          "reasoning_summary": "IoT and Java/Spring are dominant missing requirements.",
          "recommended_application_angle": "Skip for speed-focused search.",
          "cv_keywords_to_emphasize": ["Python"],
          "cv_keywords_to_avoid_overclaiming": ["IoT", "Java", "Spring Boot"]
        },
        {
          "job_id": 2,
          "final_score": 47,
          "decision": "SKIP",
          "confidence": 0.82,
          "scores": {"technical_fit": 48, "technical_readiness": 49},
          "evidence": {"red_flags": ["C++ and Qt are central"]},
          "reasoning_summary": "C++/Qt role with secondary Python.",
          "recommended_application_angle": "Do not prioritize.",
          "cv_keywords_to_emphasize": ["Python", "AWS"],
          "cv_keywords_to_avoid_overclaiming": ["C++", "Qt"]
        }
      ]
    }
    """

    results = parse_manual_batch_review_response(response, {1: baseline(), 2: baseline()})

    assert set(results) == {1, 2}
    assert results[1].final_score == 41
    assert results[2].final_score == 47
    assert results[1].evidence.requires_llm_review is False
    assert "manual_chatgpt_batch_review_applied" in results[1].evidence.llm_escalation_reasons


def test_parse_manual_batch_review_response_requires_complete_batch() -> None:
    with pytest.raises(ManualLLMReviewError, match="Faltan resultados"):
        parse_manual_batch_review_response(
            '{"rankings":[{"job_id":1,"decision":"SKIP"}]}',
            {1: baseline(), 2: baseline()},
        )


def test_build_application_kit_prompt_includes_material_fields() -> None:
    prompt = build_application_kit_prompt(
        {"id": 1, "title": "Backend Engineer", "description_text": "Python APIs"},
        baseline(),
    )

    assert "recruiter_message" in prompt
    assert "cover_letter" in prompt
    assert "ats_cv_text" in prompt
    assert "autofill_notes" in prompt


def test_parse_application_kit_response_accepts_json_fence() -> None:
    kit = parse_application_kit_response(
        """
        ```json
        {
          "recruiter_message": "Hi recruiter",
          "cover_letter": "Dear team",
          "ats_cv_text": "Python APIs",
          "autofill_notes": "Remote: yes",
          "keywords_to_emphasize": ["Python"],
          "claims_to_avoid": ["Node"]
        }
        ```
        """
    )

    assert kit["recruiter_message"] == "Hi recruiter"
    assert kit["cover_letter"] == "Dear team"
    assert "Python APIs" in kit["ats_cv_text"]
    assert "Keywords to emphasize: Python" in kit["autofill_notes"]
    assert "Claims to avoid: Node" in kit["autofill_notes"]


def test_parse_application_kit_response_requires_core_fields() -> None:
    with pytest.raises(ManualLLMReviewError):
        parse_application_kit_response('{"recruiter_message": "Hi"}')


def test_manual_review_status_maps_reasons_to_user_friendly_text() -> None:
    needs_review, reason = manual_review_status(
        {
            "requires_llm_review": True,
            "llm_escalation_reasons": [
                "central_requirement_coverage_requires_review",
                "role_confidence_below_threshold",
            ],
        }
    )

    assert needs_review is True
    assert "Coverage needs review" in reason
    assert "Low role confidence" in reason


def test_manual_review_status_hides_already_reviewed_items() -> None:
    needs_review, reason = manual_review_status(
        {
            "requires_llm_review": False,
            "llm_escalation_reasons": ["manual_chatgpt_review_applied"],
        }
    )

    assert needs_review is False
    assert reason == "Reviewed"
