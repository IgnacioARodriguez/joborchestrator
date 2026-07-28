from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from joborchestrator.automation.validation import validate_application_surface


def test_validation_detects_browser_invalid_and_visible_errors() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <input name="email" type="email" value="not-an-email" required>
          <div class="field-error">Use a valid email address.</div>
        </form>
      </body>
    </html>
    """

    report = asyncio.run(_validate(html, {"expected_postconditions": []}))
    data = report.to_dict()

    assert data["status"] == "validation_failed"
    assert any(issue["field_name"] == "email" and issue["issue_type"] == "browser_invalid" for issue in data["issues"])
    assert any(issue["issue_type"] == "visible_error" for issue in data["issues"])


def test_validation_ignores_invalid_controls_outside_action_plan() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <input name="email" type="email" value="candidate@example.test" required>
          <input name="unplanned_required" required>
        </form>
      </body>
    </html>
    """

    report = asyncio.run(
        _validate(
            html,
            {
                "expected_postconditions": [
                    {"field_name": "email", "action_type": "fill_text", "surface_id": "main"}
                ]
            },
        )
    )
    data = report.to_dict()

    assert data["status"] == "validation_clean"
    assert data["issues"] == []


def test_validation_accepts_dry_run_fill_marker() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <input name="first_name" value="" data-joborchestrator-dry-run="filled">
        </form>
      </body>
    </html>
    """

    report = asyncio.run(
        _validate(
            html,
            {
                "expected_postconditions": [
                    {"field_name": "first_name", "action_type": "fill_text", "surface_id": "main"}
                ]
            },
        )
    )
    data = report.to_dict()

    assert data["status"] == "validation_clean"
    assert data["checked_postconditions"] == 1
    assert data["satisfied_postconditions"] == 1


def test_validation_detects_failed_postcondition_when_value_is_cleared() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form>
          <input name="linkedin" type="url" value="">
        </form>
      </body>
    </html>
    """

    report = asyncio.run(
        _validate(
            html,
            {
                "expected_postconditions": [
                    {"field_name": "linkedin", "action_type": "fill_text", "surface_id": "main"}
                ]
            },
        )
    )
    data = report.to_dict()

    assert data["status"] == "validation_failed"
    assert data["checked_postconditions"] == 1
    assert data["satisfied_postconditions"] == 0
    assert data["issues"] == [
        {
            "field_name": "linkedin",
            "issue_type": "postcondition_failed",
            "message": "Field value was not retained.",
            "surface_id": "main",
            "action_type": "fill_text",
        }
    ]


async def _validate(html: str, action_plan: dict):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            return await validate_application_surface(page, action_plan)
        finally:
            await browser.close()
