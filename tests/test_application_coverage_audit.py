from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import quote

from scripts.audit_application_coverage import (
    adapter_uplift,
    audit_application_coverage,
    automation_score,
    coverage_score,
    read_urls,
    write_csv_report,
    write_json_report,
    write_markdown_report,
)


def test_read_urls_combines_file_args_dedupes_and_limits(tmp_path: Path) -> None:
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "\n".join(
            [
                "# comment",
                "https://example.test/a",
                "https://example.test/b",
                "https://example.test/a",
            ]
        ),
        encoding="utf-8",
    )

    assert read_urls(urls=["https://example.test/c"], urls_file=urls_file, limit=2) == [
        "https://example.test/c",
        "https://example.test/a",
    ]


def test_coverage_score_classifies_low_friction_and_gaps() -> None:
    assert (
        coverage_score(
            state="submit_only",
            fields_detected=4,
            fields_autofilled=4,
            unknown_fields=0,
            submit_controls_count=1,
            blocked=False,
        )
        == "ready_no_human_input"
    )
    assert (
        coverage_score(
            state="needs_user_input",
            fields_detected=4,
            fields_autofilled=2,
            unknown_fields=1,
            submit_controls_count=1,
            blocked=False,
        )
        == "partial_needs_answers"
    )
    assert (
        coverage_score(
            state="needs_user_input",
            reason="posting_unavailable",
            fields_detected=0,
            fields_autofilled=0,
            unknown_fields=0,
            submit_controls_count=0,
            blocked=False,
        )
        == "posting_unavailable"
    )
    assert (
        coverage_score(
            state="needs_user_input",
            fields_detected=0,
            fields_autofilled=0,
            unknown_fields=1,
            submit_controls_count=0,
            blocked=False,
        )
        == "no_form_detected"
    )


def test_adapter_uplift_compares_generic_and_detected_results() -> None:
    generic = {"coverage_score": "partial_needs_answers", "provider_detected": "generic_form"}
    adapter = {"coverage_score": "ready_no_human_input", "provider_detected": "greenhouse"}

    assert automation_score(generic) == 0.55
    assert adapter_uplift(generic, adapter) == {
        "generic_score": 0.55,
        "adapter_score": 1.0,
        "delta": 0.45,
        "generic_coverage_score": "partial_needs_answers",
        "adapter_coverage_score": "ready_no_human_input",
        "generic_provider": "generic_form",
        "adapter_provider": "greenhouse",
    }


def test_report_writers_create_json_csv_and_markdown(tmp_path: Path) -> None:
    report = {
        "dry_run": True,
        "auto_submit_enabled": False,
        "summary": {
            "total": 1,
            "low_friction_count": 1,
            "low_friction_ratio": 1.0,
            "by_score": {"ready_no_human_input": 1},
            "by_provider": {"generic_form": 1},
        },
        "results": [
            {
                "url": "https://example.test/apply",
                "provider_detected": "generic_form",
                "state": "submit_only",
                "coverage_score": "ready_no_human_input",
                "fields_detected": 3,
                "fields_autofilled": 3,
                "unknown_fields": 0,
                "resume_upload_status": "uploaded",
                "submit_controls_count": 1,
                "validation_status": "validation_clean",
                "validation_issue_count": 0,
                "validation_issue_types": [],
                "verified_action_success_rate": 1.0,
                "human_intervention_status": "submit_only",
                "human_intervention_types": ["submit_only"],
                "human_interventions_per_application": 1,
                "answer_intervention_rate": 0.0,
                "validation_intervention_rate": 0.0,
                "widget_intervention_rate": 0.0,
                "submit_only_intervention_rate": 1.0,
                "dynamic_required_count": 0,
                "steps_completed_without_human": 0,
                "step_advance_success_rate": 0.0,
                "submit_only_ready": True,
                "adapter_uplift": {
                    "generic_score": 1.0,
                    "adapter_score": 1.0,
                    "delta": 0.0,
                    "generic_coverage_score": "ready_no_human_input",
                    "adapter_coverage_score": "ready_no_human_input",
                },
                "reason": None,
                "last_error": None,
                "final_url": "https://example.test/apply",
                "duration_seconds": 1.2,
            }
        ],
    }

    write_json_report(tmp_path / "audit.json", report)
    write_csv_report(tmp_path / "audit.csv", report["results"])
    write_markdown_report(tmp_path / "audit.md", report)

    assert "ready_no_human_input" in (tmp_path / "audit.json").read_text(encoding="utf-8")
    assert "human_intervention_status" in (tmp_path / "audit.csv").read_text(encoding="utf-8")
    assert "adapter_uplift_delta" in (tmp_path / "audit.csv").read_text(encoding="utf-8")
    assert "Adapter uplift" in (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "| URL | Provider | State | Score |" in (tmp_path / "audit.md").read_text(encoding="utf-8")


def test_audit_application_coverage_runs_dry_run_on_local_fixture(tmp_path: Path) -> None:
    html = Path("tests/fixtures/generic_application.html").read_text(encoding="utf-8")
    report = asyncio.run(
        audit_application_coverage(
            [f"data:text/html,{quote(html)}"],
            db_path=tmp_path / "coverage.db",
            provider="generic_form",
            answers_file=None,
            headful=False,
            timeout_ms=10_000,
            keep_db=False,
            compare_generic=True,
        )
    )

    result = report["results"][0]
    assert report["dry_run"] is True
    assert report["auto_submit_enabled"] is False
    assert result["provider_detected"] == "generic_form"
    assert result["state"] == "submit_only"
    assert result["coverage_score"] == "ready_no_human_input"
    assert result["resume_upload_status"] == "uploaded"
    assert result["submit_controls_count"] == 1
    assert result["verified_action_success_rate"] == 1.0
    assert result["dynamic_required_count"] == 0
    assert result["steps_completed_without_human"] == 0
    assert result["submit_only_ready"] is True
    assert result["human_intervention_status"] == "submit_only"
    assert result["human_intervention_types"] == ["submit_only"]
    assert result["submit_only_intervention_rate"] == 1.0
    assert result["generic_engine_result"]["provider_detected"] == "generic_form"
    assert result["adapter_uplift"]["delta"] == 0.0
    assert report["summary"]["average_adapter_uplift"] == 0.0


def test_audit_application_coverage_restores_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JOB_ORCHESTRATOR_SKIP_ENV_FILE", raising=False)
    html = Path("tests/fixtures/generic_application.html").read_text(encoding="utf-8")

    asyncio.run(
        audit_application_coverage(
            [f"data:text/html,{quote(html)}"],
            db_path=tmp_path / "coverage.db",
            provider="generic_form",
            answers_file=None,
            headful=False,
            timeout_ms=10_000,
            keep_db=False,
        )
    )

    assert "JOB_ORCHESTRATOR_SKIP_ENV_FILE" not in os.environ
