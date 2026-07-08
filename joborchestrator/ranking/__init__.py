"""Structured opportunity ranking engine."""

from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranker import rank_job, rank_jobs
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.ranking.schemas import (
    CandidateProfile,
    JobRequirements,
    RankingEvidence,
    RankingResult,
    RankingScores,
)

__all__ = [
    "CandidateProfile",
    "JobRequirements",
    "RankingEvidence",
    "RankingResult",
    "RankingScores",
    "load_candidate_profile",
    "rank_job",
    "rank_jobs",
    "NVIDIA_RANKING_VERSION",
]
