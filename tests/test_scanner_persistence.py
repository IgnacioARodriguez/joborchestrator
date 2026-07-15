import json
import sqlite3
from datetime import datetime, timedelta

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
from joborchestrator.scanning import linkedin
from joborchestrator.storage import persistence as db
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores


def make_job(
    title: str = "Backend Engineer",
    description: str = "Build APIs",
    *,
    external_id: str = "job-1",
    source: str = "greenhouse",
    company: str = "Acme",
) -> JobPosting:
    content_hash = compute_content_hash(title, company, "Remote", description, "https://example.com/apply")
    return JobPosting(
        external_id=external_id,
        source=source,
        company=company,
        title=title,
        location="Remote",
        apply_url="https://example.com/apply",
        description_text=description,
        scraped_at="2026-01-01T09:00:00",
        posted_at_raw="2026-01-01",
        posted_at_confidence="medium",
        content_hash=content_hash,
        raw_payload={"id": external_id, "title": title},
    )


def make_ranking(ranking_version: str = "ranking_v1.1.0-nvidia") -> RankingResult:
    return RankingResult(
        final_score=81,
        decision="APPLY_NOW",
        confidence=0.88,
        scores=RankingScores(
            technical_fit=82,
            seniority_fit=75,
            role_fit=80,
            opportunity_quality=70,
            application_roi=85,
            market_alignment=70,
            risk_penalty=2,
        ),
        evidence=RankingEvidence(strong_matches=["Python", "FastAPI"]),
        reasoning_summary="Synthetic LLM ranking for persistence tests.",
        recommended_application_angle="Emphasize Python APIs.",
        cv_keywords_to_emphasize=["Python", "FastAPI"],
        cv_keywords_to_avoid_overclaiming=[],
        ranking_version=ranking_version,
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


def test_application_entities_and_events_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    resume = db.create_resume_variant(
        {"label": "Backend CV", "file_ref": "cv/backend.pdf", "base_version": "base-v1", "diff_summary": "Python focus"}
    )
    application = db.create_application(
        {
            "job_id": job_id,
            "ats_type": "greenhouse",
            "status": "submitted",
            "channel": "portal",
            "resume_variant_id": resume["id"],
            "submitted_at": "2026-01-02T10:00:00",
        }
    )
    event = db.create_application_event(
        application["id"],
        {"event_type": "submitted", "event_at": "2026-01-02T10:00:00", "note": "Manual submit"},
    )

    stored = db.get_application(application["id"])
    assert stored["status"] == "submitted"
    assert stored["channel"] == "portal"
    assert stored["job_title"] == "Backend Engineer"
    assert event["event_type"] == "submitted"
    assert stored["events"][0]["note"] == "Manual submit"
    assert db.list_resume_variants()[0]["label"] == "Backend CV"


def test_answer_contacts_and_followups_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])
    application = db.create_application({"job_id": job_id, "status": "preparing", "channel": "easy_apply"})

    answer = db.upsert_answer_definition(
        {
            "canonical_key": "work_authorization",
            "question_patterns": ["Are you authorized to work?"],
            "answer_type": "boolean",
            "value": "yes",
            "source": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": True,
        }
    )
    contact = db.create_contact(
        {"job_id": job_id, "company": "Acme", "name": "Jane Recruiter", "source": "linkedin_scraper"}
    )
    follow_up = db.create_follow_up(
        {"application_id": application["id"], "due_at": "2026-01-10T09:00:00", "note": "Ping recruiter"}
    )

    assert answer["question_patterns"] == ["Are you authorized to work?"]
    assert answer["requires_confirmation"] is True
    assert db.list_answer_definitions()[0]["canonical_key"] == "work_authorization"
    assert contact["name"] == "Jane Recruiter"
    assert db.list_contacts()[0]["company"] == "Acme"
    assert follow_up["note"] == "Ping recruiter"
    assert db.list_follow_ups()[0]["application_id"] == application["id"]


def test_generated_resume_variant_links_to_application(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])

    resume = db.register_generated_resume_variant(
        job_id,
        "Acme - Backend Engineer ATS CV",
        "Professional Summary\nBackend engineer\n\nTechnical Skills\nPython",
    )

    application = db.list_applications()[0]
    assert resume["label"] == "Acme - Backend Engineer ATS CV"
    assert application["job_id"] == job_id
    assert application["resume_variant_id"] == resume["id"]
    assert db.get_application(application["id"])["events"][0]["event_type"] == "answer_saved"


def test_delete_job_rankings_clears_current_rankings(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(
        make_job(description="Requirements: Python, FastAPI, REST APIs, AWS. Responsibilities: build backend APIs."),
        seen_at="2026-01-01T10:00:00",
    )
    stored = db.get_job_postings(limit=10).iloc[0]
    job_id = int(stored["id"])
    ranking = make_ranking()
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


def test_operation_run_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    operation_id = db.create_operation(
        "cv_profile_import",
        {"filename": "cv.pdf", "cv_text": "Python backend engineer"},
        "Queued.",
    )

    queued = db.get_operation(operation_id)
    assert queued["status"] == "queued"
    assert queued["input_json"]["filename"] == "cv.pdf"

    claimed = db.claim_next_operation("worker-1", ["cv_profile_import"])
    assert claimed["id"] == operation_id
    assert claimed["status"] == "running"
    assert claimed["claimed_by"] == "worker-1"

    db.update_operation_progress(operation_id, "Saving profile.")
    running = db.get_operation(operation_id)
    assert running["progress_message"] == "Saving profile."

    db.complete_operation(operation_id, {"profile_saved": True}, "Profile ready.")
    completed = db.get_operation(operation_id)
    assert completed["status"] == "completed"
    assert completed["output_json"] == {"profile_saved": True}


def test_stale_operation_runs_are_requeued(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    operation_id = db.create_operation("job_scan", {"include_ats": True}, "Queued.")
    claimed = db.claim_next_operation("worker-1", ["job_scan"])
    assert claimed["status"] == "running"

    conn = db._conn()
    try:
        conn.execute(
            """UPDATE operation_runs
               SET updated_at = '2026-01-01T00:00:00'
               WHERE id = ?""",
            (operation_id,),
        )
        conn.commit()
    finally:
        conn.close()

    assert db.requeue_stale_operations(["job_scan"], stale_seconds=1) == 1

    operation = db.get_operation(operation_id)
    assert operation["status"] == "queued"
    assert operation["claimed_by"] is None
    assert operation["progress_message"] == "Requeued after worker timeout."


def test_skill_catalog_is_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    catalog = db.list_skill_catalog()

    database_skills = [item for item in catalog if item["category"] == "Database"]
    assert {item["name"] for item in database_skills} >= {"PostgreSQL", "MongoDB", "Redis"}
    sales_skills = [item for item in catalog if item["category"] == "Sales & Customer"]
    assert {item["name"] for item in sales_skills} >= {"Presales", "Demos", "Negotiation"}


def test_skill_catalog_can_be_extended(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()

    skill = db.add_skill_catalog_item("Legal", "Contract Review")

    assert skill["category"] == "Legal"
    assert skill["name"] == "Contract Review"
    assert any(item["name"] == "Contract Review" for item in db.list_skill_catalog())


def test_recent_external_ids_for_source_respects_freshness_window(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    now = datetime.now()
    recent = (now - timedelta(days=2)).isoformat(timespec="seconds")
    old = (now - timedelta(days=45)).isoformat(timespec="seconds")

    db.upsert_job_posting(
        make_job(external_id="li-recent", source="linkedin_scraper", company="Acme"),
        seen_at=recent,
    )
    db.upsert_job_posting(
        make_job(external_id="li-old", source="linkedin_scraper", company="Acme"),
        seen_at=old,
    )
    db.upsert_job_posting(
        make_job(external_id="gh-recent", source="greenhouse", company="Acme"),
        seen_at=recent,
    )

    seen_ids = db.get_recent_external_ids_for_source("linkedin_scraper", freshness_window_seconds=30 * 24 * 60 * 60)

    assert seen_ids == {"li-recent"}


def test_linkedin_fresh_checkpoint_mode_uses_db_memory_without_old_results(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    now = datetime.now()
    recent = (now - timedelta(days=2)).isoformat(timespec="seconds")
    checkpoint_path = tmp_path / "checkpoint.jsonl"
    checkpoint_path.write_text(
        json.dumps({"id": "li-checkpoint-old", "titulo": "Old checkpoint job"}) + "\n",
        encoding="utf-8",
    )

    db.upsert_job_posting(
        make_job(external_id="li-recent", source="linkedin_scraper", company="Acme"),
        seen_at=recent,
    )
    monkeypatch.setattr(linkedin, "CHECKPOINT_JSONL", checkpoint_path)

    offers, seen_ids = linkedin.cargar_checkpoint(resume_from_checkpoint=False)

    assert offers == []
    assert seen_ids == {"li-recent"}


def test_mark_jobs_inactive_by_last_seen_only_affects_old_matching_source(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    now = datetime.now()
    recent = (now - timedelta(days=2)).isoformat(timespec="seconds")
    old = (now - timedelta(days=45)).isoformat(timespec="seconds")

    db.upsert_job_posting(
        make_job(external_id="li-recent", source="linkedin_scraper", company="Acme"),
        seen_at=recent,
    )
    db.upsert_job_posting(
        make_job(external_id="li-old", source="linkedin_scraper", company="Acme"),
        seen_at=old,
    )
    db.upsert_job_posting(
        make_job(external_id="gh-old", source="greenhouse", company="Acme"),
        seen_at=old,
    )

    inactive = db.mark_jobs_inactive_by_last_seen("linkedin_scraper", freshness_window_seconds=30 * 24 * 60 * 60)
    rows = {row["external_id"]: row for _, row in db.get_job_postings(limit=10).iterrows()}

    assert inactive == 1
    assert rows["li-recent"]["is_active"] == 1
    assert rows["li-old"]["is_active"] == 0
    assert rows["gh-old"]["is_active"] == 1


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


def test_pipeline_status_applied_and_opened_migrate_to_applications(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_pipeline.db"
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
            pipeline_status TEXT,
            identity_key TEXT,
            UNIQUE(source, company, external_id)
        )"""
    )
    for external_id, pipeline_status in [("job-applied", "applied"), ("job-opened", "opened")]:
        conn.execute(
            """INSERT INTO job_postings (
                external_id, source, company, title, location, apply_url, url,
                posted_at, first_seen_at, last_seen_at, content_hash, pipeline_status, identity_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                external_id,
                "greenhouse",
                "Acme",
                "Backend Engineer",
                "Remote",
                "https://apply.test",
                "https://job.test",
                "2026-01-01",
                "2026-01-01T09:00:00",
                "2026-01-02T09:00:00",
                external_id,
                pipeline_status,
                f"{external_id}|acme|remote",
            ),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", db_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    jobs = {row["external_id"]: dict(row) for row in conn.execute("SELECT * FROM job_postings").fetchall()}
    applications = [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY job_id").fetchall()]
    events = [dict(row) for row in conn.execute("SELECT * FROM application_events ORDER BY id").fetchall()]
    conn.close()

    assert jobs["job-applied"]["pipeline_status"] == "ready_to_apply"
    assert jobs["job-opened"]["pipeline_status"] == "new"
    assert [app["status"] for app in applications] == ["submitted", "preparing"]
    assert [event["event_type"] for event in events] == ["submitted", "opened"]
