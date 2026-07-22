import argparse
import json

import pytest

from scripts import run_autoloop


def test_decide_halts_when_guard_fails():
    metrics = {
        "critical_failures": 1,
        "stale_completion_count": 0,
        "apply_now_unsafe_rate": 0.2,
        "non_active_prompt_rate": 0.5,
        "case_regressions": ["case-1"],
        "schema_failure_retry_rate": 0.2,
        "failed_item_count": 1,
    }
    guards = {
        "max_critical_failures": 0,
        "max_stale_completion_count": 0,
        "max_apply_now_unsafe_rate": 0,
        "max_non_active_prompt_rate": 0,
        "max_case_regressions": 0,
        "max_schema_failure_retry_rate": 0.1,
        "max_failed_item_count": 0,
    }

    decision = run_autoloop.decide(metrics, None, guards)

    assert decision["action"] == "halt_required"
    assert "critical_failures:1>0" in decision["guard_failures"]
    assert "apply_now_unsafe_rate:0.2>0" in decision["guard_failures"]
    assert "non_active_prompt_rate:0.5>0" in decision["guard_failures"]
    assert "case_regressions:1>0" in decision["guard_failures"]
    assert "schema_failure_retry_rate:0.2>0.1" in decision["guard_failures"]
    assert "failed_item_count:1>0" in decision["guard_failures"]


def test_compare_metrics_marks_critical_regression():
    before = {
        "critical_failures": 0,
        "unsafe_apply_now_count": 0,
        "apply_now_unsafe_rate": 0.0,
        "stale_completion_count": 0,
        "retry_or_schema_count": 2,
        "schema_failure_retry_rate": 0.2,
        "non_active_prompt_count": 0,
        "non_active_prompt_rate": 0.0,
        "ranked_rows": 10,
    }
    after = {
        "critical_failures": 1,
        "unsafe_apply_now_count": 1,
        "apply_now_unsafe_rate": 0.1,
        "stale_completion_count": 0,
        "retry_or_schema_count": 1,
        "schema_failure_retry_rate": 0.1,
        "non_active_prompt_count": 2,
        "non_active_prompt_rate": 0.2,
        "ranked_rows": 12,
    }

    comparison = run_autoloop.compare_metrics(before, after)

    assert "retry_or_schema_count:2->1" in comparison["improvements"]
    assert "ranked_rows:10->12" in comparison["improvements"]
    assert "critical_failures:0->1" in comparison["critical_regressions"]
    assert "non_active_prompt_rate:0->0.2" in comparison["critical_regressions"]


def test_evaluate_runtime_limits_reports_budget_and_iteration_caps():
    previous_state = {
        "iteration": 3,
        "consecutive_no_improvement": 2,
        "budgets": {"api_calls_used": 50, "estimated_tokens_used": 500000},
    }
    config = {
        "max_iterations": 3,
        "max_api_calls": 50,
        "max_tokens": 500000,
        "max_consecutive_no_improvement": 2,
    }

    failures = run_autoloop.evaluate_runtime_limits(previous_state, config)

    assert failures == [
        "iteration:3>=3",
        "api_calls_used:50>=50",
        "estimated_tokens_used:500000>=500000",
        "consecutive_no_improvement:2>=2",
    ]


def test_run_autoloop_stop_file_writes_state_and_log(tmp_path):
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    halt_report_dir = tmp_path / "halt"
    stop_file = tmp_path / "AUTOLOOP_STOP"
    stop_file.write_text("stop", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "runtime": {
                    "state_path": str(state_path),
                    "log_path": str(log_path),
                    "halt_report_dir": str(halt_report_dir),
                    "stop_file": str(stop_file),
                }
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        dry_run=True,
        ranking_job_id=9,
        ranking_version="ranking-test",
        config=config_path,
        known_hard_cases=tmp_path / "hard.json",
        golden_cases=tmp_path / "golden",
        state_path=None,
        log_path=None,
        probe_output=tmp_path / "probe.json",
    )

    event = run_autoloop.run_autoloop(args)

    assert event["status"] == "halted"
    assert event["decision"]["reason"] == "stop_file_present"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "halted"
    assert persisted["halt_report"]
    assert "stop_file_present" in (halt_report_dir / "autoloop_HALT_stop_file_present.md").read_text(
        encoding="utf-8"
    )
    assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_run_autoloop_runtime_limit_halts_before_fetching(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    baseline = {"ranked_rows": 7}
    state_path.write_text(
        json.dumps(
            {
                "iteration": 3,
                "baseline": baseline,
                "budgets": {"api_calls_used": 0, "estimated_tokens_used": 0},
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "max_iterations": 3,
                "runtime": {
                    "state_path": str(state_path),
                    "log_path": str(log_path),
                    "halt_report_dir": str(tmp_path / "halt"),
                    "stop_file": str(tmp_path / "missing-stop"),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_autoloop, "fetch_ranking_rows", lambda **kwargs: pytest.fail("should not fetch rankings"))
    monkeypatch.setattr(run_autoloop, "fetch_candidate_rows", lambda **kwargs: pytest.fail("should not select probes"))
    args = argparse.Namespace(
        dry_run=True,
        ranking_job_id=9,
        ranking_version="ranking-test",
        config=config_path,
        known_hard_cases=tmp_path / "hard.json",
        golden_cases=tmp_path / "golden",
        state_path=None,
        log_path=None,
        probe_output=tmp_path / "probe.json",
    )

    event = run_autoloop.run_autoloop(args)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert event["status"] == "halted"
    assert event["decision"]["reason"] == "runtime_limits_exceeded"
    assert event["decision"]["runtime_limit_failures"] == ["iteration:3>=3"]
    assert persisted["baseline"] == baseline
    assert persisted["halt_reason"] == "iteration:3>=3"
    assert persisted["halt_report"].endswith("autoloop_HALT_iteration_3_3.md")


def test_run_autoloop_dry_run_records_metrics_and_probe(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    probe_output = tmp_path / "probe.json"
    config_path.write_text(
        json.dumps(
            {
                "probe_target_total": 1,
                "probe_category_quotas": {"general": 1},
                "runtime": {
                    "state_path": str(state_path),
                    "log_path": str(log_path),
                    "stop_file": str(tmp_path / "missing-stop"),
                },
                "guards": {"max_critical_failures": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_autoloop,
        "fetch_ranking_rows",
        lambda **kwargs: [
            {
                "job_id": 1,
                "item_status": "completed",
                "decision": "SKIP",
                "final_score": 20,
                "scores_json": "{}",
                "evidence_json": "{}",
                "ranking_validation_errors_json": "[]",
                "ranking_validation_attempts": 1,
            }
        ],
    )
    monkeypatch.setattr(
        run_autoloop,
        "fetch_candidate_rows",
        lambda **kwargs: [
            {
                "job_id": 1,
                "item_status": "completed",
                "ranking_id": 1,
                "decision": "SKIP",
                "final_score": 20,
                "scores_json": "{}",
                "evidence_json": "{}",
                "ranking_validation_errors_json": "[]",
                "ranking_validation_attempts": 1,
            }
        ],
    )
    monkeypatch.setattr(run_autoloop, "golden_failure_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(run_autoloop, "load_known_hard_cases", lambda path: {})
    args = argparse.Namespace(
        dry_run=True,
        ranking_job_id=9,
        ranking_version="ranking-test",
        config=config_path,
        known_hard_cases=tmp_path / "hard.json",
        golden_cases=tmp_path / "golden",
        state_path=None,
        log_path=None,
        probe_output=probe_output,
    )

    event = run_autoloop.run_autoloop(args)

    assert event["status"] == "dry_run_complete"
    assert event["decision"]["action"] == "baseline_recorded"
    assert event["metrics"]["ranked_rows"] == 1
    assert json.loads(probe_output.read_text(encoding="utf-8"))["candidate_count"] == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["baseline"]["ranked_rows"] == 1
