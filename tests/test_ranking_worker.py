from joborchestrator.ranking import worker
from joborchestrator.ranking.ranker import rank_job
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
            ranking = rank_job(row.to_dict())
            ranking.ranking_version = kwargs["ranking_version"]
            db.save_job_ranking(int(row["id"]), ranking)
        return {"processed": len(jobs), "saved": len(jobs), "failed": 0}

    monkeypatch.setattr(worker, "rank_jobs_with_nvidia", fake_rank_jobs_with_nvidia)

    assert worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=10) is True

    finished = db.get_ranking_job(ranking_job_id)
    assert finished["status"] == "completed"
    assert finished["processed_items"] == 1
    assert finished["saved_items"] == 1
    assert len(db.get_ranked_jobs(ranking_version=ranking_version)) == 1
