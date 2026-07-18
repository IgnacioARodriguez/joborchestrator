from __future__ import annotations

import asyncio
import json

import pandas as pd

from joborchestrator.scanning import orchestrator
from joborchestrator.scanning.models import JobPosting


def test_linkedin_scan_output_is_json_serializable(monkeypatch):
    scraped = pd.DataFrame([{"external_id": "li-1", "title": "Backend Engineer", "company": "Acme"}])
    scraped.attrs["linkedin_scan_run_id"] = 12
    scraped.attrs["linkedin_scan_summary"] = {"searches_run": 1, "pages_checked": 1, "stop_reason": "completed"}
    updated_runs = []

    async def fake_linkedin_scrape(**kwargs):
        return scraped

    monkeypatch.setattr(orchestrator.linkedin, "run_linkedin_scrape", fake_linkedin_scrape)
    monkeypatch.setattr(
        orchestrator,
        "import_linkedin_dataframe_to_job_postings",
        lambda frame: {
            "jobs": [JobPosting(external_id="li-1", source="linkedin_scraper", company="Acme")],
            "new": 1,
            "updated": 0,
            "seen": 0,
            "total": 1,
        },
    )
    monkeypatch.setattr(orchestrator.db, "mark_jobs_inactive_by_last_seen", lambda source, freshness_window_seconds: 0)
    monkeypatch.setattr(
        orchestrator.db,
        "update_linkedin_scan_run",
        lambda *args, **kwargs: updated_runs.append(kwargs),
    )

    output = asyncio.run(orchestrator._run_linkedin_scan(limit=1, resume_from_checkpoint=False, operation_id=9))

    json.dumps(output)
    json.dumps(updated_runs[0]["summary"])
    assert output["import_stats"] == {"new": 1, "updated": 0, "seen": 0, "total": 1}
    assert "jobs" not in output["import_stats"]
    assert updated_runs[0]["summary"]["import_stats"] == output["import_stats"]
