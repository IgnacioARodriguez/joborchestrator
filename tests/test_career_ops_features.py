from joborchestrator.intelligence.evaluation_framework import build_af_evaluation
from joborchestrator.intelligence.cover_letter_generator import (
    build_cover_letter_payload,
    export_cover_letter_pdf,
)
from joborchestrator.intelligence.ats_autofill import build_autofill_plan
from joborchestrator.intelligence.llm_application_materials import (
    _experience_coverage_problems,
    _kit_from_response,
    _materials_validation_error,
    _materials_payload,
    _openai_materials_messages,
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


def test_openai_materials_messages_include_versioned_cv_and_kit_contracts():
    messages = _openai_materials_messages({"job": {"title": "Backend Engineer"}})
    user_content = messages[1]["content"]

    assert "Return a complete ATS-optimized CV" in user_content
    assert "Return lightweight application materials" in user_content
    assert "Context:" in user_content
    assert '"Backend Engineer"' in user_content


def test_llm_materials_payload_accepts_ranking_dict(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "headline": "Backend engineer",
            "target_roles": ["Backend Engineer"],
            "skills": [{"name": "Python", "category": "Programming", "level": "strong"}],
            "base_cv_text": "Ignacio Rodriguez\nBackend engineer\nExperience with Python APIs.",
        },
    )

    payload = _materials_payload(
        {"title": "Backend Engineer", "company": "Acme"},
        {"final_score": 82, "decision": "APPLY_NOW"},
    )

    assert payload["ranking"]["final_score"] == 82
    assert payload["ranking"]["decision"] == "APPLY_NOW"


def test_application_kit_flattens_nested_recruiter_message():
    kit = _kit_from_response(
        {
            "recruiter_message": {"short": "Hi team", "long": "Longer recruiter message"},
            "cover_letter": "",
            "ats_cv_text": "Professional Summary\nBackend engineer",
            "autofill_notes": {"summary": "Use tailored answers", "notes": "Review before submit"},
        }
    )

    assert kit["recruiter_message"] == "Hi team\n\nLonger recruiter message"
    assert "{'short'" not in kit["recruiter_message"]
    assert kit["autofill_notes"] == "Use tailored answers\n\nReview before submit"


def test_application_kit_cleans_internal_ats_cv_notes():
    kit = _kit_from_response(
        {
            "recruiter_message": "Hi Acme, Python backend fit for the Backend Engineer role.",
            "cover_letter": "",
            "ats_cv_text": (
                "Ignacio Rodriguez\n"
                "Professional Summary\n"
                "Backend engineer focused on Python APIs.\n"
                "Optimization notes\n"
                "- Add unsupported Kubernetes certification"
            ),
            "autofill_notes": "Use tailored answers",
        }
    )

    assert "Ignacio Rodriguez" in kit["ats_cv_text"]
    assert "Optimization notes" not in kit["ats_cv_text"]
    assert "unsupported Kubernetes certification" not in kit["ats_cv_text"]


def test_recruiter_message_cleanup_removes_cover_letter_contamination():
    kit = _kit_from_response(
        {
            "recruiter_message": (
                "Hi, I'm Ignacio Rodriguez, a Python/Django backend developer with 4+ years of experience. "
                "I'm interested in the Python Developer role at Hire Feed.\n\n"
                "Dear Hiring Manager, I'm reaching out to express interest in the Python Developer position."
            ),
            "cover_letter": "Dear team",
            "ats_cv_text": "Professional Summary\nBackend engineer",
            "autofill_notes": "Use tailored answers",
        }
    )

    assert "Dear Hiring Manager" not in kit["recruiter_message"]
    assert "reaching out to express interest" not in kit["recruiter_message"]
    assert kit["recruiter_message"].startswith("Hi, I'm Ignacio Rodriguez")


def test_recruiter_message_validation_rejects_generic_message_with_job_context():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi team, my background looks relevant and I would be happy to share my CV.",
            "cover_letter": "",
            "ats_cv_text": _complete_ats_cv_text(),
            "autofill_notes": "Use tailored answers.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={"job": {"title": "Backend Engineer", "company": "Acme Labs"}},
    )

    assert error is not None
    assert "recruiter_message is generic" in error


def test_recruiter_message_validation_accepts_company_or_role_specific_message():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Acme Labs, my Python API work maps well to the Backend Engineer role.",
            "cover_letter": "",
            "ats_cv_text": _complete_ats_cv_text(),
            "autofill_notes": "Use tailored answers.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={"job": {"title": "Backend Engineer", "company": "Acme Labs"}},
    )

    assert error is None


def test_recruiter_message_validation_rejects_cover_letter_style():
    error = _materials_validation_error(
        {
            "recruiter_message": (
                "Hi, I'm Ignacio Rodriguez, a Python/Django backend developer. "
                "Excited about the Python Developer role. "
                "Dear Hiring Manager, I'm reaching out to express interest in the Python Developer position."
            ),
            "cover_letter": "",
            "ats_cv_text": "Tiny",
            "autofill_notes": "Use tailored answers",
            "risk_flags": [],
            "keywords_used": [],
        }
    )

    assert error is not None
    assert "recruiter_message reads like a cover letter" in error


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


def test_llm_application_kit_validation_requires_complete_ats_cv():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi team",
            "cover_letter": "",
            "ats_cv_text": (
                "ATS CV targeting notes\n"
                "Target role: Backend Engineer\n"
                "Python, FastAPI, PostgreSQL\n"
                "Optimization notes\n"
                "- Add better keywords"
            ),
            "autofill_notes": "Paste the recruiter note.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        }
    )

    assert error is not None
    assert "too short to be a complete ATS CV" in error
    assert "missing standard ATS sections" in error
    assert "internal/non-CV notes" in error


def test_llm_application_kit_validation_accepts_complete_parseable_ats_cv():
    ats_cv_text = """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com | linkedin.com/in/ignacio

Professional Summary
Backend engineer focused on Python services, FastAPI APIs, PostgreSQL data models, and reliable delivery for product teams.
Experienced translating business requirements into maintainable systems, improving observability, and collaborating with stakeholders.

Technical Skills
Python, FastAPI, PostgreSQL, REST APIs, Docker, AWS, CI/CD, SQL, Git, monitoring, documentation, stakeholder collaboration.

Professional Experience
Backend Engineer | Acme Labs | 2022 - Present
- Built and maintained Python APIs for internal product workflows used by cross-functional teams.
- Improved PostgreSQL query patterns and service reliability through profiling, indexing, and clearer ownership.
- Partnered with product managers to break requirements into scoped backend deliverables and measurable releases.
- Documented API contracts and operational runbooks to speed onboarding and reduce repeated support questions.

Software Engineer | Example Systems | 2019 - 2022
- Delivered backend features across REST services, data pipelines, and integrations with external platforms.
- Supported production troubleshooting, root-cause analysis, and incremental performance improvements.
- Collaborated with frontend engineers, QA, and business stakeholders in agile delivery cycles.

Education
Computer Science coursework and continuing professional development in backend engineering, cloud systems, and software delivery.
""".strip()
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi team",
            "cover_letter": "",
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Paste the recruiter note.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        }
    )

    assert error is None


def test_ats_cv_validation_rejects_omitted_base_experiences():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards.
Backend Developer August 2022 - October 2022
Globant Client: Tigo LATAM Buenos Aires, Argentina
- Built AWS microservices.
Full Stack Developer November 2021 - August 2022
Balloon Group Buenos Aires, Argentina
- Built web applications.
PROJECTS
AI Automation
""".strip()
    incomplete_cv = """
Ignacio Rodriguez

Professional Summary
Backend developer.

Technical Skills
Python, Django, AWS, PostgreSQL.

Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards.

Education
Software Engineering.
""".strip()

    problems = _experience_coverage_problems(base_cv, incomplete_cv)

    assert problems
    assert "Globant" in problems[0]
    assert "Balloon" in problems[0]


def test_ats_cv_validation_accepts_all_base_experiences():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
Backend Developer August 2022 - October 2022
Globant Client: Tigo LATAM Buenos Aires, Argentina
Full Stack Developer November 2021 - August 2022
Balloon Group Buenos Aires, Argentina
PROJECTS
AI Automation
""".strip()
    complete_cv = """
Professional Summary
Backend developer.
Technical Skills
Python, Django, AWS, PostgreSQL.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards.
Backend Developer | Globant (Client: Tigo LATAM) | August 2022 - October 2022
- Built AWS microservices.
Full Stack Developer | Balloon Group | November 2021 - August 2022
- Built web applications.
Education
Software Engineering.
""".strip()

    assert _experience_coverage_problems(base_cv, complete_cv) == []


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


def _complete_ats_cv_text() -> str:
    return """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com

Professional Summary
Backend engineer focused on Python APIs, FastAPI services, PostgreSQL data models, and reliable product delivery.
Experienced translating requirements into maintainable backend systems and collaborating with product stakeholders.

Technical Skills
Python, FastAPI, Django, PostgreSQL, SQL, REST APIs, AWS, Docker, CI/CD, Git, observability, documentation.

Professional Experience
Backend Engineer | Fiction Express | April 2025 - March 2026
- Built and maintained Python APIs for product workflows and data operations.
- Improved service reliability and backend observability through clearer ownership and documentation.

Full Stack Developer | Talan Consulting | October 2022 - April 2025
- Delivered dashboards, integrations, and SQL-backed features for business users.
- Collaborated with frontend engineers, QA, and product stakeholders across delivery cycles.

Backend Developer | Globant | August 2022 - October 2022
- Supported AWS-based backend services, integrations, and production troubleshooting.

Full Stack Developer | Balloon Group | November 2021 - August 2022
- Built web applications and backend functionality across product delivery cycles.

Education
Software engineering coursework and continuing professional development in backend engineering.
""".strip()
