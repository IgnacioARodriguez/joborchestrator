from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
from joborchestrator.storage import persistence as db


def make_job(title: str = "Backend Engineer", description: str = "Build APIs") -> JobPosting:
    content_hash = compute_content_hash(title, "Acme", "Remote", description, "https://example.com/apply")
    return JobPosting(
        external_id="job-1",
        source="greenhouse",
        company="Acme",
        title=title,
        location="Remote",
        apply_url="https://example.com/apply",
        description_text=description,
        content_hash=content_hash,
        raw_payload={"id": "job-1", "title": title},
    )


def test_upsert_preserves_first_seen_and_updates_last_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    first_status = db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    second_status = db.upsert_job_posting(make_job(), seen_at="2026-01-02T10:00:00")

    jobs = db.get_job_postings(limit=10)
    row = jobs.iloc[0]
    assert first_status == "new"
    assert second_status == "seen"
    assert row["first_seen_at"] == "2026-01-01T10:00:00"
    assert row["last_seen_at"] == "2026-01-02T10:00:00"
    assert row["times_seen"] == 2


def test_upsert_detects_content_hash_change(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    status = db.upsert_job_posting(make_job(description="Build APIs and data pipelines"), seen_at="2026-01-02T10:00:00")

    jobs = db.get_job_postings(limit=10)
    assert status == "updated"
    assert jobs.iloc[0]["status"] == "updated"
    assert jobs.iloc[0]["times_seen"] == 2


def test_company_source_upsert(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    first_id = db.add_company_source("greenhouse", "Acme", "acme", True)
    second_id = db.add_company_source("greenhouse", "Acme Labs", "acme", False)

    sources = db.list_company_sources()
    assert first_id == second_id
    assert len(sources) == 1
    assert sources.iloc[0]["company_name"] == "Acme Labs"
    assert sources.iloc[0]["enabled"] == 0


def test_application_materials_are_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted",
        recruiter_message="Hello recruiter",
        cover_letter="Dear team",
        ats_cv_text="Python, APIs",
        autofill_notes="why_join: strong fit",
    )

    stored = db.get_job_posting(job_id)
    assert stored["pipeline_status"] == "shortlisted"
    assert stored["recruiter_message"] == "Hello recruiter"
    assert stored["cover_letter"] == "Dear team"
    assert stored["ats_cv_text"] == "Python, APIs"
    assert stored["autofill_notes"] == "why_join: strong fit"
