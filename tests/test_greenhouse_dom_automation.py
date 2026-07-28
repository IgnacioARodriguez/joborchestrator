from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from joborchestrator.automation.adapters import GreenhouseAdapter
from joborchestrator.automation.executor import (
    _cleanup_resume_upload_file,
    classify_browser_action,
    detect_forbidden_submit_controls,
    fill_safe_fields_on_page,
    resolve_resume_upload_file,
    upload_resume_on_page,
)


def test_greenhouse_dom_schema_discovers_supported_controls() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    schema = asyncio.run(_extract_schema(html))
    fields = {field["name"]: field for field in schema["fields"]}

    assert schema["provider"] == "greenhouse"
    assert fields["first_name"]["type"] == "text"
    assert fields["email"]["type"] == "email"
    assert fields["phone"]["type"] == "text"
    assert fields["linkedin"]["type"] == "url"
    assert fields["portfolio"]["type"] == "url"
    assert fields["cover_letter"]["type"] == "textarea"
    assert fields["location"]["type"] == "select"
    assert fields["work_authorization"]["type"] == "radio"
    assert fields["talent_pool"]["type"] == "checkbox"
    assert fields["resume"]["type"] == "file"
    assert "hidden_tracking" not in fields
    assert "disabled_field" not in fields


def test_greenhouse_dom_schema_marks_required_sensitive_and_options() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    schema = asyncio.run(_extract_schema(html))
    fields = {field["name"]: field for field in schema["fields"]}

    assert fields["first_name"]["required"] is True
    assert fields["salary"]["required"] is True
    assert fields["salary"]["sensitive"] is True
    assert fields["work_authorization"]["sensitive"] is True
    assert fields["location"]["options"] == [
        {"value": "", "label": "Select one"},
        {"value": "remote", "label": "Remote"},
        {"value": "madrid", "label": "Madrid"},
    ]
    assert fields["work_authorization"]["options"] == [
        {"value": "yes", "label": "Yes"},
        {"value": "no", "label": "No"},
    ]
    assert fields["first_name"]["locator_strategy"] == "label_for"


def test_greenhouse_safe_dom_fill_handles_text_select_and_checkbox_without_sensitive_radio() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    result = asyncio.run(_fill_schema(html))

    assert result["first_name"] == "Synthetic Candidate"
    assert result["email"] == "candidate@example.test"
    assert result["location"] == "madrid"
    assert result["talent_pool"] is True
    assert result["salary"] == ""
    assert result["work_authorization_checked"] == []
    assert result["fields_autofilled"] >= 4


def test_greenhouse_resume_upload_uses_generated_pdf_and_cleans_temporary_file(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "resume-upload.db"
    monkeypatch.setattr("joborchestrator.storage.persistence.DB_PATH", db_path)
    from joborchestrator.storage import persistence as db
    from test_api_endpoints import make_job

    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\n"
            "Synthetic backend engineer.\n\n"
            "Technical Skills\n"
            "Python, FastAPI, PostgreSQL.\n\n"
            "Professional Experience\n"
            "Built reliable APIs.\n\n"
            "Education\n"
            "Synthetic degree."
        ),
    )
    job = db.get_job_posting(job_id)
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")

    result = asyncio.run(_upload_resume(html, int(job["id"]), job))

    assert result["status"] == "uploaded"
    assert result["filename"].endswith(".pdf")
    assert result["selected_file_name"] == result["filename"]
    assert result["selected_file_size"] > 100
    assert result["resume_variant_id"] is not None
    assert not Path(result["cleanup_path"]).exists()


def test_resume_upload_is_unresolved_without_generated_cv() -> None:
    result = resolve_resume_upload_file(1, {"company": "Acme", "title": "Backend Engineer"})

    assert result == {"status": "unresolved", "reason": "missing_ats_cv_text"}


def test_submit_controls_are_forbidden_and_not_clicked() -> None:
    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8").replace(
        "<button type=\"submit\">Submit application</button>",
        "<button type=\"submit\" onclick=\"window.__submitted = true\">Submit application</button>",
    )
    result = asyncio.run(_detect_submit_guard(html))

    assert classify_browser_action("Submit application") == "forbidden"
    assert classify_browser_action("Enviar candidatura") == "forbidden"
    assert classify_browser_action("Apply now") == "safe"
    assert result["controls"] == [
        {"tag": "button", "text": "Submit application", "action_policy": "forbidden"}
    ]
    assert result["submitted"] is False


async def _extract_schema(html: str) -> dict:
    adapter = GreenhouseAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            assert await adapter.detect_page(page)
            return await adapter.extract_form_schema_page(page)
        finally:
            await browser.close()


async def _detect_submit_guard(html: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            controls = await detect_forbidden_submit_controls(page)
            submitted = await page.evaluate("() => Boolean(window.__submitted)")
            return {"controls": controls, "submitted": submitted}
        finally:
            await browser.close()


async def _upload_resume(html: str, job_id: int, job: dict) -> dict:
    adapter = GreenhouseAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            schema = await adapter.extract_form_schema_page(page)
            resume_file = resolve_resume_upload_file(job_id, job)
            upload = await upload_resume_on_page(page, schema, resume_file)
            selected = await page.evaluate(
                """() => {
                  const file = document.querySelector('[name="resume"]').files[0];
                  return { selected_file_name: file?.name || null, selected_file_size: file?.size || 0 };
                }"""
            )
            cleanup_path = str(upload.get("cleanup_path") or "")
            _cleanup_resume_upload_file(cleanup_path)
            return {**upload, **selected, "cleanup_path": cleanup_path}
        finally:
            await browser.close()


async def _fill_schema(html: str) -> dict:
    adapter = GreenhouseAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            schema = await adapter.extract_form_schema_page(page)
            mapping = adapter.map_answers(
                schema,
                {
                    "full_name": "Synthetic Candidate",
                    "email": "candidate@example.test",
                    "phone": "+34 000 000 000",
                    "linkedin": "https://www.linkedin.com/in/synthetic",
                    "portfolio_url": "https://example.test",
                },
                [
                    {
                        "canonical_key": "preferred_location",
                        "value": "Madrid",
                        "source": "approved",
                        "sensitivity": "public",
                        "requires_confirmation": False,
                    },
                    {
                        "canonical_key": "talent_pool",
                        "value": "yes",
                        "source": "approved",
                        "sensitivity": "public",
                        "requires_confirmation": False,
                    },
                    {
                        "canonical_key": "work_authorization",
                        "value": "yes",
                        "source": "approved",
                        "sensitivity": "sensitive",
                        "requires_confirmation": True,
                    },
                ],
            )
            fill = await fill_safe_fields_on_page(page, mapping, dry_run=True)
            values = await page.evaluate(
                """() => ({
                  first_name: document.querySelector('[name="first_name"]').value,
                  email: document.querySelector('[name="email"]').value,
                  location: document.querySelector('[name="location"]').value,
                  talent_pool: document.querySelector('[name="talent_pool"]').checked,
                  salary: document.querySelector('[name="salary"]').value,
                  work_authorization_checked: Array.from(document.querySelectorAll('[name="work_authorization"]:checked')).map(node => node.value),
                })"""
            )
            return {**values, **fill}
        finally:
            await browser.close()
