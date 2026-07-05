from joborchestrator.intelligence.evaluation_framework import build_af_evaluation
from joborchestrator.intelligence.cover_letter_generator import (
    build_cover_letter_payload,
    export_cover_letter_pdf,
)
from joborchestrator.intelligence.ats_autofill import build_autofill_plan


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
    assert plan["questions"]
    assert any("Why" in q["question"] for q in plan["questions"])
    assert plan["copy_paste_block"]
    assert plan["field_mappings"]
    assert "resume" in plan["field_mappings"]


def test_pdf_export_creates_file(tmp_path):
    output_path = tmp_path / "cover_letter.pdf"
    created = export_cover_letter_pdf("Hello world", output_path)
    assert created is True
    assert output_path.exists()
