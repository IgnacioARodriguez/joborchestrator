import json

from scripts import compute_autoloop_metrics as metrics


def _row(job_id: int, **overrides):
    row = {
        "job_id": job_id,
        "item_status": "completed",
        "item_started_at": "2026-07-22T10:00:00",
        "ranking_updated_at": "2026-07-22T10:05:00",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "decision": "APPLY_NOW",
        "final_score": 82,
        "confidence": 0.9,
        "scores_json": json.dumps({"central_requirement_coverage": 90}),
        "evidence_json": json.dumps(
            {
                "dealbreakers": [],
                "red_flags": [],
                "missing_requirements": [],
                "requires_llm_review": False,
                "central_requirement_coverage": 0.9,
            }
        ),
        "ranking_validation_attempts": 1,
        "ranking_validation_errors_json": "[]",
        "ranking_prompt_versions_json": json.dumps({"ranking/nvidia_response_contract": "v3"}),
    }
    row.update(overrides)
    return row


def test_compute_metrics_detects_unsafe_apply_now_and_stale_completion():
    rows = [
        _row(1),
        _row(
            2,
            evidence_json=json.dumps(
                {
                    "dealbreakers": ["hybrid in another country"],
                    "red_flags": [],
                    "missing_requirements": [],
                    "requires_llm_review": True,
                    "central_requirement_coverage": 0.65,
                }
            ),
        ),
        _row(
            3,
            decision="SKIP",
            final_score=20,
            ranking_updated_at="2026-07-21T10:00:00",
        ),
    ]

    summary = metrics.compute_metrics(rows)

    assert summary["ranked_rows"] == 3
    assert summary["apply_now_count"] == 2
    assert summary["unsafe_apply_now_count"] == 1
    assert summary["apply_now_unsafe_rate"] == 0.5
    assert summary["critical_failures"] == 1
    assert summary["stale_completion_count"] == 1
    assert summary["review_required_count"] == 1


def test_compute_metrics_counts_schema_retry_rate():
    rows = [
        _row(1, ranking_validation_attempts=2),
        _row(2, decision="SKIP", final_score=30),
    ]

    summary = metrics.compute_metrics(rows)

    assert summary["retry_or_schema_count"] == 1
    assert summary["schema_failure_retry_rate"] == 0.5


def test_compute_metrics_ignores_queued_items_with_old_rankings():
    rows = [
        _row(1),
        _row(2, item_status="queued", decision="APPLY_NOW", final_score=90),
    ]

    summary = metrics.compute_metrics(rows)

    assert summary["evaluated_rows"] == 2
    assert summary["item_status_counts"] == {"completed": 1, "queued": 1}
    assert summary["ranked_rows"] == 1
    assert summary["apply_now_count"] == 1


def test_compute_metrics_counts_non_active_prompt_versions(monkeypatch):
    monkeypatch.setattr(metrics, "active_prompt_version", lambda surface, sub_case: "v3")
    rows = [
        _row(1, ranking_prompt_versions_json=json.dumps({"ranking/nvidia_response_contract": "v3"})),
        _row(2, ranking_prompt_versions_json=json.dumps({"ranking/nvidia_response_contract": "v2"})),
        _row(3, ranking_prompt_versions_json=json.dumps({})),
    ]

    summary = metrics.compute_metrics(rows)

    assert summary["active_ranking_prompt_version"] == "v3"
    assert summary["prompt_version_counts"] == {"unknown": 1, "v2": 1, "v3": 1}
    assert summary["non_active_prompt_count"] == 1
    assert summary["non_active_prompt_rate"] == 0.3333
