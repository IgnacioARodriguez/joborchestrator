from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from joborchestrator.automation.adapters import GenericFormAdapter
from joborchestrator.automation.journey import ApplicationJourneyEngine, build_action_plan


def test_action_plan_allows_profile_and_approved_answers_only() -> None:
    plan = build_action_plan(
        provider="generic_form",
        schema={
            "fields": [
                {"name": "name", "type": "text", "required": True},
                {"name": "location", "type": "select", "required": True},
                {"name": "salary", "type": "text", "required": True},
            ]
        },
        mapping={
            "answers": [
                {
                    "field_name": "name",
                    "canonical_key": "full_name",
                    "field_type": "text",
                    "value": "Synthetic Candidate",
                    "source": "confirmed_profile",
                    "requires_confirmation": False,
                },
                {
                    "field_name": "location",
                    "canonical_key": "preferred_location",
                    "field_type": "select",
                    "value": "Remote",
                    "source": "approved_answer",
                    "requires_confirmation": False,
                    "options": [{"value": "remote", "label": "Remote"}],
                },
                {
                    "field_name": "salary",
                    "canonical_key": "salary",
                    "field_type": "text",
                    "value": "100000",
                    "source": None,
                    "requires_confirmation": True,
                },
            ],
            "unknown_fields": [{"name": "salary", "required": True}],
        },
    )

    serialized = plan.to_dict()
    assert serialized["summary"] == {
        "actions": 2,
        "unresolved": 1,
        "forbidden": 0,
        "expected_postconditions": 2,
    }
    assert [action["action_type"] for action in serialized["actions"]] == ["fill_text", "select_option"]
    assert serialized["unresolved"] == [{"name": "salary", "required": True}]
    assert serialized["form_fingerprint"] == "name:text:True|location:select:True|salary:text:True"


def test_action_plan_requires_review_when_choice_option_does_not_match() -> None:
    plan = build_action_plan(
        provider="generic_form",
        schema={"fields": [{"name": "location", "type": "select", "required": True}]},
        mapping={
            "answers": [
                {
                    "field_name": "location",
                    "canonical_key": "preferred_location",
                    "field_type": "select",
                    "value": "Remote",
                    "source": "approved_answer",
                    "requires_confirmation": False,
                    "options": [{"value": "madrid", "label": "Madrid"}],
                }
            ],
            "unknown_fields": [],
        },
    )

    assert plan.actions == []
    assert plan.forbidden == []
    assert plan.to_dict()["summary"]["actions"] == 0


def test_journey_engine_prepares_initial_generic_step() -> None:
    html = Path("tests/fixtures/generic_application.html").read_text(encoding="utf-8")
    step = asyncio.run(_prepare_step(html))

    serialized = step.to_dict()
    assert serialized["phase"] == "actions_planned"
    assert serialized["surface"]["kind"] == "page"
    assert serialized["schema"]["provider"] == "generic_form"
    assert serialized["action_plan"]["provider"] == "generic_form"
    assert serialized["action_plan"]["summary"]["actions"] >= 2
    assert serialized["action_plan"]["form_fingerprint"]


def test_journey_engine_selects_accessible_frame_surface() -> None:
    html = """
    <!doctype html>
    <html>
      <body>
        <h1>Job details</h1>
        <iframe srcdoc='
          <form id="application">
            <label for="name">Full name *</label>
            <input id="name" name="name" required>
            <label for="email">Email *</label>
            <input id="email" name="email" type="email" required>
            <label for="resume">Resume *</label>
            <input id="resume" name="resume" type="file" required>
            <button type="submit">Submit application</button>
          </form>
        '></iframe>
      </body>
    </html>
    """
    step = asyncio.run(_prepare_step(html))
    serialized = step.to_dict()

    assert serialized["surface"]["kind"] == "frame"
    assert serialized["surface"]["surface_id"].startswith("frame:")
    assert [field["name"] for field in serialized["schema"]["fields"]] == ["name", "email", "resume"]
    assert all(field["surface_id"] == serialized["surface"]["surface_id"] for field in serialized["schema"]["fields"])
    assert serialized["schema"]["fields"][0]["control_handle"]["surface_id"] == serialized["surface"]["surface_id"]
    assert serialized["action_plan"]["actions"][0]["surface_id"] == serialized["surface"]["surface_id"]


async def _prepare_step(html: str):
    adapter = GenericFormAdapter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            return await ApplicationJourneyEngine().prepare_initial_step(
                page=page,
                adapter=adapter,
                capabilities=adapter.capabilities(),
                html=html,
                profile={
                    "full_name": "Synthetic Candidate",
                    "email": "candidate@example.test",
                    "phone": "+34 000 000 000",
                    "linkedin_url": "https://www.linkedin.com/in/synthetic",
                },
                answer_bank=[],
            )
        finally:
            await browser.close()
