from __future__ import annotations

import json

from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION, rank_job_speed
from joborchestrator.ranking.structural_requirements import (
    LLM_REVIEW_COVERAGE_THRESHOLD,
    LOW_COVERAGE_THRESHOLD,
)
from joborchestrator.storage import persistence as db
from joborchestrator.scanning.models import JobPosting


def profile() -> CandidateProfile:
    return CandidateProfile(
        target_roles=["Backend Engineer", "Python Developer"],
        secondary_roles=["Technical Consultant", "Solutions Engineer"],
        strong_skills=["Python", "Django", "FastAPI", "Flask", "PostgreSQL", "REST APIs"],
        medium_skills=["Docker", "AWS", "SQL", "Integrations"],
        weak_skills=["React"],
        real_experience_years=4,
    )


def rank(title: str, description: str):
    return rank_job_speed(
        {
            "title": title,
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Remote",
            "description_text": description,
        },
        profile(),
    )


def assert_low_structural_coverage(result) -> None:
    assert result.ranking_version == SPEED_RANKING_VERSION
    assert result.evidence.central_requirement_coverage is not None
    assert result.evidence.central_requirement_coverage < LOW_COVERAGE_THRESHOLD
    assert result.scores.technical_readiness <= 30
    assert result.scores.role_fit <= 35
    assert result.decision in {"AVOID", "SKIP"}
    assert result.evidence.requires_llm_review is True
    assert "central_requirement_coverage_below_low_threshold" in result.evidence.llm_escalation_reasons
    assert result.evidence.central_requirement_thresholds["low_coverage_threshold"] == LOW_COVERAGE_THRESHOLD
    assert result.evidence.central_requirement_thresholds["llm_review_coverage_threshold"] == LLM_REVIEW_COVERAGE_THRESHOLD


def test_firmware_role_is_capped_by_structural_coverage() -> None:
    result = rank(
        "Embedded Firmware Engineer",
        (
            "Requirements: Must have strong experience in C/C++, microcontrollers, "
            "FreeRTOS, LoRaWAN, BLE, NB-IoT. Responsibilities: develop embedded firmware for IoT devices."
        ),
    )

    assert_low_structural_coverage(result)
    central_terms = {item["term"] for item in result.evidence.central_requirements}
    assert {"freertos", "lorawan", "ble"} & central_terms


def test_unknown_adjacent_domains_are_capped_without_domain_keywords() -> None:
    examples = [
        (
            "SAP Consultant",
            (
                "Requirements: Must have strong experience in SAP S/4HANA, ABAP, FI/CO "
                "and enterprise implementation projects. Responsibilities: configure SAP modules."
            ),
        ),
        (
            "Salesforce Administrator",
            (
                "Requirements: Strong experience with Salesforce Admin, Flow Builder, SOQL, "
                "reports, dashboards and user permissions. Must maintain CRM workflows."
            ),
        ),
        (
            "Game Developer",
            (
                "Requirements: Must have strong experience with Unity, Unreal Engine, C#, "
                "gameplay systems and physics. Responsibilities: build gameplay features."
            ),
        ),
    ]

    for title, description in examples:
        assert_low_structural_coverage(rank(title, description))


def test_python_backend_role_keeps_high_central_requirement_coverage() -> None:
    result = rank(
        "Backend Engineer",
        (
            "Requirements: Must have strong experience in Python, FastAPI, Django, "
            "REST APIs and PostgreSQL. Responsibilities: build backend APIs and data services."
        ),
    )

    assert result.evidence.central_requirement_coverage is not None
    assert result.evidence.central_requirement_coverage >= 0.65
    assert result.scores.technical_readiness >= 60
    assert result.scores.role_fit >= 80
    assert result.evidence.requires_llm_review is False


def test_location_terms_do_not_become_central_requirements() -> None:
    result = rank_job_speed(
        {
            "title": "Backend Engineer - Remote, Spain",
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Remote, Spain",
            "description_text": (
                "Requirements: Must have strong experience in Python, FastAPI, REST APIs and PostgreSQL."
            ),
        },
        profile(),
    )

    central_terms = {item["term"] for item in result.evidence.central_requirements}
    assert "remote" not in central_terms
    assert "spain" not in central_terms
    assert result.evidence.central_requirement_coverage >= 0.65


def test_title_only_role_match_does_not_create_perfect_coverage() -> None:
    result = rank_job_speed(
        {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Remote",
            "description_text": "About the company. We are growing our engineering team.",
        },
        profile(),
    )

    assert result.evidence.central_requirement_coverage < LLM_REVIEW_COVERAGE_THRESHOLD
    assert result.evidence.requires_llm_review is True
    assert "insufficient_requirement_backed_evidence" in result.evidence.llm_escalation_reasons


def test_collaborating_with_product_managers_does_not_reclassify_backend_role() -> None:
    result = rank_job_speed(
        {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Remote",
            "description_text": (
                "What You Will Do: Design, develop, and maintain scalable backend services using Java and Spring Boot. "
                "Build and evolve RESTful APIs. Collaborate closely with frontend engineers, product managers, "
                "and designers to deliver end-to-end solutions."
            ),
        },
        profile(),
    )

    assert result.scores.role_fit >= 35
    assert "Product Manager" not in result.recommended_application_angle


def test_viable_python_fullstack_role_gets_manual_review_floor() -> None:
    result = rank_job_speed(
        {
            "title": "FullStack (Python/React)",
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Hybrid",
            "description_text": (
                "We are looking for a developer to build internal tools. "
                "Experience with Python, FastAPI, React and REST APIs. "
                "You will integrate services and maintain backend APIs."
            ),
        },
        profile(),
    )

    assert result.scores.technical_readiness >= 50
    assert result.scores.role_fit >= 55
    assert result.evidence.central_requirement_coverage >= LLM_REVIEW_COVERAGE_THRESHOLD
    assert result.decision in {"MAYBE", "APPLY_WITH_TAILORED_CV", "APPLY_NOW"}


def test_requirement_section_does_not_bleed_into_company_boilerplate() -> None:
    result = rank_job_speed(
        {
            "title": "Hardware Engineer Internship",
            "company": "Acme",
            "source": "linkedin_scraper",
            "location": "Onsite",
            "description_text": (
                "Requirements: enrolled in an electronics degree. "
                "Working at Acme means joining a global automotive group with health benefits."
            ),
        },
        profile(),
    )

    central_terms = {item["term"] for item in result.evidence.central_requirements}
    assert "group" not in central_terms
    assert "working" not in central_terms
    assert "health" not in central_terms


def test_save_speed_ranking_updates_job_posting_cached_signals(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    job = JobPosting(
        external_id="backend-1",
        source="greenhouse",
        company="Acme",
        title="Backend Engineer",
        location="Remote",
        url="https://jobs.example/backend",
        apply_url="https://jobs.example/backend/apply",
        description_text=(
            "Requirements: Must have strong experience in Python, FastAPI, Django, "
            "REST APIs and PostgreSQL."
        ),
        content_hash="hash-1",
        raw_payload={},
    )
    db.upsert_job_posting(job, seen_at="2026-01-01T10:00:00")
    stored = db.get_job_postings(limit=10).iloc[0]
    ranking = rank_job_speed(stored.to_dict(), profile())

    db.save_job_ranking(int(stored["id"]), ranking)
    refreshed = db.get_job_posting(int(stored["id"]))
    rankings = db.get_ranked_jobs(ranking_version=SPEED_RANKING_VERSION)

    assert refreshed["speed_signal"] == ranking.scores.speed_signal
    assert refreshed["application_effort_signal"] == ranking.scores.application_effort_signal
    assert refreshed["data_quality_signal"] == ranking.scores.data_quality_signal
    assert refreshed["source_reliability_signal"] == ranking.scores.source_reliability_signal
    assert refreshed["role_viable"] == 1
    evidence = json.loads(rankings.iloc[0]["evidence_json"])
    assert evidence["central_requirement_coverage"] == ranking.evidence.central_requirement_coverage
