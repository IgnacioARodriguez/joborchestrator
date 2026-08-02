from joborchestrator.intelligence.evaluation_framework import build_af_evaluation
from joborchestrator.intelligence.cover_letter_generator import (
    build_cover_letter_payload,
    export_cover_letter_pdf,
)
from joborchestrator.intelligence.ats_autofill import build_autofill_plan
from joborchestrator.intelligence.llm_application_materials import (
    LLMMaterialsError,
    _call_openai,
    _call_nvidia_kit,
    _ats_cv_response_validation_error,
    _build_ats_fit_analysis,
    _experience_coverage_problems,
    _experience_density_problems,
    _experience_technology_attribution_problems,
    _kit_from_response,
    _kit_validation_error,
    _materials_validation_error,
    _materials_payload,
    _materials_schema,
    _materials_repair_instruction,
    _materials_validation_retry_limit,
    _openai_materials_messages,
    build_application_kit_with_llm,
    build_application_kit_with_nvidia,
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

    def fake_call(payload, api_key, model, timeout, **kwargs):
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
        {
            "final_score": 82,
            "decision": "APPLY_NOW",
            "cv_keywords_to_emphasize": ["Python"],
            "cv_keywords_to_avoid_overclaiming": ["Serverless Architecture"],
        },
    )

    assert payload["ranking"]["final_score"] == 82
    assert payload["ranking"]["decision"] == "APPLY_NOW"
    assert payload["ranking_constraints"]["avoid_overclaiming_terms"] == ["Serverless Architecture"]
    assert payload["ranking_constraints"]["keywords_to_emphasize"] == ["Python"]
    assert "AWS Lambda" in payload["ranking_constraints"]["avoid_overclaiming_aliases"]["Serverless Architecture"]


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


def test_openai_materials_schema_requires_structured_autofill():
    schema = _materials_schema()

    assert "autofill" in schema["required"]
    assert "autofill_notes" not in schema["required"]
    assert schema["properties"]["autofill"]["additionalProperties"] is False
    assert schema["properties"]["autofill"]["properties"]["availability"]["type"] == ["string", "null"]


def test_application_kit_renders_structured_autofill_object():
    kit = _kit_from_response(
        {
            "recruiter_message": "Hi Acme, Python API work maps well to the Backend Engineer role.",
            "cover_letter": "Dear Acme team",
            "ats_cv_text": "Professional Summary\nBackend engineer",
            "autofill": {
                "core_pitch": "Python backend profile for API and automation work.",
                "availability": "Two weeks after offer acceptance.",
                "work_authorization": "Authorized to work in Spain.",
                "location_note": "Madrid-based, open to remote EU teams.",
                "application_caveats": ["Confirm exact cloud stack before claiming direct AWS production depth."],
            },
        }
    )

    assert "Python backend profile" in kit["autofill_notes"]
    assert "Availability: Two weeks" in kit["autofill_notes"]
    assert "Work authorization: Authorized" in kit["autofill_notes"]
    assert "Location: Madrid" in kit["autofill_notes"]
    assert "Caveats: Confirm exact cloud stack" in kit["autofill_notes"]


def test_application_kit_validation_rejects_json_encoded_autofill_notes():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Acme, Python API work maps well to the Backend Engineer role.",
            "cover_letter": "Dear Acme team,\n\nMy Python API background maps well to this Backend Engineer role through backend services, database work, and product collaboration on reliable application workflows.",
            "autofill_notes": '{"core_pitch": "Python API profile"}',
        },
        {"job": {"title": "Backend Engineer", "company": "Acme"}},
    )

    assert error is not None
    assert "autofill_notes must not be a JSON-encoded object string" in error


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


def test_kit_validation_rejects_language_mismatch_for_supported_job_language():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Acme, my developer experience maps well to this remote team role.",
            "cover_letter": "Dear Acme team,\n\nMy experience as a backend developer maps well to this remote team role, with responsibilities across APIs, product collaboration, and reliable delivery for business workflows.",
            "autofill_notes": "Experience as a developer on remote work, team responsibilities, and backend delivery.",
        },
        {
            "job": {
                "title": "Desarrollador Python remoto",
                "description_text": "Requisitos experiencia trabajo remoto jornada equipo desarrollo Python.",
            }
        },
    )

    assert error is not None
    assert "application materials language mismatch" in error


def test_kit_validation_does_not_reject_unsupported_job_language_signal():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Acme, Python API work maps well to this role.",
            "cover_letter": "Dear Acme team,\n\nMy Python API background maps well to this role through backend services, database work, and product collaboration on reliable application workflows.",
            "autofill_notes": "Use the Python API angle for portal questions.",
        },
        {"job": {"title": "Python", "description_text": "Build APIs."}},
    )

    assert error is None


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
            "cover_letter": "Dear Acme Labs team,\n\nMy Python API background maps well to the Backend Engineer role, with practical experience building backend services, collaborating with product teams, and delivering reliable application workflows.",
            "ats_cv_text": _complete_ats_cv_text(),
            "autofill_notes": "Use tailored answers.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={"job": {"title": "Backend Engineer", "company": "Acme Labs"}},
    )

    assert error is None


def test_recruiter_message_validation_rejects_messages_over_golden_limit():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Acme Labs, " + ("Python backend fit. " * 20),
            "cover_letter": "",
            "ats_cv_text": _complete_ats_cv_text(),
            "autofill_notes": "Use tailored answers.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={"job": {"title": "Backend Engineer", "company": "Acme Labs"}},
    )

    assert error is not None
    assert "recruiter_message is too long" in error


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
    assert "cover_letter is required" in error
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
    assert "/18" in error


def test_materials_repair_instruction_expands_short_ats_cv():
    instruction = _materials_repair_instruction(
        "ats_cv_text is too short to be a complete ATS CV; ats_cv_text has too few parseable lines for a complete CV"
    )

    assert "complete ATS CV" in instruction
    assert "700 characters" in instruction
    assert "normally 18 non-empty lines" in instruction
    assert "16-17 well-structured lines" in instruction
    assert "every base CV employer" in instruction


def test_llm_application_kit_validation_accepts_short_single_role_complete_ats_cv():
    base_cv = """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com

Professional Experience
Backend Developer 2024 - 2026
LeanOps
- Built Python API integrations for operations teams.
- Documented deployment and support workflows.

Education
Software Engineering.
""".strip()
    ats_cv_text = """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com
Professional Summary
Backend developer focused on Python API integrations and operations workflows.
Experienced documenting deployment and support workflows with careful delivery.
Technical Skills
Languages: Python
Backend: REST APIs, API integrations
Tools: Django, Docker, documentation
Professional Experience
Backend Developer | LeanOps | 2024 - 2026
- Built Python API integrations for operations teams, supporting reliable operations workflows.
- Documented deployment and support workflows so teams could operate integrations consistently.
Education
Software Engineering.
Additional Development
Ongoing practice in backend delivery, API documentation, and operations support.
""".strip()

    error = _materials_validation_error(
        {
            "recruiter_message": "Hi LeanOps, my Python API integration background may fit this role.",
            "cover_letter": (
                "I can support LeanOps through source-backed Python API integration experience, including "
                "building integrations for operations teams and documenting deployment and support workflows. "
                "The attached CV keeps the scope concise because the base source is intentionally short."
            ),
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Use the API integrations and documentation angle.",
            "risk_flags": [],
            "keywords_used": ["API integrations", "documentation", "operations workflows"],
        },
        source_payload={
            "base_cv": {"text": base_cv},
            "candidate_profile": {"real_experience_years": 2},
            "ranking_constraints": {"avoid_overclaiming_terms": []},
        },
    )

    assert error is None


def test_ats_fit_analysis_treats_truthful_keyword_variants_as_supported():
    analysis = _build_ats_fit_analysis(
        {
            "title": "API Integration Developer",
            "description_text": "Develop API integrations, write documentation, and support operations workflows.",
        },
        {
            "strong_skills": ["Python", "REST APIs"],
            "medium_skills": [],
            "weak_skills": [],
        },
        """
Professional Experience
Backend Developer 2024 - 2026
LeanOps
- Built Python API integrations for operations teams.
- Documented deployment and support workflows.
""",
        {
            "cv_keywords_to_emphasize": ["API integrations", "documentation", "operations workflows"],
            "cv_keywords_to_avoid_overclaiming": [],
        },
    )

    assert "API integrations" in analysis["supported_keywords"]
    assert "documentation" in analysis["supported_keywords"]
    assert "operations workflows" in analysis["supported_keywords"]
    assert "operations workflows" not in analysis["adjacent_or_review_keywords"]


def test_llm_application_kit_validation_rejects_keywords_used_not_in_ats_cv_text():
    base_cv = """
Professional Experience
Backend Developer 2024 - 2026
LeanOps
- Built Python API integrations for operations teams.
- Documented deployment and support workflows.
""".strip()
    ats_cv_text = """
Ignacio Rodriguez
Madrid, Spain | ignacio@example.com
Professional Summary
Backend developer with 2 years of Python API integrations experience.
Experienced documenting deployment workflows and supporting operations teams.
Technical Skills
Languages: Python
Backend: REST APIs, API integrations
Tools: Django, Docker, documentation
Professional Experience
Backend Developer | LeanOps | 2024 - 2026
- Built Python API integrations for operations teams to enhance workflow automation.
- Documented deployment and support workflows for operational clarity.
Education
Software Engineering.
Additional Development
Ongoing backend delivery practice.
""".strip()

    error = _materials_validation_error(
        {
            "recruiter_message": "Hi LeanOps, my Python API integration background may fit this role.",
            "cover_letter": (
                "I can support LeanOps through source-backed Python API integration experience, including "
                "building integrations and documenting deployment workflows for operations teams."
            ),
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Use the API integrations and documentation angle.",
            "risk_flags": [],
            "keywords_used": ["API integrations", "documentation", "operations workflows"],
        },
        source_payload={
            "base_cv": {"text": base_cv},
            "candidate_profile": {"real_experience_years": 2},
            "ranking_constraints": {"avoid_overclaiming_terms": []},
        },
    )

    assert error is not None
    assert "keywords_used contains terms not present as normalized token-aware phrases in ats_cv_text" in error
    assert "operations workflows" in error


def test_materials_repair_instruction_expands_overcompressed_ats_cv():
    instruction = _materials_repair_instruction("ats_cv_text is overcompressed for base CV experience roles")

    assert "more source-backed detail" in instruction
    assert "recent and substantial roles" in instruction
    assert "Do not add unsupported new claims" in instruction


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
            "cover_letter": "Dear hiring team,\n\nMy backend engineering background maps well to this role through Python API work, database collaboration, and reliable product delivery across cross-functional teams.",
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Paste the recruiter note.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        }
    )

    assert error is None


def test_openai_materials_call_reports_validation_retry_metadata(monkeypatch):
    calls = []

    def fake_call_once(payload, api_key, model, timeout, validation_feedback=None):
        calls.append(validation_feedback)
        if validation_feedback:
            return {
                "recruiter_message": "Hi Acme Labs, my backend API work maps well to the Backend Engineer role.",
                "cover_letter": "Dear Acme Labs team,\n\nMy backend API experience maps well to the Backend Engineer role through Python services, product collaboration, and reliable delivery practices.",
                "ats_cv_text": _complete_ats_cv_text(),
                "autofill_notes": "Paste the recruiter note.",
                "risk_flags": [],
                "keywords_used": ["Python"],
            }
        return {
            "recruiter_message": "",
            "cover_letter": "",
            "ats_cv_text": "Tiny",
            "autofill_notes": "",
            "risk_flags": [],
            "keywords_used": [],
        }

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(llm_application_materials, "DEFAULT_MATERIALS_VALIDATION_RETRIES", 1)
    monkeypatch.setattr(llm_application_materials, "_call_openai_once", fake_call_once)

    response = _call_openai(
        {"job": {"title": "Backend Engineer", "company": "Acme Labs"}, "base_cv": {"text": _complete_ats_cv_text()}},
        "test-key",
        "test-model",
        1.0,
    )

    assert calls[0] is None
    assert calls[1]
    assert response["_generation_metadata"]["validation_attempts"] == 2
    assert response["_generation_metadata"]["validation_errors"]


def test_materials_validation_retry_limit_uses_global_semantic_cap(monkeypatch):
    monkeypatch.setenv("MATERIALS_MAX_SEMANTIC_REPAIRS", "1")

    retry_limit = _materials_validation_retry_limit(
        {
            "ranking_constraints": {
                "avoid_overclaiming_terms": [
                    "Serverless Architecture",
                    "Terraform/AWS CDK/CloudFormation",
                ]
            },
            "application_tone_constraints": {"tone": "cautious_review"},
            "experience_claim_constraints": [
                {"canonical_role_technologies": ["Python", "PHP", "JavaScript", "SQL", "APIs"]}
            ],
        }
    )

    assert retry_limit == 1


def test_openai_materials_call_allows_explicit_validation_retry_limit(monkeypatch):
    calls = []

    def fake_call_once(payload, api_key, model, timeout, validation_feedback=None):
        calls.append(validation_feedback)
        return {
            "recruiter_message": "",
            "cover_letter": "",
            "ats_cv_text": "Tiny",
            "autofill_notes": "",
            "risk_flags": [],
            "keywords_used": [],
        }

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(llm_application_materials, "DEFAULT_MATERIALS_VALIDATION_RETRIES", 6)
    monkeypatch.setattr(llm_application_materials, "_call_openai_once", fake_call_once)

    try:
        _call_openai(
            {"job": {"title": "Backend Engineer", "company": "Acme Labs"}, "base_cv": {"text": _complete_ats_cv_text()}},
            "test-key",
            "test-model",
            1.0,
            validation_retry_limit=0,
        )
    except LLMMaterialsError as exc:
        metadata = exc.generation_metadata
    else:
        raise AssertionError("Expected LLMMaterialsError")

    assert len(calls) == 1
    assert metadata["validation_attempts"] == 1
    assert metadata["validation_errors"]


def test_nvidia_kit_failure_reports_validation_metadata(monkeypatch):
    calls = []

    def fake_contract_once(contract, payload, api_key, model, timeout, validation_feedback=None):
        calls.append(validation_feedback)
        return {
            "recruiter_message": "Hi PSS, I would treat this as an exploratory conversation about fit.",
            "cover_letter": (
                "Dear hiring team,\n\n"
                "I am excited about this backend opportunity and eager to discuss how my Python API experience "
                "could support the team while we review the exact cloud scope together."
            ),
            "autofill_notes": "I am excited to discuss the role.",
        }

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(llm_application_materials, "DEFAULT_MATERIALS_VALIDATION_RETRIES", 1)
    monkeypatch.setattr(llm_application_materials, "MAX_MATERIALS_VALIDATION_RETRIES", 1)
    monkeypatch.setattr(llm_application_materials, "_call_nvidia_contract_once", fake_contract_once)

    payload = {
        "job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        "base_cv": {"text": _complete_ats_cv_text()},
        "ranking": {"decision": "APPLY_WITH_TAILORED_CV"},
        "application_tone_constraints": {
            "ranking_decision": "APPLY_WITH_TAILORED_CV",
            "tone": "cautious_review",
            "forbidden_phrases": ["excited about", "excited to", "eager to"],
        },
    }

    try:
        _call_nvidia_kit(payload, "test-key", "test-model", 1.0, validation_retry_limit=1)
    except LLMMaterialsError as exc:
        metadata = exc.generation_metadata
    else:
        raise AssertionError("Expected LLMMaterialsError")

    assert calls[0] is None
    assert calls[1]
    assert metadata["validation_attempts"] == 2
    assert len(metadata["validation_errors"]) == 2
    assert "overconfident tone" in metadata["validation_errors"][-1]


def test_nvidia_cv_request_failure_preserves_prior_validation_metadata(monkeypatch):
    calls = []

    def fake_contract_once(contract, payload, api_key, model, timeout, validation_feedback=None):
        calls.append(validation_feedback)
        if validation_feedback:
            raise LLMMaterialsError("NVIDIA materials request failed: ReadTimeout")
        return {
            "ats_cv_text": "Tiny",
            "risk_flags": [],
            "keywords_used": [],
        }

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(llm_application_materials, "_call_nvidia_contract_once", fake_contract_once)

    try:
        llm_application_materials._call_nvidia_cv(
            {"job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"}, "base_cv": {"text": _complete_ats_cv_text()}},
            "test-key",
            "test-model",
            1.0,
            validation_retry_limit=1,
        )
    except LLMMaterialsError as exc:
        metadata = exc.generation_metadata
    else:
        raise AssertionError("Expected LLMMaterialsError")

    assert calls[0] is None
    assert calls[1]
    assert metadata["validation_attempts"] == 2
    assert len(metadata["validation_errors"]) == 2
    assert "ats_cv_text is too short" in metadata["validation_errors"][0]
    assert "request failed during validation attempt 2" in metadata["validation_errors"][1]
    assert "ReadTimeout" in metadata["validation_errors"][1]


def test_nvidia_application_kit_failure_combines_partial_generation_metadata(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setenv("MATERIALS_CONTROLLED_CV_ENABLED", "0")
    monkeypatch.setenv("MATERIALS_NVIDIA_PLANNER_ENABLED", "0")
    monkeypatch.setattr(
        llm_application_materials,
        "_materials_payload",
        lambda job, ranking: {"job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"}},
    )
    monkeypatch.setattr(
        llm_application_materials,
        "_call_nvidia_cv",
        lambda payload, api_key, model, timeout, **kwargs: {
            "ats_cv_text": _complete_ats_cv_text(),
            "_generation_metadata": {
                "validation_attempts": 2,
                "validation_errors": ["ats_cv_text initially missed canonical technologies"],
            },
        },
    )

    def fail_kit(payload, api_key, model, timeout, **kwargs):
        raise LLMMaterialsError(
            "NVIDIA kit response was incomplete: application materials use overconfident tone",
            generation_metadata={
                "validation_attempts": 2,
                "validation_errors": [
                    "application materials use overconfident tone",
                    "application materials use overconfident tone",
                ],
            },
        )

    monkeypatch.setattr(llm_application_materials, "_call_nvidia_kit", fail_kit)

    result = build_application_kit_with_nvidia(
        {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        {"decision": "APPLY_WITH_TAILORED_CV"},
        api_key="test-key",
    )
    metadata = result["_generation_metadata"]

    assert metadata["validation_attempts"] == 4
    assert metadata["validation_errors"] == [
        "ats_cv_text initially missed canonical technologies",
        "application materials use overconfident tone",
        "application materials use overconfident tone",
    ]
    assert metadata["partial_success"] is True
    assert metadata["material_statuses"]["ats_cv"] == "ready"


def test_ats_cv_validation_rejects_ranking_avoid_overclaiming_terms_without_source_support():
    ats_cv_text = _complete_ats_cv_text() + "\n- Kubernetes platform ownership for production clusters."

    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Acme Labs, my backend API work maps well to the Backend Engineer role.",
            "cover_letter": "",
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Paste the recruiter note.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={
            "base_cv": {"text": _complete_ats_cv_text()},
            "candidate_profile": {"skills": [{"name": "Python"}]},
            "ranking": {"cv_keywords_to_avoid_overclaiming": ["Kubernetes"]},
            "job": {"title": "Backend Engineer", "company": "Acme Labs"},
        },
    )

    assert error is not None
    assert "avoid-overclaiming terms: Kubernetes" in error


def test_materials_validation_rejects_serverless_aliases_from_avoid_overclaiming_terms():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi PSS, my Python API work maps well to the AWS Backend role.",
            "cover_letter": "My experience with API Gateway, AWS Lambda, and DynamoDB fits this role.",
            "ats_cv_text": _complete_ats_cv_text()
            + "\nTechnical Skills\nAWS (EC2, Lambda, API Gateway, S3)",
            "autofill_notes": "Lead with Python APIs and AWS-adjacent backend experience.",
            "risk_flags": [],
            "keywords_used": ["Python", "AWS"],
        },
        source_payload={
            "base_cv": {"text": _complete_ats_cv_text() + "\n- Built Python APIs on AWS EC2."},
            "candidate_profile": {"skills": [{"name": "Python"}, {"name": "AWS"}, {"name": "EC2"}]},
            "ranking": {"cv_keywords_to_avoid_overclaiming": ["Serverless Architecture"]},
            "job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        },
    )

    assert error is not None
    assert "application_materials contains unsupported ranking avoid-overclaiming terms" in error
    assert "ats_cv_text contains unsupported ranking avoid-overclaiming terms" in error
    assert "AWS Lambda" in error
    assert "DynamoDB" in error


def test_nvidia_kit_validation_rejects_serverless_aliases_from_cover_letter():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi PSS, my Python API work maps well to the AWS Backend role.",
            "cover_letter": "My experience with API Gateway, AWS Lambda, and DynamoDB fits this role.",
            "autofill_notes": "Use the Python API angle.",
        },
        {
            "base_cv": {"text": _complete_ats_cv_text() + "\n- Built Python APIs on AWS EC2."},
            "candidate_profile": {"skills": [{"name": "Python"}, {"name": "AWS"}, {"name": "EC2"}]},
            "ranking": {"cv_keywords_to_avoid_overclaiming": ["Serverless Architecture"]},
            "job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        },
    )

    assert error is not None
    assert "application_materials contains unsupported ranking avoid-overclaiming terms" in error
    assert "AWS Lambda" in error


def test_materials_validation_rejects_unsupported_years_of_experience_claims():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Datosur, my Python API background may fit the Backend role.",
            "cover_letter": "My Python API and SQL reporting experience maps to the role.",
            "ats_cv_text": _complete_ats_cv_text().replace("with 4+ years of experience", "with backend experience"),
            "autofill_notes": "Backend developer with 4+ years of experience in Python APIs.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={
            "base_cv": {"text": "Professional Experience\nBackend Developer 04/2022 - 03/2026\nAcme\n- Built APIs."},
            "candidate_profile": {"skills": [{"name": "Python"}]},
            "ranking": {},
            "job": {"title": "Backend Developer", "company": "Datosur"},
        },
    )

    assert error is not None
    assert "unsupported years-of-experience claims" in error
    assert "4+ years" in error


def test_materials_validation_allows_declared_years_of_experience_claims():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Acme, my Python API background may fit the Backend role.",
            "cover_letter": (
                "I bring 4+ years of backend experience with Python APIs and reporting workflows. "
                "That background maps to the role through practical backend delivery, documentation, "
                "and collaboration with product and operations teams."
            ),
            "autofill_notes": "Use the Python API angle.",
        },
        {
            "base_cv": {"text": "Professional Experience\nBackend Developer\n- Built APIs."},
            "candidate_profile": {"real_experience_years": 4, "skills": [{"name": "Python"}]},
            "ranking": {},
            "job": {"title": "Backend Developer", "company": "Acme"},
        },
    )

    assert error is None


def test_materials_payload_exposes_avoid_overclaiming_aliases(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "base_cv_text": _complete_ats_cv_text() + "\n- Built Python APIs on AWS EC2.",
            "skills": [{"name": "Python"}, {"name": "AWS"}, {"name": "EC2"}],
            "experience": [],
            "education": [],
        },
    )

    payload = _materials_payload(
        {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        {"cv_keywords_to_avoid_overclaiming": ["Serverless Architecture"]},
    )

    aliases = payload["ranking_constraints"]["avoid_overclaiming_aliases"]["Serverless Architecture"]
    assert "AWS Lambda" in aliases
    assert "DynamoDB" in aliases
    assert "API Gateway" in aliases


def test_materials_payload_exposes_experience_claim_constraints(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "base_cv_text": """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs with Python, REST APIs, SQL, and MongoDB.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards with Python, Flask, React, SQL, and Docker.
TECHNICAL SKILLS
Django
AWS
""".strip(),
            "skills": [{"name": "Python"}, {"name": "Django"}, {"name": "AWS"}],
            "experience": [],
            "education": [],
        },
    )

    payload = _materials_payload({"title": "Backend Engineer", "company": "Acme"})

    fiction = payload["experience_claim_constraints"][0]
    assert fiction["employer"] == "Fiction Express Malaga, Spain"
    assert "MongoDB" in fiction["supported_role_technologies"]
    assert fiction["canonical_role_technologies"] == []
    assert "Django" not in fiction["supported_role_technologies"]
    assert "AWS" not in fiction["supported_role_technologies"]


def test_materials_payload_exposes_cautious_tone_constraints(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "base_cv_text": _complete_ats_cv_text(),
            "skills": [{"name": "Python"}],
            "experience": [],
            "education": [],
        },
    )

    payload = _materials_payload(
        {"title": "Python Developer", "company": "Hire Feed"},
        {
            "decision": "SKIP",
            "evidence": {"dealbreakers": ["contract AI training/verification work"], "red_flags": []},
        },
    )

    assert payload["application_tone_constraints"]["ranking_decision"] == "SKIP"
    assert payload["application_tone_constraints"]["tone"] == "cautious_review"
    assert "immediate impact" in payload["application_tone_constraints"]["forbidden_phrases"]
    assert "worth discussing if the contract context fits" in payload["application_tone_constraints"]["allowed_phrases"]
    assert payload["application_tone_constraints"]["rewrite_strategy"].startswith("exploratory_review")


def test_materials_payload_exposes_ats_fit_analysis(monkeypatch):
    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(
        llm_application_materials.db,
        "get_candidate_profile_payload",
        lambda: {
            "base_cv_text": _complete_ats_cv_text(),
            "skills": [{"name": "Python"}, {"name": "FastAPI"}, {"name": "AWS"}],
            "experience": [],
            "education": [],
        },
    )

    payload = _materials_payload(
        {
            "title": "AWS Backend / Cloud Developer",
            "company": "PSS",
            "description_text": "Build Python and FastAPI services with Kubernetes and Terraform.",
        },
        {
            "cv_keywords_to_emphasize": ["Python", "FastAPI", "Kubernetes"],
            "cv_keywords_to_avoid_overclaiming": ["Terraform/AWS CDK/CloudFormation"],
        },
    )

    analysis = payload["ats_fit_analysis"]
    assert "Python" in analysis["supported_keywords"]
    assert "FastAPI" in analysis["supported_keywords"]
    assert "Terraform" in analysis["avoid_keywords"]
    assert "Kubernetes" in analysis["adjacent_or_review_keywords"]
    assert analysis["rules"]


def test_kit_validation_rejects_empty_or_degenerate_cover_letter():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Acme Labs, my Python API work maps well to the Backend Engineer role.",
            "cover_letter": "",
            "autofill_notes": "Use the Python API angle.",
        },
        {"job": {"title": "Backend Engineer", "company": "Acme Labs"}},
    )

    assert error is not None
    assert "cover_letter is required" in error


def test_kit_validation_rejects_overconfident_tone_for_skip_ranking():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Hire Feed, my Python work may be relevant to review for the Python Developer role.",
            "cover_letter": (
                "Dear Hire Feed team,\n\nI'm confident my skills will make an immediate impact on the role, "
                "and I am eager to enhance next-generation AI systems through this work."
            ),
            "autofill_notes": "Position as a strong fit with immediate impact.",
        },
        {
            "job": {"title": "Python Developer", "company": "Hire Feed"},
            "ranking": {
                "decision": "SKIP",
                "evidence": {"dealbreakers": ["contract AI training/verification work"]},
            },
        },
    )

    assert error is not None
    assert "overconfident tone for SKIP ranking" in error
    assert "immediate impact" in error


def test_kit_validation_rejects_internal_review_language():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi Hire Feed, my Python backend work may be relevant to review for the role.",
            "cover_letter": (
                "Dear Hire Feed team,\n\nMy Python backend background may be relevant to review for this role, "
                "although I understand the safety gate concern highlighted in your system."
            ),
            "autofill_notes": "Mention the dealbreaker only if asked.",
        },
        {"job": {"title": "Python Developer", "company": "Hire Feed"}},
    )

    assert error is not None
    assert "internal review/evaluation language" in error
    assert "safety gate" in error


def test_materials_validation_rejects_ats_opaque_implied_hedges():
    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Hire Feed, my Python backend work may be relevant to review for the role.",
            "cover_letter": (
                "Dear Hire Feed team,\n\nMy Python backend background may be relevant to review for this role, "
                "with supported experience around APIs, data workflows, and practical automation."
            ),
            "ats_cv_text": _complete_ats_cv_text() + "\nTechnical Skills\nAWS (EC2, implied through experience)",
            "autofill_notes": "If asked about Next.js, adaptability can be implied from React experience.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={"job": {"title": "Python Developer", "company": "Hire Feed"}},
    )

    assert error is not None
    assert "ATS-opaque unsupported hedge language" in error


def test_materials_validation_rejects_slash_separated_avoid_aliases():
    error = _kit_validation_error(
        {
            "recruiter_message": "Hi PSS, my Python API work maps well to the AWS Backend role.",
            "cover_letter": "",
            "autofill_notes": "Mention Terraform as a target-stack gap, not as direct experience.",
        },
        {
            "base_cv": {"text": _complete_ats_cv_text() + "\n- Built Python APIs on AWS EC2."},
            "candidate_profile": {"skills": [{"name": "Python"}, {"name": "AWS"}, {"name": "EC2"}]},
            "ranking": {"cv_keywords_to_avoid_overclaiming": ["Terraform/AWS CDK/CloudFormation"]},
            "job": {"title": "AWS Backend / Cloud Developer", "company": "PSS"},
        },
    )

    assert error is not None
    assert "Terraform/AWS CDK/CloudFormation" in error
    assert "Terraform" in error


def test_ats_cv_validation_allows_ranking_avoid_term_when_source_supports_it():
    source_cv = _complete_ats_cv_text() + "\n- Supported Kubernetes-adjacent deployment work."
    ats_cv_text = _complete_ats_cv_text() + "\n- Supported Kubernetes-adjacent deployment work."

    error = _materials_validation_error(
        {
            "recruiter_message": "Hi Acme Labs, my backend API work maps well to the Backend Engineer role.",
            "cover_letter": "Dear Acme Labs team,\n\nMy backend API background maps well to this Backend Engineer role through Python delivery, Kubernetes-adjacent deployment support, and reliable collaboration.",
            "ats_cv_text": ats_cv_text,
            "autofill_notes": "Paste the recruiter note.",
            "risk_flags": [],
            "keywords_used": ["Python"],
        },
        source_payload={
            "base_cv": {"text": source_cv},
            "candidate_profile": {"skills": [{"name": "Python"}, {"name": "Kubernetes"}]},
            "ranking": {"cv_keywords_to_avoid_overclaiming_json": '["Kubernetes"]'},
            "job": {"title": "Backend Engineer", "company": "Acme Labs"},
        },
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


def test_ats_cv_validation_rejects_overcompressed_experience_detail():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
- Collaborated with product managers on backend requirements.
- Documented backend processes and runbooks.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards for finance teams.
- Developed reporting tools for market data.
- Automated manual reporting workflows.
- Designed SQL queries and backend integrations.
- Connected internal data sources and dashboards.
Backend Developer August 2022 - October 2022
Globant Client: Tigo LATAM Buenos Aires, Argentina
- Built AWS microservices.
- Optimized backend APIs.
PROJECTS
AI Automation
""".strip()
    compressed_cv = """
Professional Summary
Backend developer focused on Python APIs and dashboards.
Technical Skills
Python, SQL, MongoDB, AWS.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards.
Backend Developer | Globant (Client: Tigo LATAM) | August 2022 - October 2022
- Built AWS microservices.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, compressed_cv)

    assert problems
    assert "overcompressed" in problems[-1]
    assert "Fiction Express" in problems[-1]
    assert "Talan" in problems[-1]


def test_ats_cv_validation_counts_real_cv_unicode_bullets():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
• Built analytics APIs for product workflows.
• Developed reporting pipelines for student activity.
• Improved SQL and MongoDB queries for product metrics.
• Collaborated with product managers on backend requirements.
• Documented backend processes and runbooks.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
• Built dashboards for finance teams.
• Developed reporting tools for market data.
• Automated manual reporting workflows.
• Designed SQL queries and backend integrations.
• Connected internal data sources and dashboards.
PROJECTS
AI Automation
""".strip()
    compressed_cv = """
Professional Summary
Backend developer focused on Python APIs and dashboards.
Technical Skills
Python, SQL, MongoDB, AWS.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, compressed_cv)

    assert problems
    assert "Fiction Express" in problems[-1]
    assert "Talan" in problems[-1]


def test_ats_cv_density_parser_handles_common_experience_headings_and_dates():
    base_cv = """
Work Experience
Backend Developer Apr 2025 - Mar 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
Full Stack Developer 2022 - 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards for finance teams.
- Developed reporting tools for market data.
- Automated manual reporting workflows.
Education
Software Engineering.
""".strip()
    compressed_cv = """
Professional Summary
Backend developer.
Technical Skills
Python, SQL.
Professional Experience
Backend Developer | Fiction Express | Apr 2025 - Mar 2026
- Built analytics APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | 2022 - 2025
- Built dashboards.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, compressed_cv)

    assert problems
    assert "density validation was not applied" not in problems[0]
    assert "overcompressed" in problems[-1]


def test_ats_cv_density_warns_when_long_base_experience_cannot_be_parsed():
    base_cv = "EXPERIENCE\n" + "\n".join(
        f"Long unparseable role detail line {index} with backend APIs, reporting, data pipelines, dashboards, and operations."
        for index in range(30)
    )

    problems = _experience_density_problems(base_cv, "Professional Experience\n- Short generated CV.")

    assert problems
    assert "density validation was not applied" in problems[0]


def test_ats_cv_density_warns_when_experience_heading_is_unknown():
    base_cv = "Career Journey\n" + "\n".join(
        f"Backend Developer 04/2022 - 03/2025\nAcme Systems\n- Built API, reporting, data, and dashboard workflows for team {index}."
        for index in range(16)
    )

    problems = _experience_density_problems(base_cv, "Professional Experience\n- Short generated CV.")

    assert problems
    assert "density validation was not applied" in problems[0]


def test_ats_cv_density_warns_for_short_unknown_experience_heading():
    base_cv = """
Career Journey
Backend Developer 04/2022 - 03/2025
Acme Systems
- Built APIs.
- Built reports.
- Built dashboards.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, "Professional Experience\n- Short generated CV.")

    assert problems
    assert "density validation was not applied" in problems[0]


def test_ats_cv_density_does_not_require_more_bullets_than_source():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
Education
Software Engineering.
""".strip()
    generated_cv = """
Professional Summary
Backend developer focused on Python APIs, reporting, and product data workflows.
Technical Skills
Python, SQL, MongoDB, APIs, dashboards, documentation.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
Education
Software Engineering.
""".strip()

    assert _experience_density_problems(base_cv, generated_cv) == []


def test_ats_cv_density_validates_single_experience_role():
    base_cv = """
Professional Experience
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
- Collaborated with product managers on backend requirements.
Education
Software Engineering.
""".strip()
    generated_cv = """
Professional Summary
Backend developer.
Technical Skills
Python, SQL.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, generated_cv)

    assert problems
    assert "Fiction Express" in problems[-1]


def test_ats_cv_rejects_omitted_single_experience_role():
    base_cv = """
Professional Experience
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
Education
Software Engineering.
""".strip()
    generated_cv = """
Professional Summary
Backend developer focused on Python APIs and product data workflows.
Technical Skills
Python, SQL, MongoDB.
Professional Experience
Project Consultant | Independent | 2022 - 2025
- Supported internal reporting workflows.
Education
Software Engineering.
""".strip()

    coverage = _experience_coverage_problems(base_cv, generated_cv)
    density = _experience_density_problems(base_cv, generated_cv)

    assert coverage
    assert "Fiction Express" in coverage[0]
    assert density
    assert "missing from generated experience" in density[-1]


def test_ats_cv_density_requires_at_least_one_bullet_for_short_source_role():
    base_cv = """
Professional Experience
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
Education
Software Engineering.
""".strip()
    generated_cv = """
Professional Summary
Backend developer focused on API delivery.
Technical Skills
Python, SQL.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
Backend services and analytics workflows.
Education
Software Engineering.
""".strip()

    problems = _experience_density_problems(base_cv, generated_cv)

    assert problems
    assert "expected at least 1" in problems[-1]


def test_nvidia_cv_density_parse_failure_returns_degraded_review_cv(monkeypatch):
    calls = []
    base_cv = "Career Journey\n" + "\n".join(
        f"Backend Developer 04/2022 - 03/2025\nAcme Systems\n- Built API, reporting, data, and dashboard workflows for team {index}."
        for index in range(16)
    )

    def fake_contract_once(contract, payload, api_key, model, timeout, validation_feedback=None):
        calls.append(validation_feedback)
        return {
            "ats_cv_text": _complete_ats_cv_text(),
            "risk_flags": [],
            "keywords_used": ["Python"],
        }

    from joborchestrator.intelligence import llm_application_materials

    monkeypatch.setattr(llm_application_materials, "_call_nvidia_contract_once", fake_contract_once)

    result = llm_application_materials._call_nvidia_cv(
        {"job": {"title": "Backend Engineer", "company": "Acme"}, "base_cv": {"text": base_cv}},
        "test-key",
        "test-model",
        1.0,
        validation_retry_limit=3,
    )
    metadata = result["_generation_metadata"]

    assert calls == [None]
    assert metadata["validation_attempts"] == 1
    assert metadata["human_review_required"] is True
    assert metadata["experience_density_validation"] == "skipped"
    assert "density validation was not applied" in metadata["validation_errors"][0]


def test_ats_cv_keywords_used_presence_is_token_aware():
    payload = {
        "ats_cv_text": _complete_ats_cv_text().replace("SQL", "NoSQL").replace("APIs", "API integrations"),
        "risk_flags": [],
        "keywords_used": ["SQL"],
    }

    error = _ats_cv_response_validation_error(payload, base_cv_text="")

    assert error
    assert "keywords_used contains terms not present" in error


def test_ats_cv_validation_accepts_reasonable_experience_compression():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
- Collaborated with product managers on backend requirements.
- Documented backend processes and runbooks.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards for finance teams.
- Developed reporting tools for market data.
- Automated manual reporting workflows.
- Designed SQL queries and backend integrations.
- Connected internal data sources and dashboards.
PROJECTS
AI Automation
""".strip()
    compressed_cv = """
Professional Summary
Backend developer focused on Python APIs, data workflows, and internal dashboards.
Technical Skills
Python, SQL, MongoDB, APIs, dashboards, documentation.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs for product workflows.
- Developed reporting pipelines for student activity.
- Improved SQL and MongoDB queries for product metrics.
- Collaborated with product managers on backend requirements.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards for finance teams.
- Developed reporting tools for market data.
- Automated manual reporting workflows.
Education
Software Engineering.
""".strip()

    assert _experience_density_problems(base_cv, compressed_cv) == []


def test_ats_cv_validation_rejects_role_specific_technology_drift():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs with Python, REST APIs, SQL, and MongoDB.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards with Python, Flask, React, SQL, and Docker.
PROJECTS
AI Automation
TECHNICAL SKILLS
Django
FastAPI
AWS
""".strip()
    ats_cv = """
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs with Python and REST APIs.
- Technologies: Python, Django, FastAPI, AWS, SQL, MongoDB.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards with Python, Flask, React, SQL, and Docker.
Education
Software Engineering.
""".strip()

    problems = _experience_technology_attribution_problems(base_cv, ats_cv)

    assert problems
    assert "Fiction Express" in problems[0]
    assert "Django" in problems[0]
    assert "FastAPI" in problems[0]
    assert "AWS" in problems[0]


def test_ats_cv_validation_allows_global_skills_outside_role_blocks():
    base_cv = """
EXPERIENCE
Backend Developer April 2025 - March 2026
Fiction Express Malaga, Spain
- Built analytics APIs with Python, REST APIs, SQL, and MongoDB.
Full Stack Developer October 2022 - April 2025
Talan Consulting Client: Cepsa Malaga, Spain
- Built dashboards with Python, Flask, React, SQL, and Docker.
PROJECTS
AI Automation
TECHNICAL SKILLS
Django
FastAPI
AWS
""".strip()
    ats_cv = """
Professional Summary
Backend developer with Django, FastAPI, and AWS exposure.
Technical Skills
Python, Django, FastAPI, AWS, SQL, MongoDB.
Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs with Python and REST APIs.
Full Stack Developer | Talan Consulting (Client: Cepsa) | October 2022 - April 2025
- Built dashboards with Python, Flask, React, SQL, and Docker.
Education
Software Engineering.
""".strip()

    assert _experience_technology_attribution_problems(base_cv, ats_cv) == []


def test_ats_cv_validation_rejects_missing_canonical_role_technologies():
    base_cv = """
EXPERIENCE
Full Stack Developer November 2021 - August 2022
Balloon Group Buenos Aires, Argentina
- Developed web applications and backend services for international clients.
- Technologies: Python, PHP, JavaScript, SQL, APIs.
Backend Developer August 2022 - October 2022
Globant Client: Tigo LATAM Buenos Aires, Argentina
- Technologies: Python, AWS, REST APIs.
""".strip()
    ats_cv = """
Professional Experience
Full Stack Developer | Balloon Group | November 2021 - August 2022
- Developed web applications and backend services for international clients.
- Technologies: PHP.
Backend Developer | Globant (Client: Tigo LATAM) | August 2022 - October 2022
- Technologies: Python, AWS, REST APIs.
Education
Software Engineering.
""".strip()

    problems = _experience_technology_attribution_problems(base_cv, ats_cv)

    assert problems
    assert "Balloon Group" in problems[0]
    assert "missing canonical role technologies" in problems[0]
    assert "Python" in problems[0]
    assert "JavaScript" in problems[0]
    assert "SQL" in problems[0]


def test_ats_cv_docx_export_returns_document_bytes():
    content = export_ats_cv_docx_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        "Summary\n- Python APIs\n- PostgreSQL",
    )

    assert content.startswith(b"PK")
    assert len(content) > 1000


def test_ats_cv_docx_export_keeps_parseable_text():
    content = export_ats_cv_docx_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        _complete_ats_cv_text(),
    )

    from docx import Document
    from io import BytesIO

    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "PROFESSIONAL SUMMARY" in text
    assert "Fiction Express" in text
    assert "PROFESSIONAL EXPERIENCE" in text
    assert "EDUCATION" in text


def test_ats_cv_pdf_export_returns_document_bytes():
    content = export_ats_cv_pdf_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        "Ignacio Rodriguez\nMadrid, Spain\nProfessional Summary\nPython APIs\nTechnical Skills\nPostgreSQL",
    )

    assert content.startswith(b"%PDF")
    assert len(content) > 1000


def test_ats_cv_pdf_export_keeps_parseable_headings():
    content = export_ats_cv_pdf_bytes(
        {"title": "Backend Engineer", "company": "Acme"},
        _complete_ats_cv_text(),
    )

    from pypdf import PdfReader
    from io import BytesIO

    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    assert "Ignacio Rodriguez" in text
    assert "PROFESSIONAL SUMMARY" in text
    assert "TECHNICAL SKILLS" in text
    assert "PROFESSIONAL EXPERIENCE" in text
    assert "EDUCATION" in text


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
