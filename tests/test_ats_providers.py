from joborchestrator.scanning.normalization import compute_content_hash, normalize_job_identity
from joborchestrator.scanning.providers import AshbyProvider, GreenhouseProvider, LeverProvider


def test_greenhouse_normalization():
    payload = {
        "id": 123,
        "title": "Backend Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
        "location": {"name": "Remote"},
        "department": {"name": "Engineering"},
        "content": "<p>Build APIs</p>",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    job = GreenhouseProvider().normalize_job(payload, "acme", "Acme")

    assert job.external_id == "123"
    assert job.source == "greenhouse"
    assert job.company == "Acme"
    assert job.location == "Remote"
    assert job.department == "Engineering"
    assert job.description_text == "Build APIs"
    assert job.content_hash
    assert job.raw_payload == payload


def test_lever_normalization():
    payload = {
        "id": "abc",
        "text": "Product Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "applyUrl": "https://jobs.lever.co/acme/abc/apply",
        "categories": {"team": "Product", "department": "Engineering", "location": "Madrid", "commitment": "Full-time"},
        "descriptionPlain": "Build product systems",
        "lists": [{"text": "What you will do", "content": "<li>Ship features</li>"}],
    }

    job = LeverProvider().normalize_job(payload, "acme", "Acme")

    assert job.external_id == "abc"
    assert job.source == "lever"
    assert job.title == "Product Engineer"
    assert job.apply_url.endswith("/apply")
    assert job.department == "Engineering"
    assert job.workplace_type == "Full-time"
    assert "Build product systems" in job.description_text


def test_ashby_normalization_with_compensation():
    payload = {
        "id": "ash-1",
        "title": "AI Engineer",
        "locationNames": ["Spain", "Remote"],
        "employmentType": "FullTime",
        "departmentName": "AI",
        "descriptionHtml": "<p>Work on agents</p>",
        "jobUrl": "https://jobs.ashbyhq.com/acme/ash-1",
        "applyUrl": "https://jobs.ashbyhq.com/acme/ash-1/application",
        "compensation": {"minValue": 90000, "maxValue": 130000, "currencyCode": "EUR"},
    }

    job = AshbyProvider().normalize_job(payload, "acme", "Acme")

    assert job.external_id == "ash-1"
    assert job.source == "ashby"
    assert job.location == "Spain, Remote"
    assert job.salary_min == 90000
    assert job.salary_max == 130000
    assert job.salary_currency == "EUR"
    assert job.description_text == "Work on agents"


def test_content_hash_and_identity_are_normalized():
    h1 = compute_content_hash("Backend Engineer", "Acme", "Remote", "Build APIs", "https://x.test/apply")
    h2 = compute_content_hash(" backend   engineer ", "ACME", "remote", "<p>Build APIs</p>", "https://x.test/apply")

    assert h1 == h2
    assert normalize_job_identity("Senior Backend", "Acme Inc.", "Madrid") == "senior backend|acme inc|madrid"
