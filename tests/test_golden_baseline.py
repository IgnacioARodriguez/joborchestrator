from argparse import Namespace
import json

from scripts import run_golden_baseline as baseline
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
from joborchestrator.scanning.models import JobPosting
from joborchestrator.storage import persistence as db


def test_golden_baseline_evaluates_persisted_ranking(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "golden-baseline.db")
    db.init_db()
    job_id = _save_job("Backend Engineer", "Acme Labs", "Build Python FastAPI APIs with PostgreSQL.")
    db.save_job_ranking(
        job_id,
        _ranking(
            score=82,
            decision="APPLY_NOW",
            evidence=RankingEvidence(strong_matches=["Python", "FastAPI", "PostgreSQL"]),
        ),
    )
    fixture_dir = tmp_path / "golden"
    fixture_dir.mkdir()
    (fixture_dir / "ranking.json").write_text(
        json.dumps(
            {
                "case_id": "ranking-acme-backend",
                "surface": "ranking",
                "review_status": "reviewed",
                "critical": True,
                "source": {"job_id": job_id},
                "raw_input": {
                    "title": "Backend Engineer",
                    "company": "Acme Labs",
                    "job_html_or_text": "Build Python FastAPI APIs with PostgreSQL.",
                },
                "candidate_profile_snapshot": {
                    "profile": {
                        "base_cv_text": "Backend engineer with Python, FastAPI and PostgreSQL.",
                        "skills": [
                            {"name": "Python", "level": "strong"},
                            {"name": "FastAPI", "level": "strong"},
                            {"name": "PostgreSQL", "level": "strong"},
                        ],
                    }
                },
                "expected": {
                    "allowed_decisions": ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"],
                    "min_score": 70,
                    "required_evidence_terms": ["Python", "FastAPI"],
                },
            }
        ),
        encoding="utf-8",
    )

    summary = baseline.run_golden_baseline(_args(fixture_dir))

    assert summary["fixtures"] == 1
    assert summary["evaluated"] == 1
    assert summary["passed"] == 1
    assert summary["failed"] == 0
    assert summary["critical_failures"] == 0
    assert summary["by_surface"]["ranking"] == {"evaluated": 1, "passed": 1, "failed": 0}


def test_golden_baseline_counts_critical_failures_and_skips_missing_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "golden-baseline.db")
    db.init_db()
    job_id = _save_job("Rust Kernel Engineer", "LowLevel Systems", "Requires Rust kernel and device drivers.")
    db.save_job_ranking(
        job_id,
        _ranking(
            score=92,
            decision="APPLY_NOW",
            evidence=RankingEvidence(strong_matches=["engineering"], dealbreakers=[]),
        ),
    )
    fixture_dir = tmp_path / "golden"
    fixture_dir.mkdir()
    (fixture_dir / "ranking.json").write_text(
        json.dumps(
            {
                "case_id": "ranking-rust-kernel",
                "surface": "ranking",
                "review_status": "reviewed",
                "critical": True,
                "source": {"job_id": job_id},
                "raw_input": {
                    "title": "Rust Kernel Engineer",
                    "company": "LowLevel Systems",
                    "job_html_or_text": "Requires Rust kernel and device drivers.",
                },
                "candidate_profile_snapshot": {
                    "profile": {
                        "base_cv_text": "Backend engineer with Python and FastAPI.",
                        "skills": [{"name": "Python", "level": "strong"}],
                    }
                },
                "expected": {
                    "allowed_decisions": ["MAYBE", "SKIP", "AVOID"],
                    "max_score": 55,
                    "dealbreaker_terms": ["Rust kernel"],
                },
            }
        ),
        encoding="utf-8",
    )
    (fixture_dir / "missing.json").write_text(
        json.dumps(
            {
                "case_id": "ranking-missing",
                "surface": "ranking",
                "review_status": "reviewed",
                "source": {"job_id": 999},
                "raw_input": {"title": "Missing", "company": "Missing", "job_html_or_text": "Missing"},
                "expected": {},
            }
        ),
        encoding="utf-8",
    )

    summary = baseline.run_golden_baseline(_args(fixture_dir, include_records=True))

    assert summary["fixtures"] == 2
    assert summary["evaluated"] == 1
    assert summary["failed"] == 1
    assert summary["critical_failures"] == 1
    assert summary["issue_counts"]["decision_outside_expected_band"] == 1
    assert summary["skipped"] == [{"case_id": "ranking-missing", "reason": "no stored ranking for job_id=999"}]
    assert summary["records"][0]["case_id"] == "ranking-rust-kernel"


def _args(fixture_dir, include_records=False):
    return Namespace(
        golden_cases=fixture_dir,
        ranking_version="ranking_v1.1.0-nvidia",
        artifact="all",
        include_records=include_records,
        save_db=False,
        fail_on_issues=False,
        provider="golden-baseline",
        model="deterministic",
        notes=None,
    )


def _save_job(title: str, company: str, description: str) -> int:
    db.upsert_job_posting(
        JobPosting(
            external_id=title.lower().replace(" ", "-"),
            source="test",
            company=company,
            title=title,
            location="Remote",
            apply_url=f"https://example.com/{title}",
            description_text=description,
            content_hash=f"hash-{title}",
            raw_payload={},
        ),
        seen_at="2026-01-01T10:00:00",
    )
    return int(db.get_job_postings(limit=1).iloc[0]["id"])


def _ranking(score: int, decision: str, evidence: RankingEvidence) -> RankingResult:
    return RankingResult(
        final_score=score,
        decision=decision,  # type: ignore[arg-type]
        confidence=0.9,
        scores=RankingScores(
            technical_fit=score,
            seniority_fit=score,
            role_fit=score,
            opportunity_quality=score,
            application_roi=score,
            market_alignment=score,
            risk_penalty=5,
        ),
        evidence=evidence,
        reasoning_summary="Stored ranking.",
        recommended_application_angle="Use truthful backend evidence.",
        cv_keywords_to_emphasize=["Python"],
        cv_keywords_to_avoid_overclaiming=[],
        ranking_version="ranking_v1.1.0-nvidia",
    )
