from __future__ import annotations

import json
from pathlib import Path

from joborchestrator.evals.semantic import (
    build_auto_eval_case,
    build_llm_judge_payload,
    evaluate_application_materials,
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
        "cover_letter": "Acme Labs needs Python APIs, FastAPI delivery, and PostgreSQL ownership.",
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
        "cover_letter": "Ignacio is Kubernetes Certified and has a PhD.",
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
        "cover_letter": "Acme Labs backend role.",
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
    assert "Fiction Express" in case["candidate"]["required_experience_terms"]


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
