from __future__ import annotations

import json
from pathlib import Path


def test_application_corpus_declares_expected_obligations_and_terminal_states() -> None:
    corpus = json.loads(Path("tests/fixtures/application_corpus.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]

    assert len(cases) >= 5
    assert {case["expected_terminal_state"] for case in cases} >= {"SUBMIT_ONLY", "NEEDS_USER_INPUT"}
    for case in cases:
        assert case["known_controls"]
        assert case["required_controls"]
        assert isinstance(case["expected_answers"], dict)
        assert "auto_submit" in case["forbidden_actions"]
        assert "final_submit" in case["reserved_actions"]
        assert case["expected_human_interventions"]
