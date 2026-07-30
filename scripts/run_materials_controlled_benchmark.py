from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.intelligence.materials_context import build_generation_context

ARMS = ["A", "B", "C", "D", "E"]


def run_offline_benchmark(baseline_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    cases = baseline["representative_cases"]
    theme_counts = baseline["validation_error_themes"]
    nvidia_duration = baseline["provider_duration_seconds"]["nvidia"]["avg"]
    openai_duration = baseline["provider_duration_seconds"]["openai"]["avg"]
    return {
        "mode": "offline",
        "case_count": len(cases),
        "source_packet": baseline["source_packet"],
        "arms": [
            _arm_metrics(arm, len(cases), theme_counts, nvidia_duration, openai_duration)
            for arm in ARMS
        ],
        "context_size": _context_size_sample(),
        "notes": [
            "Offline benchmark uses stored packet theme counts and deterministic architecture estimates.",
            "Live pass-rate and latency claims require provider credentials and should not be inferred from this report.",
        ],
    }


def _arm_metrics(arm: str, case_count: int, theme_counts: dict[str, int], nvidia_duration: float, openai_duration: float) -> dict[str, Any]:
    if arm == "A":
        return {
            "arm": "A",
            "label": "Baseline NVIDIA current",
            "hard_valid_first_pass": None,
            "hard_valid_final": None,
            "retries": sum(theme_counts.values()),
            "fallbacks": 0,
            "median_latency_seconds": nvidia_duration,
            "factual_errors": theme_counts,
            "language_errors": "not_measured",
        }
    if arm == "B":
        fixed = theme_counts.get("keywords_not_in_cv", 0)
        return _estimated_arm("B", "NVIDIA freeform improved", case_count, theme_counts, fixed, nvidia_duration * 0.7, 0)
    if arm == "C":
        fixed = theme_counts.get("keywords_not_in_cv", 0) + theme_counts.get("missing_canonical_role_tech", 0)
        return _estimated_arm("C", "NVIDIA planner + renderer", case_count, theme_counts, fixed, nvidia_duration * 0.35, 0)
    if arm == "D":
        fixed = sum(theme_counts.values())
        return _estimated_arm("D", "NVIDIA planner + renderer + OpenAI fallback", case_count, theme_counts, fixed, median([nvidia_duration * 0.35, openai_duration]), 1)
    fixed = theme_counts.get("keywords_not_in_cv", 0) + theme_counts.get("missing_canonical_role_tech", 0)
    return _estimated_arm("E", "OpenAI with CV IR and renderer", case_count, theme_counts, fixed, openai_duration, 0)


def _estimated_arm(arm: str, label: str, case_count: int, theme_counts: dict[str, int], fixed_theme_count: int, latency: float, fallbacks: int) -> dict[str, Any]:
    remaining = max(0, sum(theme_counts.values()) - fixed_theme_count)
    return {
        "arm": arm,
        "label": label,
        "hard_valid_first_pass": "offline_not_live_measured",
        "hard_valid_final": "offline_not_live_measured",
        "retries": remaining,
        "fallbacks": fallbacks,
        "median_latency_seconds": round(latency, 2),
        "factual_errors": {"offline_remaining_theme_count": remaining, "case_count": case_count},
        "language_errors": "offline_not_live_measured",
    }


def _context_size_sample() -> dict[str, int]:
    legacy_context = {
        "candidate_profile": {"skills": ["Python", "REST APIs"]},
        "base_cv": {"text": "Python backend developer\n" * 200},
        "ranking": {"reasoning_summary": "Detailed ranking notes " * 50},
        "ranking_constraints": {"avoid_overclaiming_aliases": {"Kubernetes": ["Kubernetes", "EKS"]}},
        "ats_fit_analysis": {"supported_keywords": ["Python", "REST APIs"]},
        "job": {"company": "Acme", "title": "Backend Engineer", "description_text": "Build Python APIs."},
    }
    generation_context = build_generation_context(legacy_context)
    return {
        "legacy_context_chars": len(json.dumps(legacy_context, ensure_ascii=False)),
        "generation_context_chars": len(json.dumps(generation_context, ensure_ascii=False)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline materials controlled-generation benchmark.")
    parser.add_argument("--baseline", type=Path, default=Path("tests/fixtures/materials_evidence_baseline.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_offline_benchmark(args.baseline)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
