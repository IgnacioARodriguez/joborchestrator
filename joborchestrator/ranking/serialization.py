from __future__ import annotations

from dataclasses import asdict

from joborchestrator.ranking.schemas import RankingResult


def result_to_dict(result: RankingResult) -> dict:
    return {
        "final_score": result.final_score,
        "decision": result.decision,
        "confidence": result.confidence,
        "scores": asdict(result.scores),
        "evidence": asdict(result.evidence),
        "reasoning_summary": result.reasoning_summary,
        "recommended_application_angle": result.recommended_application_angle,
        "cv_keywords_to_emphasize": result.cv_keywords_to_emphasize,
        "cv_keywords_to_avoid_overclaiming": result.cv_keywords_to_avoid_overclaiming,
        "ranking_version": result.ranking_version,
    }
