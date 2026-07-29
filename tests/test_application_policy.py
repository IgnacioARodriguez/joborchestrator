from __future__ import annotations

from joborchestrator.automation.policy import evaluate_answer_action, evaluate_browser_action


def test_policy_reserves_legal_consent_even_with_approved_answer() -> None:
    decision = evaluate_answer_action(
        {
            "field_name": "privacy_consent",
            "label": "I agree to the privacy policy and certify my answers are accurate",
            "canonical_key": "privacy_consent",
            "field_type": "checkbox",
            "value": "yes",
            "source": "approved_answer",
        },
        action="check",
    )

    assert decision.outcome == "REVIEW_REQUIRED"
    assert decision.reason_code == "legal_consent_reserved_for_user"
    assert decision.semantic_category == "privacy_acknowledgement"


def test_policy_allows_work_authorization_without_generic_authorization_false_positive() -> None:
    decision = evaluate_answer_action(
        {
            "field_name": "work_authorization",
            "label": "Do you have permanent authorization to work in the United States?",
            "canonical_key": "work_authorization",
            "field_type": "radio",
            "value": "yes",
            "source": "approved_answer",
        },
        action="choose_radio",
    )

    assert decision.outcome == "ALLOW"
    assert decision.reason_code == "work_authorization_approved_answer"


def test_policy_blocks_background_check_authorization() -> None:
    decision = evaluate_answer_action(
        {
            "field_name": "background_check",
            "label": "I authorize the company to run a background check",
            "canonical_key": "background_check",
            "field_type": "checkbox",
            "value": "yes",
            "source": "approved_answer",
        },
        action="check",
    )

    assert decision.outcome == "REVIEW_REQUIRED"
    assert decision.semantic_category == "background_check_authorization"


def test_policy_denies_challenge_automation() -> None:
    decision = evaluate_answer_action(
        {
            "field_name": "captcha",
            "label": "Please complete the CAPTCHA",
            "field_type": "text",
            "value": "solved",
            "source": "approved_answer",
        },
        action="fill_text",
    )

    assert decision.outcome == "DENY"
    assert decision.reason_code == "captcha_automation_denied"


def test_policy_reserves_final_submit() -> None:
    decision = evaluate_browser_action("Submit application")

    assert decision.outcome == "REVIEW_REQUIRED"
    assert decision.reason_code == "final_submit_reserved_for_user"
