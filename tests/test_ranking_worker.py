from joborchestrator.ranking import worker
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
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


def make_ranking(ranking_version: str) -> RankingResult:
    return RankingResult(
        final_score=82,
        decision="APPLY_NOW",
        confidence=0.9,
        scores=RankingScores(
            technical_fit=82,
            seniority_fit=80,
            role_fit=84,
            opportunity_quality=75,
            application_roi=88,
            market_alignment=70,
            risk_penalty=2,
        ),
        evidence=RankingEvidence(strong_matches=["APIs"]),
        reasoning_summary="Synthetic LLM ranking for worker persistence.",
        recommended_application_angle="Emphasize API delivery.",
        cv_keywords_to_emphasize=["APIs"],
        cv_keywords_to_avoid_overclaiming=[],
        ranking_version=ranking_version,
    )


def test_worker_processes_queued_nvidia_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])
    ranking_version = "worker-test-v1"
    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model="nvidia/test",
        ranking_version=ranking_version,
        job_ids=[job_id],
        request_batch_size=1,
        max_concurrency=1,
    )

    def fake_rank_jobs_with_nvidia(jobs, **kwargs):
        for _, row in jobs.iterrows():
            ranking = make_ranking(kwargs["ranking_version"])
            db.save_job_ranking(int(row["id"]), ranking)
        return {"processed": len(jobs), "saved": len(jobs), "failed": 0}

    monkeypatch.setattr(worker, "rank_jobs_with_nvidia", fake_rank_jobs_with_nvidia)

    assert worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=10) is True

    finished = db.get_ranking_job(ranking_job_id)
    assert finished["status"] == "completed"
    assert finished["processed_items"] == 1
    assert finished["saved_items"] == 1
    assert len(db.get_ranked_jobs(ranking_version=ranking_version)) == 1


def test_worker_recovers_stale_running_items(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    monkeypatch.setattr(worker, "DEFAULT_STALE_SECONDS", 1)
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])
    ranking_version = "worker-stale-test-v1"
    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model="nvidia/test",
        ranking_version=ranking_version,
        job_ids=[job_id],
        request_batch_size=1,
        max_concurrency=1,
    )
    db.start_ranking_job(ranking_job_id)
    db.mark_ranking_items_running(ranking_job_id, [job_id])

    conn = db._conn()
    try:
        conn.execute(
            """UPDATE ranking_job_items
               SET updated_at = '2026-01-01T00:00:00'
               WHERE ranking_job_id = ?""",
            (ranking_job_id,),
        )
        conn.commit()
    finally:
        conn.close()

    def fake_rank_jobs_with_nvidia(jobs, **kwargs):
        for _, row in jobs.iterrows():
            db.save_job_ranking(int(row["id"]), make_ranking(kwargs["ranking_version"]))
        return {"processed": len(jobs), "saved": len(jobs), "failed": 0}

    monkeypatch.setattr(worker, "rank_jobs_with_nvidia", fake_rank_jobs_with_nvidia)

    assert worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=10) is True

    finished = db.get_ranking_job(ranking_job_id)
    assert finished["status"] == "completed"
    assert finished["processed_items"] == 1
    assert finished["saved_items"] == 1


def test_worker_failed_item_overwrites_stale_requeue_error(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    monkeypatch.setattr(worker, "DEFAULT_STALE_SECONDS", 1)
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])
    ranking_version = "worker-failed-error-test-v1"
    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model="nvidia/test",
        ranking_version=ranking_version,
        job_ids=[job_id],
        request_batch_size=1,
        max_concurrency=1,
    )
    db.start_ranking_job(ranking_job_id)
    db.mark_ranking_items_running(ranking_job_id, [job_id])

    conn = db._conn()
    try:
        conn.execute(
            """UPDATE ranking_job_items
               SET updated_at = '2026-01-01T00:00:00'
               WHERE ranking_job_id = ?""",
            (ranking_job_id,),
        )
        conn.commit()
    finally:
        conn.close()

    def fake_rank_jobs_with_nvidia(jobs, **kwargs):
        return {"processed": len(jobs), "saved": 0, "failed": len(jobs)}

    monkeypatch.setattr(worker, "rank_jobs_with_nvidia", fake_rank_jobs_with_nvidia)

    assert worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=10) is True

    conn = db._conn()
    try:
        item = conn.execute(
            "SELECT status, error FROM ranking_job_items WHERE ranking_job_id = ?",
            (ranking_job_id,),
        ).fetchone()
    finally:
        conn.close()

    assert item["status"] == "failed"
    assert item["error"] == (
        "NVIDIA did not return a valid ranking for this job. "
        "Try rerunning with a smaller batch size if this repeats."
    )


def test_worker_does_not_complete_item_from_stale_existing_ranking(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=10).iloc[0]["id"])
    ranking_version = "worker-stale-ranking-test-v1"
    db.save_job_ranking(job_id, make_ranking(ranking_version))

    conn = db._conn()
    try:
        conn.execute(
            """UPDATE job_rankings
               SET updated_at = '2026-01-01T00:00:00'
               WHERE job_id = ? AND ranking_version = ?""",
            (job_id, ranking_version),
        )
        conn.commit()
    finally:
        conn.close()

    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model="nvidia/test",
        ranking_version=ranking_version,
        job_ids=[job_id],
        request_batch_size=1,
        max_concurrency=1,
    )

    def fake_rank_jobs_with_nvidia(jobs, **kwargs):
        return {"processed": len(jobs), "saved": 0, "failed": len(jobs)}

    monkeypatch.setattr(worker, "rank_jobs_with_nvidia", fake_rank_jobs_with_nvidia)

    assert worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=10) is True

    finished = db.get_ranking_job(ranking_job_id)
    assert finished["status"] == "completed"
    assert finished["processed_items"] == 1
    assert finished["saved_items"] == 0
    assert finished["failed_items"] == 1

    conn = db._conn()
    try:
        item = conn.execute(
            "SELECT status, error FROM ranking_job_items WHERE ranking_job_id = ?",
            (ranking_job_id,),
        ).fetchone()
    finally:
        conn.close()

    assert item["status"] == "failed"
    assert item["error"] == (
        "NVIDIA did not return a valid ranking for this job. "
        "Try rerunning with a smaller batch size if this repeats."
    )
