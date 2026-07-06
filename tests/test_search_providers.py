from joborchestrator.scanning.search_providers import (
    AdzunaSearchProvider,
    ArbeitnowSearchProvider,
    RemotiveSearchProvider,
    TheMuseSearchProvider,
)


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
