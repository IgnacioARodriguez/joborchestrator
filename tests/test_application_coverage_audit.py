from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

from scripts.audit_application_coverage import (
    audit_application_coverage,
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
            state="ready_for_review",
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
            fields_detected=0,
            fields_autofilled=0,
            unknown_fields=1,
            submit_controls_count=0,
            blocked=False,
        )
        == "no_form_detected"
    )


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
                "state": "ready_for_review",
                "coverage_score": "ready_no_human_input",
                "fields_detected": 3,
                "fields_autofilled": 3,
                "unknown_fields": 0,
                "resume_upload_status": "uploaded",
                "submit_controls_count": 1,
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
    assert "provider_detected" in (tmp_path / "audit.csv").read_text(encoding="utf-8")
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
        )
    )

    result = report["results"][0]
    assert report["dry_run"] is True
    assert report["auto_submit_enabled"] is False
    assert result["provider_detected"] == "generic_form"
    assert result["state"] == "ready_for_review"
    assert result["coverage_score"] == "ready_no_human_input"
    assert result["resume_upload_status"] == "uploaded"
    assert result["submit_controls_count"] == 1
