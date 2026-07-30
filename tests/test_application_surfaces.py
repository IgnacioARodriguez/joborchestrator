from __future__ import annotations

from joborchestrator.automation.journey import _with_control_handles
from joborchestrator.automation.surfaces import rebind_control


def test_logical_control_identity_rebinds_after_dynamic_id_change() -> None:
    original = _with_control_handles(
        {
            "fields": [
                {
                    "id": "react-select-1-input",
                    "name": "react-select-1-input",
                    "label": "Preferred Location",
                    "key": "preferred_location",
                    "type": "select",
                    "required": True,
                    "options": [{"value": "remote", "label": "Remote"}, {"value": "madrid", "label": "Madrid"}],
                }
            ]
        },
        "main",
    )
    rerendered = _with_control_handles(
        {
            "fields": [
                {
                    "id": "react-select-42-input",
                    "name": "react-select-42-input",
                    "label": "Preferred Location",
                    "key": "preferred_location",
                    "type": "select",
                    "required": True,
                    "options": [{"value": "remote", "label": "Remote"}, {"value": "madrid", "label": "Madrid"}],
                }
            ]
        },
        "main",
    )

    identity = original["fields"][0]["control_handle"]["logical_identity"]
    rebound = rebind_control(rerendered, identity)

    assert rebound is not None
    assert rebound["name"] == "react-select-42-input"


def test_logical_control_identity_fails_closed_for_ambiguous_rebind() -> None:
    original = _with_control_handles(
        {"fields": [{"name": "first", "label": "Website", "key": "portfolio", "type": "url", "required": True}]},
        "main",
    )
    ambiguous = _with_control_handles(
        {
            "fields": [
                {"name": "portfolio_a", "label": "Website", "key": "portfolio", "type": "url", "required": True},
                {"name": "portfolio_b", "label": "Website", "key": "portfolio", "type": "url", "required": True},
            ]
        },
        "main",
    )

    identity = original["fields"][0]["control_handle"]["logical_identity"]

    assert rebind_control(ambiguous, identity) is None
