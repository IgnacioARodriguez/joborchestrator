from __future__ import annotations

import json
from pathlib import Path


def test_application_corpus_declares_expected_obligations_and_terminal_states() -> None:
    corpus = json.loads(Path("tests/fixtures/application_corpus.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]
    inline_fixtures = corpus["inline_fixtures"]

    assert len(cases) >= 21
    assert {case["expected_terminal_state"] for case in cases} >= {"SUBMIT_ONLY", "NEEDS_USER_INPUT"}
    capabilities = {capability for case in cases for capability in case.get("capabilities", [])}
    assert capabilities >= {
        "smartrecruiters_equivalent",
        "popup",
        "modal",
        "spa",
        "open_shadow_dom",
        "custom_select",
        "visual_state_mismatch",
        "first_last_name",
        "headline_rejected_as_full_name",
        "wrong_control_assignment",
        "required_upload_initially_missing",
        "inline_validation",
        "async_validation",
        "idempotency",
        "retry_exhaustion",
        "policy_during_repair",
    }
    for case in cases:
        assert case["known_controls"]
        assert case["required_controls"]
        assert set(case["required_controls"]).issubset(set(case["known_controls"]))
        assert isinstance(case["expected_semantic_mappings"], dict)
        assert isinstance(case["expected_answers"], dict)
        assert isinstance(case["expected_automatable_actions"], list)
        assert "auto_submit" in case["forbidden_actions"]
        assert "final_submit" in case["reserved_actions"]
        assert case["expected_human_interventions"]
        assert isinstance(case["expected_repair_attempts"], int)
        assert isinstance(case["eligible_submit_only"], bool)
        fixture = str(case["fixture"])
        if fixture.startswith("inline_"):
            assert fixture in inline_fixtures
            assert "<" in inline_fixtures[fixture]


def test_application_corpus_repair_ground_truth_has_nonzero_denominators() -> None:
    corpus = json.loads(Path("tests/fixtures/application_corpus.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]

    assert any(case["recoverable_failures"] for case in cases)
    assert any(case["stale_controls"] for case in cases)
