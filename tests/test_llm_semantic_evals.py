from __future__ import annotations

import json
from pathlib import Path

from joborchestrator.evals.semantic import (
    build_auto_eval_case,
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ats_cv_result,
    evaluate_ranking_result,
)
from joborchestrator.storage import persistence as db


def _cases() -> dict[str, dict]:
    path = Path(__file__).parent / "fixtures" / "llm_eval_cases.json"
    return {case["id"]: case for case in json.loads(path.read_text(encoding="utf-8"))}


def test_material_eval_accepts_truthful_tailored_materials():
    case = _cases()["backend-fastapi-strong-fit"]
    materials = {
        "recruiter_message": (
            "Hi Acme Labs team, Ignacio's Python/FastAPI backend work maps well to your Backend Engineer role. "
            "Happy to share his CV."
        ),
        "cover_letter": (
            "Dear Acme Labs team,\n\nIgnacio's Python API, FastAPI, and PostgreSQL background maps well to "
            "the Backend Engineer role, with practical experience building reliable backend services for product teams."
        ),
        "ats_cv_text": """
Ignacio Rodriguez

Professional Summary
Backend engineer focused on Python, FastAPI APIs, PostgreSQL, and product delivery.

Technical Skills
Python, FastAPI, PostgreSQL, AWS, observability, REST APIs.

Professional Experience
Fiction Express
- Built Python APIs and backend workflows.
Talan Consulting
- Delivered product dashboards and integrations.
Globant
- Supported AWS microservices.
Balloon Group
- Built web applications.

Education
Software engineering coursework.
""",
        "autofill_notes": "Use the Acme Labs angle around Python APIs, PostgreSQL ownership, and product collaboration.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is True
    assert result.score == 100
    assert result.issues == []


def test_material_eval_rejects_hallucinated_claims_and_omissions():
    case = _cases()["backend-fastapi-strong-fit"]
    materials = {
        "recruiter_message": "Dear Hiring Manager, I am writing to express interest in the Backend Engineer role.",
        "cover_letter": "Ignacio is Kubernetes Certified and has a PhD from a top university, with extensive platform leadership beyond the source CV.",
        "ats_cv_text": "Professional Summary\nPython engineer\nProfessional Experience\nFiction Express\nEducation\nCoursework",
        "autofill_notes": "Mention Kubernetes Certified.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is False
    assert any(issue.startswith("unsupported_claims:") for issue in result.issues)
    assert any(issue.startswith("omitted_base_experience:") for issue in result.issues)
    assert any(issue.startswith("recruiter_message_cover_letter_style:") for issue in result.issues)


def test_material_eval_rejects_internal_cv_notes():
    case = _cases()["backend-fastapi-strong-fit"]
    materials = {
        "recruiter_message": "Hi Acme Labs, Python/FastAPI backend fit for the Backend Engineer role.",
        "cover_letter": "Dear Acme Labs team,\n\nIgnacio's backend experience maps well to the role through Python APIs, delivery ownership, and pragmatic product collaboration.",
        "ats_cv_text": (
            "Ignacio Rodriguez\nProfessional Summary\nPython FastAPI PostgreSQL\n"
            "Target role: Backend Engineer\nATS keywords to emphasize truthfully: Python\n"
            "Optimized CV\nProfessional Experience\nFiction Express\nTalan Consulting\nGlobant\nBalloon Group\n"
            "Education\nCoursework"
        ),
        "autofill_notes": "Use Acme Labs backend angle.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is False
    assert any(issue.startswith("ats_cv_contains_internal_notes:") for issue in result.issues)


def test_material_eval_rejects_empty_cover_letter():
    case = _cases()["backend-fastapi-strong-fit"]
    materials = {
        "recruiter_message": "Hi Acme Labs, Python/FastAPI backend fit for the Backend Engineer role.",
        "cover_letter": "",
        "ats_cv_text": """
Professional Summary
Python backend engineer.
Technical Skills
Python, FastAPI, PostgreSQL.
Professional Experience
Fiction Express
Talan Consulting
Globant
Balloon Group
Education
Software engineering coursework.
""",
        "autofill_notes": "Use Acme Labs backend angle.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is False
    assert "missing_required_fields:cover_letter" in result.issues


def test_material_eval_rejects_overconfident_tone_for_skip_ranking():
    case = build_auto_eval_case(
        {"title": "Python Developer", "company": "Hire Feed"},
        {"base_cv_text": "EXPERIENCE\nFiction Express\nTalan Consulting\nGlobant\nBalloon Group"},
        {
            "decision": "SKIP",
            "evidence": {"dealbreakers": ["contract AI training/verification work"]},
        },
    )
    materials = {
        "recruiter_message": "Hi Hire Feed, Python backend experience may be relevant to review for the role.",
        "cover_letter": (
            "Dear Hire Feed team,\n\nI am confident my skills will make an immediate impact, and I am "
            "excited to enhance your AI systems through this Python Developer role."
        ),
        "ats_cv_text": """
Professional Summary
Python backend engineer.
Technical Skills
Python, Django, APIs.
Professional Experience
Fiction Express
Talan Consulting
Globant
Balloon Group
Education
Software engineering coursework.
""",
        "autofill_notes": "Position as a strong fit with immediate impact.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is False
    assert any(issue.startswith("application_materials_overconfident_for_risky_ranking:") for issue in result.issues)


def test_material_eval_ignores_generation_metadata_text():
    case = _cases()["backend-fastapi-strong-fit"]
    materials = {
        "recruiter_message": "Hi Acme Labs, Python/FastAPI backend fit for the Backend Engineer role.",
        "cover_letter": (
            "Dear Acme Labs team,\n\nIgnacio's Python API and FastAPI background maps well to the Backend "
            "Engineer role, with practical delivery experience across backend services and product collaboration."
        ),
        "ats_cv_text": """
Professional Summary
Python backend engineer.
Technical Skills
Python, FastAPI, PostgreSQL.
Professional Experience
Fiction Express
Talan Consulting
Globant
Balloon Group
Education
Software engineering coursework.
""",
        "autofill_notes": "Use Acme Labs backend angle.",
        "_generation_metadata": {
            "validation_errors": [
                "application_materials contains unsupported ranking avoid-overclaiming terms",
                "application materials use overconfident tone: eager to",
            ]
        },
    }

    result = evaluate_application_materials(case, materials)

    assert result.passed is True
    assert result.issues == []


def test_ats_cv_eval_accepts_complete_truthful_parseable_cv():
    case = _cases()["backend-fastapi-strong-fit"]
    ats_cv = """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com

Professional Summary
Backend engineer focused on Python APIs, FastAPI services, PostgreSQL data models, observability, and product delivery.
Experienced turning product requirements into reliable backend systems and collaborating with cross-functional teams.

Technical Skills
Python, FastAPI, PostgreSQL, SQL, REST APIs, AWS, observability, dashboards, automation, stakeholder collaboration.

Professional Experience
Backend Engineer | Fiction Express
- Built and maintained Python API workflows and backend features for digital learning products.
- Improved service reliability, observability, and data workflows in collaboration with product stakeholders.

Full Stack Developer | Talan Consulting
- Delivered dashboards, integrations, and SQL-backed product features for business users.
- Partnered with frontend and product teams to scope backend deliverables and implementation plans.

Backend Developer | Globant
- Supported AWS-based backend services, integrations, and production troubleshooting.

Full Stack Developer | Balloon Group
- Built web applications and backend functionality across product delivery cycles.

Education
Software engineering coursework and ongoing professional development in backend systems.
""".strip()

    result = evaluate_ats_cv_result(case, {"ats_cv_text": ats_cv})

    assert result.passed is True
    assert result.issues == []


def test_ats_cv_eval_accepts_supported_keyword_variants_and_punctuation():
    case = {
        "candidate": {
            "required_experience_terms": [
                "Built Python API integrations for operations teams.",
                "Documented deployment and support workflows.",
            ],
            "forbidden_claims": [],
        },
        "ats_cv_expectations": {
            "required_keywords": ["API integrations", "documentation", "operations workflows"],
            "required_sections": ["summary", "skills", "experience", "education"],
            "min_chars": 200,
        },
    }
    ats_cv = """
Ignacio Rodriguez

Professional Summary
Backend developer focused on API integrations, documentation, and operations workflow support.

Technical Skills
Python, REST APIs, API integrations, deployment documentation, operations workflow support.

Professional Experience
Backend Developer | Example Co
- Built Python API integrations for operations teams, enhancing workflow efficiency.
- Documented deployment and support workflows to improve team onboarding.

Education
Software engineering coursework.
""".strip()

    result = evaluate_ats_cv_result(case, {"ats_cv_text": ats_cv})

    assert result.passed is True
    assert result.issues == []


def test_ats_cv_eval_rejects_internal_notes_and_hallucinated_claims():
    case = _cases()["backend-fastapi-strong-fit"]
    result = evaluate_ats_cv_result(
        case,
        {
            "ats_cv_text": (
                "Professional Summary\nKubernetes Certified backend engineer\n"
                "Target role: Backend Engineer\n"
                "Technical Skills\nPython\n"
                "Professional Experience\nFiction Express\n"
                "Education\nCoursework"
            )
        },
    )

    assert result.passed is False
    assert any(issue.startswith("unsupported_claims:") for issue in result.issues)
    assert any(issue.startswith("missing_required_keywords:") for issue in result.issues)
    assert any(issue.startswith("omitted_base_experience:") for issue in result.issues)
    assert any(issue.startswith("ats_cv_contains_internal_notes:") for issue in result.issues)


def test_ranking_eval_accepts_expected_decision_band():
    case = _cases()["backend-fastapi-strong-fit"]
    ranking = {
        "final_score": 82,
        "decision": "APPLY_WITH_TAILORED_CV",
        "evidence": {
            "strong_matches": ["Python", "FastAPI", "PostgreSQL"],
            "missing_requirements": [],
            "dealbreakers": [],
        },
        "reasoning_summary": "Strong Python and FastAPI overlap for backend API delivery.",
        "recommended_application_angle": "Emphasize Python APIs and PostgreSQL ownership.",
        "cv_keywords_to_emphasize": ["Python", "FastAPI", "PostgreSQL"],
        "cv_keywords_to_avoid_overclaiming": [],
    }

    result = evaluate_ranking_result(case, ranking)

    assert result.passed is True
    assert result.score == 100


def test_ranking_eval_accepts_evidence_term_synonyms():
    case = {
        "ranking_expectations": {
            "allowed_decisions": ["APPLY_WITH_TAILORED_CV"],
            "required_evidence_terms": ["REST APIs", "EPC"],
            "dealbreaker_terms": ["EPC"],
            "keyword_synonyms": {
                "REST APIs": ["API REST", "REST API"],
                "EPC": ["Engineering Procurement and Construction"],
            },
        }
    }
    ranking = {
        "final_score": 70,
        "decision": "APPLY_WITH_TAILORED_CV",
        "evidence": {
            "strong_matches": ["Python backend", "API REST delivery"],
            "missing_requirements": ["Engineering Procurement and Construction domain"],
            "dealbreakers": [],
        },
        "cv_keywords_to_emphasize": [],
        "cv_keywords_to_avoid_overclaiming": [],
    }

    result = evaluate_ranking_result(case, ranking)

    assert result.passed is True
    assert result.metrics["missing_evidence_terms"] == []
    assert result.metrics["mentioned_dealbreakers"] == ["EPC"]


def test_ranking_eval_rejects_apply_now_for_dealbreaker_mismatch():
    case = _cases()["rust-kernel-mismatch"]
    ranking = {
        "final_score": 92,
        "decision": "APPLY_NOW",
        "evidence": {
            "strong_matches": ["backend engineering"],
            "missing_requirements": [],
            "dealbreakers": [],
        },
        "reasoning_summary": "Good engineering background.",
        "recommended_application_angle": "Apply directly.",
        "cv_keywords_to_emphasize": ["Rust kernel", "device drivers"],
        "cv_keywords_to_avoid_overclaiming": [],
    }

    result = evaluate_ranking_result(case, ranking)

    assert result.passed is False
    assert "decision_outside_expected_band:APPLY_NOW" in result.issues
    assert "apply_now_with_expected_dealbreaker" in result.issues
    assert any(issue.startswith("score_above_expected:") for issue in result.issues)
    assert any(issue.startswith("unsafe_cv_keyword_emphasis:") for issue in result.issues)


def test_llm_judge_payload_is_structured_and_offline():
    case = _cases()["backend-fastapi-strong-fit"]
    output = {"decision": "APPLY_NOW", "final_score": 88}

    payload = build_llm_judge_payload(case, output, "ranking")

    assert payload["artifact_type"] == "ranking"
    assert payload["case_id"] == "backend-fastapi-strong-fit"
    assert payload["rubric_version"] == "semantic-eval-v1"
    assert payload["source_case"]["job"]["company"] == "Acme Labs"
    assert payload["candidate_output"] == output
    assert "unsupported_claims" in payload["rubric"]["issue_codes"]
    assert payload["expected_response_schema"]["issue_codes"] == ["enum string from rubric.issue_codes"]


def test_llm_judge_payload_supports_ats_cv_rubric():
    case = _cases()["backend-fastapi-strong-fit"]
    output = {"ats_cv_text": "Professional Summary\nPython FastAPI PostgreSQL"}

    payload = build_llm_judge_payload(case, output, "ats_cv")

    assert payload["artifact_type"] == "ats_cv"
    assert payload["source_case"]["expectations"]["ats_cv"]["required_keywords"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
    ]
    assert any("parseable" in rule for rule in payload["rubric"]["pass_fail_rules"])


def test_all_fixture_cases_have_eval_expectations():
    for case in _cases().values():
        assert case["job"]["title"]
        assert case["candidate"]["base_cv_text"]
        assert case.get("materials_expectations") or case.get("ranking_expectations")
        if case.get("ranking_expectations"):
            payload = build_llm_judge_payload(case, {"decision": "MAYBE", "final_score": 50}, "ranking")
            assert payload["case_id"] == case["id"]


def test_auto_eval_case_uses_job_and_profile_terms():
    case = build_auto_eval_case(
        {
            "id": 77,
            "title": "AWS Backend Developer",
            "company": "CloudWorks",
            "description_text": "Build Python APIs on AWS with PostgreSQL.",
        },
        {
            "base_cv_text": "Experience\nFiction Express\nTalan Consulting\nPython AWS PostgreSQL APIs",
            "skills": [
                {"name": "Python", "level": "strong"},
                {"name": "AWS", "level": "strong"},
                {"name": "React", "level": "medium"},
            ],
        },
    )

    assert case["id"] == "auto-job-77"
    assert case["materials_expectations"]["specificity_terms"] == ["CloudWorks", "AWS Backend Developer"]
    assert {"Python", "AWS", "PostgreSQL"}.issubset(set(case["materials_expectations"]["required_terms"]))
    assert {"Python", "AWS", "PostgreSQL"}.issubset(set(case["ats_cv_expectations"]["required_keywords"]))
    assert "Fiction Express" in case["candidate"]["required_experience_terms"]


def test_auto_eval_case_extracts_generic_employers_without_known_names():
    case = build_auto_eval_case(
        {
            "id": 78,
            "title": "Backend Developer",
            "company": "CloudWorks",
            "description_text": "Build Python APIs.",
        },
        {
            "base_cv_text": """
Professional Experience
Backend Developer April 2025 - March 2026
Northstar Labs
- Built Python APIs.
Full Stack Developer October 2022 - April 2025
Riverstone Digital
- Built reporting dashboards.
Education
Software Engineering.
""",
            "skills": [{"name": "Python", "level": "strong"}],
        },
    )

    assert case["candidate"]["required_experience_terms"] == ["Northstar Labs", "Riverstone Digital"]


def test_semantic_keyword_matching_does_not_count_sql_inside_nosql():
    case = {
        "ats_cv_expectations": {"required_keywords": ["SQL"], "required_sections": []},
        "candidate": {},
    }

    result = evaluate_ats_cv_result(case, {"ats_cv_text": "Professional Summary\nNoSQL databases and APIs."})

    assert result.passed is False
    assert "missing_required_keywords:SQL" in result.issues


def test_auto_eval_case_limits_required_terms_for_skip_jobs():
    case = build_auto_eval_case(
        {
            "id": 93,
            "title": "Python Django Backend Engineer",
            "company": "GridOps",
            "description_text": (
                "Required skills: Python, Django, and PostgreSQL. "
                "Nice to have exposure to EC2, Monitoring, and Code Review."
            ),
        },
        {
            "base_cv_text": (
                "Experience\nPython Django PostgreSQL APIs. "
                "Some EC2 Monitoring and Code Review collaboration."
            ),
            "skills": [
                {"name": "Python", "level": "strong"},
                {"name": "Django", "level": "strong"},
                {"name": "PostgreSQL", "level": "strong"},
                {"name": "EC2", "level": "strong"},
                {"name": "Monitoring", "level": "medium"},
                {"name": "Code Review", "level": "medium"},
            ],
        },
        {
            "decision": "SKIP",
            "final_score": 45,
            "cv_keywords_to_emphasize": ["Python", "Django", "PostgreSQL"],
            "cv_keywords_to_avoid_overclaiming": [],
        },
    )

    assert case["materials_expectations"]["required_terms"] == ["Python", "Django", "PostgreSQL"]
    assert case["ats_cv_expectations"]["required_keywords"] == ["Python", "Django", "PostgreSQL"]


def test_auto_eval_case_accepts_ranker_profile_skill_groups():
    case = build_auto_eval_case(
        {
            "id": 80,
            "title": "Backend Engineer",
            "company": "Acme Labs",
            "description_text": "Required skills: Python, FastAPI, and PostgreSQL.",
        },
        {
            "strong_skills": ["Python", "FastAPI"],
            "medium_skills": ["PostgreSQL"],
            "weak_skills": ["React"],
            "notes": "Backend engineer focused on Python APIs.",
        },
        {"decision": "APPLY_NOW", "final_score": 88},
    )

    assert case["materials_expectations"]["required_terms"] == ["Python", "FastAPI", "PostgreSQL"]


def test_auto_eval_case_rejects_profile_derived_unsupported_claims():
    case = build_auto_eval_case(
        {
            "id": 78,
            "title": "AWS Backend Developer",
            "company": "CloudWorks",
            "description_text": "Build Python APIs on AWS with PostgreSQL.",
        },
        {
            "base_cv_text": "Experience\nPython AWS PostgreSQL APIs",
            "real_experience_years": 4,
            "skills": [
                {"name": "Python", "level": "strong"},
                {"name": "AWS", "level": "strong"},
                {"name": "PostgreSQL", "level": "strong"},
            ],
        },
    )
    materials = {
        "recruiter_message": "Hi CloudWorks, Ignacio's AWS backend work fits the AWS Backend Developer role.",
        "cover_letter": "Ignacio is an AWS Certified Solutions Architect with 10+ years of backend experience.",
        "ats_cv_text": "Professional Summary\nPython AWS PostgreSQL backend engineer.",
        "autofill_notes": "Mention AWS Certified Solutions Architect.",
    }

    result = evaluate_application_materials(case, materials)

    assert "PhD" not in case["candidate"]["forbidden_claims"]
    assert any(issue.startswith("unsupported_claims:") for issue in result.issues)
    assert "AWS Certified Solutions Architect" in result.metrics["unsupported_claims"]
    assert "10+ years" in result.metrics["unsupported_claims"]


def test_auto_eval_case_allows_declared_experience_years():
    case = build_auto_eval_case(
        {
            "id": 79,
            "title": "Python Backend Developer",
            "company": "CloudWorks",
            "description_text": "Build Python APIs.",
        },
        {
            "base_cv_text": "Experience\nPython APIs",
            "real_experience_years": 4,
            "skills": [{"name": "Python", "level": "strong"}],
        },
    )
    materials = {
        "recruiter_message": "Hi CloudWorks, Ignacio's Python backend work fits the Python Backend Developer role.",
        "cover_letter": "Ignacio brings 4+ years of backend experience with Python APIs.",
        "ats_cv_text": "Professional Summary\nPython backend engineer.",
        "autofill_notes": "Mention Python APIs.",
    }

    result = evaluate_application_materials(case, materials)

    assert result.metrics["unsupported_claims"] == []


def test_eval_runs_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "evals.db")
    db.init_db()
    case = _cases()["backend-fastapi-strong-fit"]
    output = {"decision": "APPLY_NOW", "final_score": 88}
    result = evaluate_ranking_result(
        case,
        {
            **output,
            "evidence": {"strong_matches": ["Python", "FastAPI"], "missing_requirements": []},
            "reasoning_summary": "Python and FastAPI match the target backend work.",
            "recommended_application_angle": "Lead with Python API work.",
            "cv_keywords_to_emphasize": ["Python", "FastAPI"],
            "cv_keywords_to_avoid_overclaiming": [],
        },
    )
    judge_payload = build_llm_judge_payload(case, output, "ranking")

    saved = db.save_llm_eval_run(
        {
            "case_id": case["id"],
            "artifact_type": "ranking",
            "ranking_version": "test-ranking-v1",
            "provider": "offline",
            "model": "deterministic",
            "passed": result.passed,
            "score": result.score,
            "issues": result.issues,
            "metrics": result.metrics,
            "output": output,
            "judge_payload": judge_payload,
            "judge_provider": "openai",
            "judge_model": "judge-test",
            "judge_result": {"passed": True, "score": 95, "issues": [], "rationale": "Looks good."},
            "notes": "fixture run",
        }
    )
    runs = db.list_llm_eval_runs(limit=5)

    assert saved["id"] == 1
    assert len(runs) == 1
    row = runs.iloc[0]
    assert row["case_id"] == "backend-fastapi-strong-fit"
    assert row["artifact_type"] == "ranking"
    assert row["passed"] == 1
    assert row["score"] == 100
    assert row["judge_provider"] == "openai"
    assert row["judge_model"] == "judge-test"
    assert "Looks good" in row["judge_result_json"]
