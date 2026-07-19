import asyncio

import httpx

from joborchestrator.scanning import providers
from joborchestrator.scanning.search_providers import (
    AdzunaSearchProvider,
    ArbeitnowSearchProvider,
    HimalayasSearchProvider,
    InfoJobsSearchProvider,
    RemotiveSearchProvider,
    RemoteOkSearchProvider,
    TheMuseSearchProvider,
    configured_search_provider_names,
    provider_requires_configuration,
)
from joborchestrator.scanning.providers import BaseProvider, ProviderError
from joborchestrator.scanning.search_scanner import summarize_duplicate_rates
from joborchestrator.scanning.models import JobPosting, ScanResult


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_remotive_normalization():
    provider = RemotiveSearchProvider()
    job = provider.normalize_job(
        {
            "id": 123,
            "title": "Python Backend Developer",
            "company_name": "Acme",
            "candidate_required_location": "Europe",
            "url": "https://remotive.com/jobs/123",
            "description": "<p>Build APIs with Python.</p>",
            "publication_date": "2026-07-01T00:00:00",
        },
        "python developer",
        "Europe",
    )

    assert job.source == "remotive"
    assert job.external_id == "123"
    assert job.company == "Acme"
    assert job.workplace_type == "Remote"
    assert job.description_text == "Build APIs with Python."
    assert job.content_hash


def test_base_provider_retries_timeout_once(monkeypatch):
    calls = {"count": 0}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.TimeoutException("temporary timeout")
            return FakeResponse({"ok": True})

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(BaseProvider(timeout=1, retries=1)._get_json("https://example.test/jobs"))

    assert result == {"ok": True}
    assert calls["count"] == 2


def test_base_provider_reports_exhausted_timeout_attempts(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            raise httpx.TimeoutException("still timing out")

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)

    try:
        asyncio.run(BaseProvider(timeout=1, retries=2)._get_json("https://example.test/jobs"))
    except ProviderError as exc:
        assert "after 3 attempts" in str(exc)
    else:
        raise AssertionError("Expected ProviderError")


def test_arbeitnow_normalization():
    provider = ArbeitnowSearchProvider()
    job = provider.normalize_job(
        {
            "slug": "backend-engineer-acme",
            "title": "Backend Engineer",
            "company_name": "Acme",
            "location": "Berlin",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/backend-engineer-acme",
            "description": "<p>Python and APIs.</p>",
            "tags": ["Python", "API"],
            "created_at": 1780000000,
        },
        "backend engineer",
        "Europe",
    )

    assert job.source == "arbeitnow"
    assert job.external_id == "backend-engineer-acme"
    assert job.company == "Acme"
    assert job.workplace_type == "Remote"
    assert job.department == "Python, API"


def test_adzuna_normalization():
    provider = AdzunaSearchProvider()
    job = provider.normalize_job(
        {
            "id": "adz-1",
            "title": "Software Engineer",
            "company": {"display_name": "Acme"},
            "location": {"display_name": "Madrid, Spain"},
            "redirect_url": "https://adzuna.example/jobs/1",
            "description": "Build software.",
            "salary_min": 45000,
            "salary_max": 65000,
            "created": "2026-07-01T00:00:00Z",
        },
        "software engineer",
        "Spain",
    )

    assert job.source == "adzuna"
    assert job.company == "Acme"
    assert job.location == "Madrid, Spain"
    assert job.salary_min == 45000.0
    assert job.salary_currency == "EUR"


def test_themuse_normalization():
    provider = TheMuseSearchProvider()
    job = provider.normalize_job(
        {
            "id": 99,
            "name": "Solutions Engineer",
            "company": {"name": "Acme"},
            "locations": [{"name": "Remote, Europe"}],
            "refs": {"landing_page": "https://themuse.example/jobs/99"},
            "contents": "<p>APIs, integrations, customers.</p>",
            "publication_date": "2026-07-01T00:00:00Z",
        },
        "solutions engineer",
        "Europe",
    )

    assert job.source == "themuse"
    assert job.external_id == "99"
    assert job.company == "Acme"
    assert job.location == "Remote, Europe"
    assert "APIs" in job.description_text


def test_remoteok_normalization():
    provider = RemoteOkSearchProvider()
    job = provider.normalize_job(
        {
            "id": "remoteok-1",
            "position": "Backend Engineer",
            "company": "Acme",
            "location": "Europe",
            "url": "https://remoteok.com/remote-jobs/remoteok-1",
            "description": "<p>Python APIs.</p>",
            "tags": ["python", "api"],
            "date": "2026-07-01T00:00:00Z",
        },
        "backend engineer",
        "Europe",
    )

    assert job.source == "remoteok"
    assert job.external_id == "remoteok-1"
    assert job.workplace_type == "Remote"
    assert job.department == "python, api"


def test_himalayas_normalization():
    provider = HimalayasSearchProvider()
    job = provider.normalize_job(
        {
            "id": "him-1",
            "title": "Platform Engineer",
            "company": {"name": "Acme"},
            "locations": [{"name": "Remote, Europe"}],
            "applicationUrl": "https://himalayas.app/jobs/him-1",
            "description": "<p>Build platforms.</p>",
            "publishedAt": "2026-07-01T00:00:00Z",
        },
        "platform engineer",
        "Europe",
    )

    assert job.source == "himalayas"
    assert job.external_id == "him-1"
    assert job.company == "Acme"
    assert job.location == "Remote, Europe"


def test_infojobs_normalization():
    provider = InfoJobsSearchProvider()
    job = provider.normalize_job(
        {
            "id": "ij-1",
            "title": "Backend Developer",
            "author": {"name": "Acme"},
            "city": {"value": "Malaga"},
            "province": {"value": "Malaga"},
            "link": "https://www.infojobs.net/malaga/backend-developer/of-ij-1",
            "description": "Python APIs.",
            "salary": {"minimum": 40000, "maximum": 55000},
            "published": "2026-07-01T00:00:00Z",
        },
        "backend developer",
        "Malaga",
    )

    assert job.source == "infojobs"
    assert job.external_id == "ij-1"
    assert job.company == "Acme"
    assert job.location == "Malaga"
    assert job.salary_min == 40000.0
    assert job.salary_currency == "EUR"


def test_configured_search_provider_names_excludes_missing_credentials(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("INFOJOBS_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFOJOBS_CLIENT_SECRET", raising=False)

    names = configured_search_provider_names()

    assert "remotive" in names
    assert "adzuna" not in names
    assert "infojobs" not in names
    assert provider_requires_configuration("infojobs") is True


def test_duplicate_rate_summary_for_source_evaluation():
    new_job = JobPosting(external_id="new", source="adzuna", company="Acme")
    duplicate_job = JobPosting(external_id="old", source="adzuna", company="Acme")
    result = ScanResult(
        source_type="adzuna",
        company_name="backend",
        company_ref="backend / Spain",
        jobs=[new_job, duplicate_job],
        new_jobs=[new_job],
        unchanged_jobs=[duplicate_job],
    )

    summary = summarize_duplicate_rates([result])

    assert summary == [
        {
            "provider": "adzuna",
            "found": 2,
            "new": 1,
            "updated": 0,
            "duplicates": 1,
            "duplicate_rate": 0.5,
        }
    ]
