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
from joborchestrator.automation.validation import validate_application_surface


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


def test_dom_schema_discovers_aria_custom_controls() -> None:
    schema = asyncio.run(_extract_schema(_aria_custom_controls_html()))
    fields = {field["name"]: field for field in schema["fields"]}

    assert fields["location-combobox"]["key"] == "preferred_location"
    assert fields["location-combobox"]["type"] == "select"
    assert fields["location-combobox"]["locator_strategy"] == "aria_role"
    assert fields["location-combobox"]["options"] == [
        {"value": "Remote", "label": "Remote"},
        {"value": "Madrid", "label": "Madrid"},
    ]
    assert "location-options" not in fields
    assert fields["work_mode"]["type"] == "radio"
    assert fields["work_mode"]["options"] == [
        {"value": "Remote", "label": "Remote"},
        {"value": "Hybrid", "label": "Hybrid"},
    ]
    assert fields["talent-pool"]["key"] == "talent_pool"
    assert fields["talent-pool"]["type"] == "checkbox"


def test_safe_dom_fill_handles_aria_custom_controls() -> None:
    result = asyncio.run(_fill_aria_custom_controls())

    assert result["location_value"] == "Madrid"
    assert result["work_mode"] == "Remote"
    assert result["talent_pool"] is True
    assert result["validation"]["status"] == "validation_clean"
    assert result["fields_autofilled"] == 3


def test_dom_schema_and_fill_traverse_open_shadow_roots() -> None:
    result = asyncio.run(_fill_open_shadow_form())

    assert result["fields"]["first_name"]["type"] == "text"
    assert result["fields"]["location"]["type"] == "select"
    assert result["fields"]["talent_pool"]["type"] == "checkbox"
    assert result["first_name"] == "Synthetic Candidate"
    assert result["location"] == "madrid"
    assert result["talent_pool"] is True
    assert result["validation"]["status"] == "validation_clean"
    assert result["fields_autofilled"] == 3


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


def test_dom_schema_discovers_file_upload_widget_without_native_input() -> None:
    schema = asyncio.run(_extract_schema(_file_chooser_upload_html()))
    fields = {field["name"]: field for field in schema["fields"]}

    assert fields["resume_upload"]["type"] == "file"
    assert fields["resume_upload"]["locator_strategy"] == "file_widget"


def test_resume_upload_uses_file_chooser_widget(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "resume-upload-widget.db"
    monkeypatch.setattr("joborchestrator.storage.persistence.DB_PATH", db_path)
    from joborchestrator.storage import persistence as db
    from test_api_endpoints import make_job

    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.update_job_application_materials(
        job_id,
        ats_cv_text=(
            "Professional Summary\nSynthetic backend engineer.\n\n"
            "Technical Skills\nPython, FastAPI.\n\n"
            "Professional Experience\nBuilt reliable APIs.\n\n"
            "Education\nSynthetic degree."
        ),
    )
    job = db.get_job_posting(job_id)

    result = asyncio.run(_upload_resume_with_widget(_file_chooser_upload_html(), int(job["id"]), job))

    assert result["status"] == "uploaded"
    assert result["strategy"] == "file_chooser"
    assert result["selected_file_name"] == result["filename"]
    assert result["selected_file_size"] > 100
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


async def _upload_resume_with_widget(html: str, job_id: int, job: dict) -> dict:
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
                  const file = document.querySelector('input[type="file"]')?.files?.[0];
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


async def _fill_aria_custom_controls() -> dict:
    adapter = GreenhouseAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_aria_custom_controls_html())
            schema = await adapter.extract_form_schema_page(page)
            mapping = adapter.map_answers(
                schema,
                {},
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
                        "value": "Remote",
                        "source": "approved",
                        "sensitivity": "public",
                        "requires_confirmation": False,
                    },
                ],
            )
            # Keep this role-specific answer local to avoid teaching the global resolver a portal-specific alias.
            for answer in mapping["answers"]:
                if answer["field_name"] == "work_mode":
                    answer["canonical_key"] = "work_authorization"
                    answer["source"] = "approved_answer"
                    answer["value"] = "Remote"
                    answer["requires_confirmation"] = False
            fill = await fill_safe_fields_on_page(page, mapping, dry_run=True)
            validation = await validate_application_surface(
                page,
                {
                    "expected_postconditions": [
                        {"field_name": "location-combobox", "action_type": "select_option"},
                        {"field_name": "work_mode", "action_type": "choose_radio"},
                        {"field_name": "talent-pool", "action_type": "check"},
                    ]
                },
            )
            values = await page.evaluate(
                """() => ({
                  location_value: document.getElementById('location-combobox').getAttribute('data-selected'),
                  work_mode: document.querySelector('[role="radio"][aria-checked="true"]')?.textContent?.trim() || '',
                  talent_pool: document.getElementById('talent-pool').getAttribute('aria-checked') === 'true',
                })"""
            )
            return {**values, **fill, "validation": validation.to_dict()}
        finally:
            await browser.close()


def _aria_custom_controls_html() -> str:
    return """
    <!doctype html>
    <html>
      <body>
        <form id="application_form">
          <label id="location-label">Preferred Location *</label>
          <div
            id="location-combobox"
            role="combobox"
            aria-labelledby="location-label"
            aria-controls="location-options"
            aria-required="true"
            onclick="document.getElementById('location-options').style.display='block'"
          ></div>
          <div id="location-options" role="listbox" style="display:block">
            <div role="option" onclick="document.getElementById('location-combobox').setAttribute('data-selected', 'Remote')">Remote</div>
            <div role="option" onclick="document.getElementById('location-combobox').setAttribute('data-selected', 'Madrid')">Madrid</div>
          </div>

          <div id="work-mode-label">Work Mode *</div>
          <div role="radiogroup" id="work_mode" aria-labelledby="work-mode-label" aria-required="true">
            <div role="radio" aria-checked="false" onclick="this.setAttribute('aria-checked', 'true')">Remote</div>
            <div role="radio" aria-checked="false" onclick="this.setAttribute('aria-checked', 'true')">Hybrid</div>
          </div>

          <div id="talent-pool" role="checkbox" aria-label="Talent Pool" onclick="this.setAttribute('aria-checked', 'true')">Talent Pool</div>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """


async def _fill_open_shadow_form() -> dict:
    adapter = GreenhouseAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(_open_shadow_form_html())
            schema = await adapter.extract_form_schema_page(page)
            mapping = adapter.map_answers(
                schema,
                {"full_name": "Synthetic Candidate"},
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
                ],
            )
            fill = await fill_safe_fields_on_page(page, mapping, dry_run=True)
            validation = await validate_application_surface(
                page,
                {
                    "expected_postconditions": [
                        {"field_name": "first_name", "action_type": "fill_text"},
                        {"field_name": "location", "action_type": "select_option"},
                        {"field_name": "talent_pool", "action_type": "check"},
                    ]
                },
            )
            values = await page.evaluate(
                """() => {
                  const root = document.querySelector('shadow-application').shadowRoot;
                  return {
                    first_name: root.querySelector('[name="first_name"]').value,
                    location: root.querySelector('[name="location"]').value,
                    talent_pool: root.querySelector('[name="talent_pool"]').checked,
                  };
                }"""
            )
            return {
                **values,
                **fill,
                "fields": {field["name"]: field for field in schema["fields"]},
                "validation": validation.to_dict(),
            }
        finally:
            await browser.close()


def _open_shadow_form_html() -> str:
    return """
    <!doctype html>
    <html>
      <body>
        <form id="application_form">
          <shadow-application></shadow-application>
          <button type="submit">Submit application</button>
        </form>
        <script>
          customElements.define('shadow-application', class extends HTMLElement {
            connectedCallback() {
              const root = this.attachShadow({ mode: 'open' });
              root.innerHTML = `
                <label for="first_name">First Name *</label>
                <input id="first_name" name="first_name" required>
                <label for="location">Preferred Location *</label>
                <select id="location" name="location" required>
                  <option value="">Select one</option>
                  <option value="remote">Remote</option>
                  <option value="madrid">Madrid</option>
                </select>
                <label><input id="talent_pool" name="talent_pool" type="checkbox" value="yes"> Talent Pool</label>
              `;
            }
          });
        </script>
      </body>
    </html>
    """


def _file_chooser_upload_html() -> str:
    return """
    <!doctype html>
    <html>
      <body>
        <form id="application_form">
          <button
            id="resume_upload"
            type="button"
            aria-label="Upload resume"
            onclick="
              const input = document.createElement('input');
              input.type = 'file';
              input.name = 'resume_upload';
              input.style.display = 'none';
              document.body.appendChild(input);
              input.click();
            "
          >Upload resume</button>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """
