from __future__ import annotations

from scripts.smoke_vercel_backend import evaluate_backend_summary, summarize_backend_responses


def test_vercel_backend_smoke_summarizes_healthy_turso_backend():
    responses = {
        "health": {"status": "ok"},
        "profile": {"profile": {"headline": "ML Engineer", "skills": []}},
        "jobs": {"meta": {"total": 383, "db_mode": "turso"}, "jobs": [{"id": "1"}]},
        "apply_queue": {"meta": {"total": 383, "db_mode": "turso"}, "jobs": [{"id": "1"}]},
        "applications": {"applications": [{"id": 1}]},
        "ops_status": {
            "mode": "turso",
            "local_worker_needed": False,
            "ranking_worker_needed": False,
            "summary": "All quiet.",
            "latest_scan_operation": {"id": 1, "type": "job_scan", "status": "completed", "output_json": {}},
            "latest_ranking_job": {"id": 2, "provider": "nvidia", "status": "completed", "failed_items": 0},
        },
        "worker_status": {"mode": "turso", "pending_count": 0, "running_count": 0, "needs_local_worker": False},
        "sources": {"sources": [{"id": 1}]},
        "scan_overview": {
            "overview": {"total_jobs": 383, "recent_errors": 0, "last_scan_status": "success"},
            "errors": [],
        },
        "ranking_jobs": {"jobs": [{"id": 2, "provider": "nvidia", "status": "completed", "failed_items": 0}]},
    }

    summary = summarize_backend_responses(responses)
    checks = evaluate_backend_summary(summary)

    assert checks["passed"] is True
    assert checks["failures"] == []
    assert checks["warnings"] == []
    assert summary["db_modes"] == ["turso"]
    assert summary["profile_present"] is True
    assert summary["jobs_total"] == 383
    assert summary["ranking_jobs_returned"] == 1
    assert summary["recent_scan_errors"] == []


def test_vercel_backend_smoke_warns_on_operational_errors_without_failing_availability():
    summary = {
        "health": {"status": "ok"},
        "db_modes": ["turso"],
        "profile_present": True,
        "jobs_total": 10,
        "ranking_jobs_returned": 1,
        "latest_ranking_job": {"failed_items": 3},
        "scan_overview": {"last_scan_status": "error", "recent_errors": 2},
        "recent_scan_errors": [{"provider": "greenhouse", "company_name": "Acme"}],
        "latest_scan_operation": {
            "error": None,
            "output_errors": {"linkedin": "Object of type JobPosting is not JSON serializable"},
        },
    }

    checks = evaluate_backend_summary(summary)

    assert checks["passed"] is True
    assert checks["failures"] == []
    assert "Latest ranking job has 3 failed items." in checks["warnings"]
    assert "Latest scan status is error." in checks["warnings"]
    assert "Scan overview reports 2 recent errors." in checks["warnings"]
    assert "Recent scan error sample: greenhouse:Acme" in checks["warnings"]
    assert (
        "Latest scan output error for linkedin: Object of type JobPosting is not JSON serializable"
        in checks["warnings"]
    )


def test_vercel_backend_smoke_fails_when_backend_is_not_using_turso():
    summary = {
        "health": {"status": "ok"},
        "db_modes": ["sqlite"],
        "profile_present": False,
        "jobs_total": 0,
        "ranking_jobs_returned": 0,
        "latest_ranking_job": None,
        "scan_overview": {},
        "latest_scan_operation": None,
    }

    checks = evaluate_backend_summary(summary)

    assert checks["passed"] is False
    assert "Backend did not report db_mode=turso." in checks["failures"]
    assert "Expected at least 1 jobs from /api/jobs." in checks["failures"]
    assert "Expected at least 1 ranking jobs." in checks["failures"]
    assert "Profile endpoint returned no candidate profile." in checks["failures"]
