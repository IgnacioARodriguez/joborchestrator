from __future__ import annotations

from joborchestrator.storage import persistence as db
from scripts.smoke_ui import seed_ui_database


def test_ui_smoke_seed_creates_dashboard_data(tmp_path):
    db_path = tmp_path / "ui-smoke.db"

    seed = seed_ui_database(db_path)

    old_path = db.DB_PATH
    db.DB_PATH = db_path
    try:
        jobs = db.get_job_postings(limit=None)
        applications = db.list_applications()
        rankings = db.get_rankings_for_job_ids("ranking_v1.1.0-nvidia", [int(seed["primary_job_id"])])
    finally:
        db.DB_PATH = old_path

    assert seed["job_count"] == 2
    assert len(jobs) == 2
    assert len(applications) == 1
    assert not rankings.empty
    assert "Senior Backend Engineer" in set(jobs["title"].tolist())
