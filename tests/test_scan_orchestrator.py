from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pandas as pd

from joborchestrator.scanning import orchestrator
from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning import search_providers


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


def test_unified_scan_default_search_providers_skip_unconfigured(monkeypatch):
    captured: dict[str, list[str]] = {}

    async def fake_search_intents_concurrently(providers, *args, **kwargs):
        captured["providers"] = list(providers)
        return []

    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("INFOJOBS_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFOJOBS_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(orchestrator.db, "get_candidate_profile_payload", lambda: {})
    monkeypatch.setattr(
        orchestrator.search_scanner,
        "search_intents_concurrently",
        fake_search_intents_concurrently,
    )

    providers = {
        "adzuna": object(),
        "infojobs": object(),
        "remotive": object(),
    }
    with patch.dict(search_providers.SEARCH_PROVIDERS, providers, clear=True), patch.dict(
        orchestrator.SEARCH_PROVIDERS,
        providers,
        clear=True,
    ):
        output = asyncio.run(
            orchestrator.run_unified_job_scan(
                {
                    "include_ats": False,
                    "include_search": True,
                    "include_linkedin": False,
                    "search_providers": [],
                    "queries": ["backend engineer"],
                }
            )
        )

    assert captured["providers"] == ["remotive"]
    assert output["errors"] == {}
