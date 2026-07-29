from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from joborchestrator.automation.adapters import GenericFormAdapter, GreenhouseAdapter


def test_generic_form_adapter_selects_best_application_form() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="job-search">
          <label for="q">Search jobs</label>
          <input id="q" name="q" type="search">
          <button type="submit">Search</button>
        </form>
        <form id="application">
          <label for="name">Full name *</label>
          <input id="name" name="name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required>
          <label for="linkedin">LinkedIn</label>
          <input id="linkedin" name="linkedin" type="url">
          <label for="resume">Resume *</label>
          <input id="resume" name="resume" type="file" required>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    schema = asyncio.run(_extract_schema(GenericFormAdapter(), html))

    assert schema["selected_form_index"] == 1
    assert [field["name"] for field in schema["fields"]] == ["name", "email", "linkedin", "resume"]
    assert len(schema["form_candidates"]) == 2
    assert schema["form_candidates"][1]["score"] > schema["form_candidates"][0]["score"]


def test_greenhouse_adapter_does_not_pick_login_form_before_application_form() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <form id="login">
          <label for="username">Email</label>
          <input id="username" name="username" type="email">
          <label for="password">Password</label>
          <input id="password" name="password" type="password">
          <button type="submit">Log in</button>
        </form>
        <form id="application_form">
          <label for="first_name">Full name *</label>
          <input id="first_name" name="first_name" required>
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" required>
          <input id="resume" name="resume" type="file" required>
          <button type="submit">Submit application</button>
        </form>
      </body>
    </html>
    """

    schema = asyncio.run(_extract_schema(GreenhouseAdapter(), html))

    assert schema["selected_form_index"] == 1
    assert [field["name"] for field in schema["fields"]] == ["first_name", "email", "resume"]


async def _extract_schema(adapter, html: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            return await adapter.extract_form_schema_page(page)
        finally:
            await browser.close()
