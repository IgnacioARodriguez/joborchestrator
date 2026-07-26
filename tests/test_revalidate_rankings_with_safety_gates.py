from __future__ import annotations

import json

from scripts import revalidate_rankings_with_safety_gates as revalidate


def test_revalidation_defaults_to_optimistic_decisions(monkeypatch, capsys):
    calls = {}

    def fake_fetch_rows(**kwargs):
        calls["fetch_rows"] = kwargs
        return []

    monkeypatch.setattr(revalidate, "fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(revalidate, "revalidate_rows", lambda rows: ([], []))

    assert revalidate.main(["--ranking-job-id", "9"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert calls["fetch_rows"]["decisions"] == ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]
    assert output["decisions"] == ["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]


def test_revalidation_decision_flag_overrides_default(monkeypatch, capsys):
    calls = {}

    def fake_fetch_rows(**kwargs):
        calls["fetch_rows"] = kwargs
        return []

    monkeypatch.setattr(revalidate, "fetch_rows", fake_fetch_rows)
    monkeypatch.setattr(revalidate, "revalidate_rows", lambda rows: ([], []))

    assert revalidate.main(["--ranking-job-id", "9", "--decision", "MAYBE"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert calls["fetch_rows"]["decisions"] == ["MAYBE"]
    assert output["decisions"] == ["MAYBE"]
