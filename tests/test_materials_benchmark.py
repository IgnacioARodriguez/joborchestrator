from __future__ import annotations

from pathlib import Path

from scripts.run_materials_controlled_benchmark import run_offline_benchmark


def test_offline_materials_benchmark_reports_all_arms():
    report = run_offline_benchmark(Path("tests/fixtures/materials_evidence_baseline.json"))

    assert report["mode"] == "offline"
    assert [row["arm"] for row in report["arms"]] == ["A", "B", "C", "D", "E"]
    assert report["context_size"]["generation_context_chars"] < report["context_size"]["legacy_context_chars"]
    assert report["arms"][0]["factual_errors"]["overcompressed_cv"] == 10
