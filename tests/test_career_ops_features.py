from joborchestrator.intelligence.evaluation_framework import build_af_evaluation
from joborchestrator.intelligence.cover_letter_generator import (
    build_cover_letter_payload,
    export_cover_letter_pdf,
)
from joborchestrator.intelligence.ats_autofill import build_autofill_plan
from joborchestrator.intelligence.llm_application_materials import (
    _materials_validation_error,
    build_application_kit_with_llm,
    estimate_materials_cost,
    export_ats_cv_docx_bytes,
    export_ats_cv_pdf_bytes,
)
from joborchestrator.intelligence.application_materials import (
    ApplicationMaterialsError,
    build_application_kit,
)
from joborchestrator.intelligence.llm_costs import estimate_ranking_tokens


def test_af_evaluation_structure():
    job = {
        "title": "Senior Python Backend Engineer",
        "company": "Anthropic",
        "description": "Build scalable APIs with Python, FastAPI, PostgreSQL, AWS, Docker. Lead backend architecture and mentor engineers.",
        "location": "Remote - Spain",
    }
    profile = "Backend engineer with Python, FastAPI, PostgreSQL, AWS, mentoring experience."

    result = build_af_evaluation(job, profile)

    assert "A" in result["blocks"]
    assert "F" in result["blocks"]
    assert "legitimidad" in result["blocks"]
    assert result["overall_score"] >= 0
    assert result["decision"] in {"go", "review", "skip"}


def test_cover_letter_payload_contains_research_keywords_and_prompts():
    job = {
        "title": "Senior Backend Engineer",
        "company": "Acme Labs",
        "description": "Build reliable APIs, optimize performance, work with Python and distributed systems.",
    }
    profile = "I am a backend engineer with Python, system design and mentoring experience."

    payload = build_cover_letter_payload(job, profile)

    assert payload["research_summary"]
    assert payload["keyword_alignment"]
    assert "why" in payload["angle_prompts"]
    assert "approach" in payload["angle_prompts"]
    assert payload["draft"]
    assert payload["approval_gate"]["ready_for_review"] is True
    assert payload["approval_gate"]["review_prompt"]


def test_autofill_plan_contains_contextual_answers():
    job = {
        "title": "Product Engineer",
        "company": "GreenTech",
        "description": "Build internal tools, collaborate with product, scale frontend and backend systems.",
    }

    plan = build_autofill_plan(job, ats_type="greenhouse")

    assert plan["ats_type"] == "greenhouse"
    assert plan["automation_mode"] == "assisted_copy_paste"
    assert plan["preflight_checklist"]
    assert plan["browser_steps"]
    assert plan["questions"]
    assert any("Why" in q["question"] for q in plan["questions"])
    assert plan["copy_paste_block"]
    assert plan["field_mappings"]
    assert "resume" in plan["field_mappings"]
    assert plan["extension_payload"]["mode"] == "assist_only"
    assert any(response["needs_review"] for response in plan["form_responses"])


def test_heuristic_application_kit_requires_dynamic_profile(monkeypatch):
    from joborchestrator.intelligence import application_materials

    monkeypatch.setattr(application_materials.db, "get_candidate_profile_payload", lambda: None)

    try:
        build_application_kit({"title": "Account Manager", "company": "Acme"})
    except ApplicationMaterialsError as exc:
        assert "No candidate profile configured" in str(exc)
    else:
        raise AssertionError("Expected ApplicationMaterialsError")


def test_heuristic_application_kit_uses_profile_skills(monkeypatch):
    from joborchestrator.intelligence import application_materials

    monkeypatch.setattr(
        application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "headline": "Customer success specialist",
            "target_roles": ["Customer Success Manager"],
            "skills": [
                {"name": "Onboarding", "category": "Customer Success", "level": "strong"},
                {"name": "Renewals", "category": "Revenue", "level": "medium"},
            ],
            "base_cv_text": "Ignacio Rodriguez\nCustomer success specialist\nLed onboarding programs.",
        },
    )

    kit = build_application_kit(
        {"title": "Customer Success Manager", "company": "Acme", "description_text": "Onboarding and renewals"},
        keywords=["Onboarding", "Python"],
    )

    assert "Customer success specialist" in kit["cover_letter"]
    assert "Ignacio Rodriguez" in kit["ats_cv_text"]
    assert "Onboarding" in kit["ats_cv_text"]
    assert "Optimization notes" not in kit["ats_cv_text"]
    assert "Python" not in kit["ats_cv_text"]


def test_pdf_export_creates_file(tmp_path):
    output_path = tmp_path / "cover_letter.pdf"
    created = export_cover_letter_pdf("Hello world", output_path)
    assert created is True
    assert output_path.exists()


def test_llm_cost_estimates_are_positive():
    input_tokens, output_tokens = estimate_ranking_tokens(2500)

    assert input_tokens > output_tokens
    assert estimate_materials_cost(10, model="gpt-5.4-mini") > 0
    assert estimate_materials_cost(10, model="gpt-5.4-mini", batch=True) < estimate_materials_cost(
        10,
        model="gpt-5.4-mini",
    )


def test_llm_application_kit_uses_structured_payload(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "headline": "Backend engineer",
            "target_roles": ["Backend Engineer"],
            "skills": [{"name": "Python", "category": "Programming", "level": "strong"}],
            "base_cv_text": "Ignacio Rodriguez\nBackend engineer\nExperience with Python APIs.",
            "base_cv_filename": "Ignacio Rodriguez.pdf",
        },
    )

    def fake_call(payload, api_key, model, timeout):
        assert payload["candidate_profile"]
        assert "Ignacio Rodriguez" in payload["base_cv"]["text"]
        assert payload["job"]["title"] == "Backend Engineer"
        return {
            "recruiter_message": "Hi team",
            "cover_letter": "Dear hiring team",
            "ats_cv_text": "Python\n- FastAPI APIs",
            "autofill_notes": "LinkedIn: paste recruiter note",
            "risk_flags": [],
            "keywords_used": ["Python"],
        }

    monkeypatch.setattr(llm_application_materials, "_call_openai", fake_call)

    kit = build_application_kit_with_llm(
        {"title": "Backend Engineer", "company": "Acme", "description_text": "Python APIs"},
        model="test-model",
    )

    assert kit["recruiter_message"] == "Hi team"
    assert "FastAPI" in kit["ats_cv_text"]
    assert "LinkedIn" in kit["autofill_notes"]


def test_llm_application_kit_validation_rejects_empty_required_sections():
    error = _materials_validation_error(
        {
            "recruiter_message": "",
            "cover_letter": "",
            "ats_cv_text": "Tiny",
            "autofill_notes": "",
            "risk_flags": "not-array",
            "keywords_used": [],
        }
    )

    assert error is not None
    assert "recruiter_message is required" in error
    assert "autofill_notes is required" in error
    assert "risk_flags must be an array" in error
    assert "ats_cv_text is too short" in error


def test_ats_cv_docx_export_returns_document_bytes():
    content = export_ats_cv_docx_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        "Summary\n- Python APIs\n- PostgreSQL",
    )

    assert content.startswith(b"PK")
    assert len(content) > 1000


def test_ats_cv_pdf_export_returns_document_bytes():
    content = export_ats_cv_pdf_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        "Summary\nPython APIs\nPostgreSQL",
    )

    assert content.startswith(b"%PDF")
    assert len(content) > 1000


def test_ats_cv_export_strips_internal_optimization_notes():
    content = export_ats_cv_pdf_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        "ATS CV - Backend Engineer\nIgnacio Rodriguez\n\x7f Python APIs\nOptimization notes\n- Internal note",
    )

    from pypdf import PdfReader
    from io import BytesIO

    text = PdfReader(BytesIO(content)).pages[0].extract_text()
    assert "Ignacio Rodriguez" in text
    assert "Optimization notes" not in text
    assert "Internal note" not in text
    assert "\x7f" not in text
