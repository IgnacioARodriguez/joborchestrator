import pandas as pd

from joborchestrator.scanning.linkedin_importer import (
    extract_linkedin_external_id,
    import_linkedin_dataframe_to_job_postings,
    linkedin_dataframe_to_job_postings,
)
from joborchestrator.storage import persistence as db


def test_extracts_linkedin_id_from_url():
    assert extract_linkedin_external_id(url="https://www.linkedin.com/jobs/view/123456789/") == "123456789"
    assert extract_linkedin_external_id(url="https://www.linkedin.com/jobs/search/?currentJobId=987") == "987"


def test_maps_spanish_linkedin_columns_to_job_posting():
    df = pd.DataFrame(
        [
            {
                "id": "li-1",
                "titulo": "Python Backend Developer",
                "empresa": "Acme",
                "ubicacion": "Spain Remote",
                "modalidad": "Remote",
                "url": "https://www.linkedin.com/jobs/view/123/",
                "descripcion": "Requirements: Python, FastAPI, APIs. Responsibilities: build backend services." * 8,
                "extraccion_ok": True,
                "cantidad_solicitantes": 25,
                "cantidad_solicitantes_raw": None,
                "salary_min": 40000,
                "salary_max": 55000,
                "salary_currency": "EUR",
                "recruiter_name": "Jane Recruiter",
                "recruiter_profile_url": "https://www.linkedin.com/in/jane/",
                "apply_type": "external",
                "external_apply_url": "https://jobs.example.com/apply/123",
            }
        ]
    )

    jobs = linkedin_dataframe_to_job_postings(df)

    assert len(jobs) == 1
    assert jobs[0].source == "linkedin_scraper"
    assert jobs[0].external_id == "li-1"
    assert jobs[0].company == "Acme"
    assert jobs[0].parse_confidence and jobs[0].parse_confidence >= 0.8
    assert jobs[0].content_hash
    assert jobs[0].applicant_count == 25
    assert jobs[0].applicant_count_raw is None
    assert jobs[0].salary_min == 40000
    assert jobs[0].salary_max == 55000
    assert jobs[0].salary_currency == "EUR"
    assert jobs[0].recruiter_name == "Jane Recruiter"
    assert jobs[0].recruiter_profile_url == "https://www.linkedin.com/in/jane/"
    assert jobs[0].apply_type == "external"
    assert jobs[0].external_apply_url == "https://jobs.example.com/apply/123"


def test_new_linkedin_enrichment_fields_default_to_none():
    df = pd.DataFrame(
        [
            {
                "id": "li-no-enrichment",
                "titulo": "Python Backend Developer",
                "empresa": "Acme",
                "url": "https://www.linkedin.com/jobs/view/321/",
                "descripcion": "Requirements: Python, FastAPI, APIs. Responsibilities: build backend services." * 8,
                "extraccion_ok": True,
            }
        ]
    )

    job = linkedin_dataframe_to_job_postings(df)[0]

    assert job.applicant_count is None
    assert job.applicant_count_raw is None
    assert job.recruiter_name is None
    assert job.recruiter_profile_url is None
    assert job.apply_type is None
    assert job.external_apply_url is None


def test_low_quality_extraction_is_flagged():
    df = pd.DataFrame(
        [
            {
                "id": "li-2",
                "titulo": "Software Engineer",
                "empresa": "Acme",
                "url": "https://www.linkedin.com/jobs/view/456/",
                "descripcion": "",
                "extraccion_ok": False,
            }
        ]
    )

    job = linkedin_dataframe_to_job_postings(df)[0]

    assert job.parse_confidence <= 0.45
    assert "LinkedIn extraction marked as failed" in job.data_quality_flags
    assert "Very short or missing description" in job.data_quality_flags


def test_missing_company_imports_as_unknown_with_quality_flag():
    df = pd.DataFrame(
        [
            {
                "id": "li-missing-company",
                "titulo": "Go Full Stack Software Engineer",
                "empresa": None,
                "ubicacion": "Remote",
                "url": "https://www.linkedin.com/jobs/view/111/",
                "descripcion": "Requirements: Go, APIs, backend systems. Responsibilities: build services." * 8,
                "fecha_publicacion": "hace 1 semana",
            }
        ]
    )

    job = linkedin_dataframe_to_job_postings(df)[0]

    assert job.company == "UNKNOWN"
    assert job.posted_at_raw == "hace 1 semana"
    assert job.posted_at_confidence == "low"
    assert "missing_company" in job.data_quality_flags


def test_import_upserts_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "linkedin.db")
    db.init_db()
    df = pd.DataFrame(
        [
            {
                "id": "li-3",
                "titulo": "Python Backend Engineer",
                "empresa": "Acme",
                "ubicacion": "Remote",
                "url": "https://www.linkedin.com/jobs/view/789/",
                "descripcion": "Requirements: Python, FastAPI, AWS. Responsibilities: build APIs." * 8,
                "extraccion_ok": True,
            }
        ]
    )

    first = import_linkedin_dataframe_to_job_postings(df)
    second = import_linkedin_dataframe_to_job_postings(df)
    stored = db.get_job_postings(limit=10)

    assert first["new"] == 1
    assert second["seen"] == 1
    assert len(stored) == 1
    assert stored.iloc[0]["first_seen_at"] == stored.iloc[0]["first_seen_at"]
    assert stored.iloc[0]["times_seen"] == 2
    assert stored.iloc[0]["parse_confidence"] >= 0.8
