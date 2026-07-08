from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranker import decision_from_score, rank_job
from joborchestrator.ranking.schemas import CandidateProfile


PROFILE = load_candidate_profile()


def make_job(title, description, source="greenhouse", company="Acme", location="Spain Remote", apply_url="https://boards.greenhouse.io/acme/jobs/1"):
    return {
        "id": 1,
        "external_id": "1",
        "source": source,
        "company": company,
        "title": title,
        "location": location,
        "workplace_type": "remote",
        "url": apply_url,
        "apply_url": apply_url,
        "description_text": description,
        "salary_min": None,
        "salary_max": None,
    }


def test_python_fastapi_aws_four_years_ranks_high():
    job = make_job(
        "Senior Python Backend Engineer",
        """
        Requirements: 4+ years Python, FastAPI, REST APIs, AWS, Docker, SQL.
        Responsibilities: build backend APIs and own cloud services.
        Nice to have: Kubernetes.
        """,
    )

    result = rank_job(job, PROFILE)

    assert result.final_score >= 70
    assert result.decision in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"}
    assert "Python" in result.evidence.strong_matches
    assert result.scores.technical_fit >= 75


def test_pure_react_frontend_ranks_low_or_medium_low():
    job = make_job(
        "Frontend Engineer",
        "Requirements: React, TypeScript, CSS, design systems. Responsibilities: build UI components.",
    )

    result = rank_job(job, PROFILE)

    assert result.scores.role_fit < 40
    assert result.decision in {"MAYBE", "SKIP", "AVOID"}


def test_senior_architect_eight_years_penalized_strongly():
    job = make_job(
        "Senior Architect",
        "Requirements: 8+ years experience as Staff or Principal Architect. Required: Kubernetes, Terraform, enterprise architecture.",
    )

    result = rank_job(job, PROFILE)

    assert result.scores.seniority_fit < 35
    assert result.decision in {"MAYBE", "SKIP", "AVOID"}


def test_postgresql_is_partial_not_critical_gap():
    job = make_job(
        "Backend Engineer",
        "Requirements: Python, PostgreSQL, REST APIs. Responsibilities: build database-backed APIs.",
    )

    result = rank_job(job, PROFILE)

    matched = result.evidence.strong_matches + result.evidence.partial_matches
    assert any("PostgreSQL" in item for item in matched)
    assert "PostgreSQL" not in result.evidence.missing_requirements


def test_mandatory_relocation_outside_spain_is_dealbreaker():
    job = make_job(
        "Backend Engineer",
        "Requirements: Python, Django. This role requires mandatory relocation to Dubai and is onsite only.",
        location="Dubai onsite",
    )

    result = rank_job(job, PROFILE)

    assert result.evidence.dealbreakers or any("relocation" in x.lower() for x in result.evidence.red_flags)
    assert result.decision in {"SKIP", "AVOID"}


def test_unpaid_or_commission_only_is_avoid():
    job = make_job(
        "Backend Developer",
        "Requirements: Python and APIs. This is an unpaid internship with commission only compensation.",
    )

    result = rank_job(job, PROFILE)

    assert result.decision == "AVOID"
    assert result.final_score <= 29


def test_kubernetes_nice_to_have_does_not_penalize_strongly():
    job = make_job(
        "Python Backend Developer",
        "Requirements: Python, Django, REST APIs, SQL. Nice to have: Kubernetes.",
    )

    result = rank_job(job, PROFILE)

    assert result.scores.technical_fit >= 70
    assert not any(item == "Kubernetes" for item in result.evidence.missing_requirements)


def test_pure_devops_role_has_low_role_fit():
    job = make_job(
        "DevOps Engineer",
        "Requirements: Terraform, Kubernetes, CI/CD, observability, SRE. Responsibilities: manage infrastructure.",
    )

    result = rank_job(job, PROFILE)

    assert result.scores.role_fit < 45
    assert result.decision in {"MAYBE", "SKIP", "AVOID"}


def test_technical_solutions_engineer_with_apis_is_medium_fit():
    job = make_job(
        "Solutions Engineer",
        "Requirements: APIs, integrations, Python, customer-facing technical consulting. Responsibilities: help customers implement workflows.",
    )

    result = rank_job(job, PROFILE)

    assert result.scores.role_fit >= 55
    assert result.decision in {"APPLY_WITH_TAILORED_CV", "MAYBE", "APPLY_NOW"}


def test_manual_qa_is_not_a_global_dealbreaker():
    qa_profile = CandidateProfile(
        target_roles=["QA Tester"],
        role_aliases={"QA Tester": ["Manual QA", "Quality Assurance Tester"]},
        strong_skills=["Manual QA", "Test cases", "Bug reports"],
        medium_skills=["Regression testing"],
        preferred_locations=["Spain"],
        preferred_work_modes=["remote"],
        real_experience_years=3,
    )
    job = make_job(
        "Manual QA Tester",
        "Requirements: Manual QA, test cases, regression testing. Responsibilities: report bugs and verify fixes.",
    )

    result = rank_job(job, qa_profile)

    flags = result.evidence.dealbreakers + result.evidence.red_flags
    assert not any("manual qa" in flag.lower() for flag in flags)


def test_low_parse_confidence_caps_ranking_decision():
    job = make_job(
        "Senior Python Backend Engineer",
        """
        Requirements: 4+ years Python, FastAPI, REST APIs, AWS, Docker, SQL.
        Responsibilities: build backend APIs and own cloud services.
        """,
        source="linkedin_scraper",
    )
    job["parse_confidence"] = 0.42

    result = rank_job(job, PROFILE)

    assert result.decision in {"MAYBE", "SKIP", "AVOID"}
    assert result.final_score <= 64
    assert "Low extraction confidence" in result.evidence.red_flags


def test_score_to_decision_mapping():
    assert decision_from_score(85) == "APPLY_NOW"
    assert decision_from_score(70) == "APPLY_WITH_TAILORED_CV"
    assert decision_from_score(55) == "MAYBE"
    assert decision_from_score(35) == "SKIP"
    assert decision_from_score(10) == "AVOID"


def test_risk_penalty_reduces_score():
    clean = make_job(
        "Python Backend Engineer",
        "Requirements: Python, FastAPI, REST APIs, AWS. Responsibilities: build clear backend services.",
    )
    risky = make_job(
        "Python Backend Engineer",
        "Requirements: Python, FastAPI, REST APIs, AWS. Rockstar wanted. Work hard play hard. Commission only.",
    )

    clean_result = rank_job(clean, PROFILE)
    risky_result = rank_job(risky, PROFILE)

    assert risky_result.scores.risk_penalty > clean_result.scores.risk_penalty
    assert risky_result.final_score < clean_result.final_score


def test_final_score_always_clamped():
    job = make_job(
        "Unpaid Principal Mobile Architect",
        "Unpaid commission only role. Requirements: 12+ years, mobile, relocation to China, rockstar ninja.",
        location="China onsite",
    )

    result = rank_job(job, PROFILE)

    assert 0 <= result.final_score <= 100
    assert 0 <= result.scores.risk_penalty <= 40
