import sqlite3

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
from joborchestrator.storage import persistence as db
from joborchestrator.ranking.ranker import rank_job


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
        scraped_at="2026-01-01T09:00:00",
        posted_at_raw="2026-01-01",
        posted_at_confidence="medium",
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
    assert row["scraped_at"] == "2026-01-01T09:00:00"
    assert row["posted_at_raw"] == "2026-01-01"
    assert row["posted_at_confidence"] == "medium"
    assert row["soft_identity_key"] == "backend engineer|acme|remote"
    assert row["repost_key"]


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


def test_application_material_update_preserves_unspecified_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted",
        recruiter_message="Initial recruiter",
        cover_letter="Initial cover",
        ats_cv_text="Initial ATS",
        autofill_notes="Initial autofill",
    )
    db.update_job_application_materials(job_id, cover_letter="Updated cover")

    stored = db.get_job_posting(job_id)
    assert stored["pipeline_status"] == "shortlisted"
    assert stored["recruiter_message"] == "Initial recruiter"
    assert stored["cover_letter"] == "Updated cover"
    assert stored["ats_cv_text"] == "Initial ATS"
    assert stored["autofill_notes"] == "Initial autofill"


def test_opening_job_posting_registers_legacy_history(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    assert db.registrar_job_posting_abierta(job_id) is True
    assert db.registrar_job_posting_abierta(job_id) is True

    historial = db.get_historial()
    row = historial.iloc[0]
    assert len(historial) == 1
    assert row["id"] == "job-1"
    assert row["titulo"] == "Backend Engineer"
    assert row["empresa"] == "Acme"
    assert row["categoria"] == "greenhouse"
    assert row["veces_vista"] == 2


def test_opening_ranked_job_posting_copies_score_to_legacy_history(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(
        make_job(description="Requirements: Python, FastAPI, REST APIs, AWS. Responsibilities: build backend APIs."),
        seen_at="2026-01-01T10:00:00",
    )
    stored = db.get_job_postings(limit=10).iloc[0]
    job_id = int(stored["id"])
    ranking = rank_job(stored.to_dict())
    db.save_job_ranking(job_id, ranking)

    db.registrar_job_posting_abierta(job_id)

    historial = db.get_historial()
    row = historial.iloc[0]
    assert row["score_total"] == ranking.final_score
    assert row["fit_stack"] == ranking.scores.technical_fit
    assert row["fit_seniority"] == ranking.scores.seniority_fit
    assert row["transferibilidad"] == ranking.scores.role_fit
    assert row["razon_breve"] == ranking.reasoning_summary


def test_delete_job_rankings_clears_current_rankings(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(
        make_job(description="Requirements: Python, FastAPI, REST APIs, AWS. Responsibilities: build backend APIs."),
        seen_at="2026-01-01T10:00:00",
    )
    stored = db.get_job_postings(limit=10).iloc[0]
    job_id = int(stored["id"])
    ranking = rank_job(stored.to_dict())
    db.save_job_ranking(job_id, ranking)

    assert len(db.get_ranked_jobs(ranking_version=ranking.ranking_version)) == 1

    deleted = db.delete_job_rankings(ranking.ranking_version)

    assert deleted == 1
    assert db.get_ranked_jobs(ranking_version=ranking.ranking_version).empty
    refreshed = db.get_job_posting(job_id)
    assert refreshed["speed_signal"] is None
    assert refreshed["role_viable"] is None


def test_create_and_cancel_ranking_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model="nvidia/test",
        ranking_version="test-v1",
        job_ids=[job_id, job_id],
        request_batch_size=5,
        max_concurrency=2,
    )

    queued = db.get_ranking_job(ranking_job_id)
    assert queued["status"] == "queued"
    assert queued["total_items"] == 1
    assert len(db.get_queued_ranking_items(ranking_job_id, limit=10)) == 1

    db.cancel_ranking_job(ranking_job_id)

    cancelled = db.get_ranking_job(ranking_job_id)
    assert cancelled["status"] == "cancelled"
    assert db.get_queued_ranking_items(ranking_job_id, limit=10).empty


def test_marking_job_posting_applied_syncs_legacy_history_when_opened(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    db.registrar_job_posting_abierta(job_id)
    db.update_job_status(job_id, "applied")

    stored = db.get_job_posting(job_id)
    historial = db.get_historial()
    assert stored["pipeline_status"] == "applied"
    assert int(historial.iloc[0]["aplicado"]) == 1
    assert historial.iloc[0]["fecha_aplicado"]


def test_speed_ranking_migration_is_additive_and_backfills(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE job_postings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT NOT NULL,
            source TEXT NOT NULL,
            company TEXT NOT NULL,
            title TEXT,
            location TEXT,
            apply_url TEXT,
            url TEXT,
            posted_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            content_hash TEXT,
            status TEXT DEFAULT 'seen',
            identity_key TEXT,
            UNIQUE(source, company, external_id)
        )"""
    )
    conn.execute(
        """INSERT INTO job_postings (
            external_id, source, company, title, location, apply_url, url,
            posted_at, first_seen_at, last_seen_at, content_hash, identity_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "li-1",
            "linkedin_scraper",
            "Acme",
            "Backend Engineer",
            "Remote",
            "https://apply.test",
            "https://linkedin.test/jobs/view/1",
            "hace 1 semana",
            "2026-01-01T10:00:00",
            "2026-01-01T10:00:00",
            "old-hash",
            "backend engineer|acme|remote",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", db_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    columns = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(job_postings)")}
    row = conn.execute("SELECT * FROM job_postings WHERE external_id = 'li-1'").fetchone()
    conn.close()
    backups = list((tmp_path / "backups").glob("*before_speed_ranking_migration*.db"))

    assert columns["speed_signal"] == "REAL"
    assert columns["application_effort_signal"] == "REAL"
    assert columns["data_quality_signal"] == "REAL"
    assert columns["source_reliability_signal"] == "REAL"
    assert row["scraped_at"] == "2026-01-01T10:00:00"
    assert row["posted_at_raw"] == "hace 1 semana"
    assert row["posted_at_confidence"] == "low"
    assert row["soft_identity_key"] == "backend engineer|acme|remote"
    assert row["repost_key"]
    assert backups
