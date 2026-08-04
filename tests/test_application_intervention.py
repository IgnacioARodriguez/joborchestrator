from __future__ import annotations

from joborchestrator.automation.intervention import policy_intervention_items


def test_policy_interventions_expose_legal_consent() -> None:
    items = policy_intervention_items(
        {
            "answers": [
                {
                    "field_name": "privacy_consent",
                    "label": "I agree to the privacy policy",
                    "canonical_key": "privacy_consent",
                    "field_type": "checkbox",
                    "value": "yes",
                    "source": "approved_answer",
                }
            ]
        }
    )

    assert items == [
        {
            "type": "consent",
            "field": "privacy_consent",
            "label": "I agree to the privacy policy",
            "reason": "legal_consent_reserved_for_user",
            "semantic_category": "privacy_acknowledgement",
            "required": False,
            "sensitive": False,
        }
    ]


def test_policy_interventions_expose_optional_demographics() -> None:
    items = policy_intervention_items(
        {
            "answers": [
                {
                    "field_name": "gender",
                    "label": "Gender",
                    "canonical_key": "gender",
                    "field_type": "select",
                    "value": "Prefer not to say",
                    "source": "approved_answer",
                }
            ]
        }
    )

    assert items[0]["type"] == "demographic"
    assert items[0]["reason"] == "optional_demographic_reserved_for_user"


def test_policy_interventions_ignore_authorized_answers() -> None:
    items = policy_intervention_items(
        {
            "answers": [
                {
                    "field_name": "email",
                    "label": "Email",
                    "canonical_key": "email",
                    "field_type": "text",
                    "value": "candidate@example.com",
                    "source": "profile",
                }
            ]
        }
    )

    assert items == []
