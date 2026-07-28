from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from joborchestrator.automation.adapters import LeverAdapter
from joborchestrator.automation.executor import (
    _cleanup_resume_upload_file,
    detect_forbidden_submit_controls,
    fill_safe_fields_on_page,
    resolve_resume_upload_file,
    upload_resume_on_page,
)


def test_lever_dom_schema_discovers_supported_controls() -> None:
    html = Path("tests/fixtures/lever_application.html").read_text(encoding="utf-8")
    schema = asyncio.run(_extract_schema(html))
    fields = {field["name"]: field for field in schema["fields"]}

    assert schema["provider"] == "lever"
    assert fields["name"]["type"] == "text"
    assert fields["email"]["type"] == "email"
    assert fields["phone"]["type"] == "tel"
    assert fields["urls[LinkedIn]"]["type"] == "url"
    assert fields["cards[location]"]["type"] == "select"
    assert fields["cards[sponsorship]"]["type"] == "radio"
    assert fields["resume"]["type"] == "file"
    assert "csrf" not in fields


def test_lever_safe_dom_fill_uploads_resume_and_detects_submit(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "lever-upload.db"
    monkeypatch.setattr("joborchestrator.storage.persistence.DB_PATH", db_path)
    from joborchestrator.scanning.models import JobPosting
    from joborchestrator.scanning.normalization import compute_content_hash
    from joborchestrator.storage import persistence as db

    db.init_db()
    apply_url = "https://jobs.lever.co/acme/backend/apply"
    db.upsert_job_posting(
        JobPosting(
            external_id="lever-backend",
            source="lever",
            company="Acme",
            title="Backend Engineer",
            location="Remote",
            apply_url=apply_url,
            description_text="Build APIs with Python and FastAPI.",
            content_hash=compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs with Python and FastAPI.", apply_url),
            raw_payload={"id": "lever-backend"},
        ),
        seen_at="2026-01-01T10:00:00",
    )
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
    html = Path("tests/fixtures/lever_application.html").read_text(encoding="utf-8")

    result = asyncio.run(_fill_upload_and_detect(html, int(job["id"]), job))

    assert result["name"] == "Synthetic Candidate"
    assert result["email"] == "candidate@example.test"
    assert result["linkedin"] == "https://www.linkedin.com/in/synthetic"
    assert result["location"] == "remote"
    assert result["sponsorship_checked"] == []
    assert result["upload"]["status"] == "uploaded"
    assert result["submit_controls"] == [
        {"tag": "button", "text": "Submit application", "action_policy": "forbidden"}
    ]
    assert result["submitted"] is False
    assert result["fill"]["fields_autofilled"] >= 4
    assert not Path(result["upload"]["cleanup_path"]).exists()


async def _extract_schema(html: str) -> dict:
    adapter = LeverAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            assert await adapter.detect_page(page)
            return await adapter.extract_form_schema_page(page)
        finally:
            await browser.close()


async def _fill_upload_and_detect(html: str, job_id: int, job: dict) -> dict:
    adapter = LeverAdapter()
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
                    "linkedin_url": "https://www.linkedin.com/in/synthetic",
                    "portfolio_url": "https://example.test",
                },
                [
                    {
                        "canonical_key": "preferred_location",
                        "value": "Remote",
                        "source": "approved",
                        "sensitivity": "public",
                        "requires_confirmation": False,
                    },
                    {
                        "canonical_key": "sponsorship",
                        "value": "yes",
                        "source": "approved",
                        "sensitivity": "sensitive",
                        "requires_confirmation": True,
                    },
                ],
            )
            fill = await fill_safe_fields_on_page(page, mapping, dry_run=True)
            upload = await upload_resume_on_page(page, schema, resolve_resume_upload_file(job_id, job))
            submit_controls = await detect_forbidden_submit_controls(page)
            values = await page.evaluate(
                """() => ({
                  name: document.querySelector('[name="name"]').value,
                  email: document.querySelector('[name="email"]').value,
                  linkedin: document.querySelector('[name="urls[LinkedIn]"]').value,
                  location: document.querySelector('[name="cards[location]"]').value,
                  sponsorship_checked: Array.from(document.querySelectorAll('[name="cards[sponsorship]"]:checked')).map(node => node.value),
                  submitted: Boolean(window.__submitted),
                })"""
            )
            cleanup_path = str(upload.get("cleanup_path") or "")
            _cleanup_resume_upload_file(cleanup_path)
            return {**values, "fill": fill, "upload": {**upload, "cleanup_path": cleanup_path}, "submit_controls": submit_controls}
        finally:
            await browser.close()
