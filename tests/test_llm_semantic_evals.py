from __future__ import annotations

import json
from pathlib import Path

from joborchestrator.evals.semantic import (
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ranking_result,
)


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
