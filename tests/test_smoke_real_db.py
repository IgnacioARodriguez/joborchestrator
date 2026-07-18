from __future__ import annotations

from joborchestrator.storage import persistence as db
from scripts.smoke_real_db import copy_database_readonly, inspect_database_readonly
from scripts.smoke_ui import seed_ui_database


def test_real_db_smoke_inspects_and_copies_database_readonly(tmp_path):
    source = tmp_path / "source.db"
    copied = tmp_path / "copied.db"
    seed_ui_database(source)

    before = source.read_bytes()
    summary = inspect_database_readonly(source)
    copy_database_readonly(source, copied)
    after = source.read_bytes()

    assert before == after
    assert summary["counts"]["job_postings"] == 2
    assert summary["counts"]["job_rankings"] == 2
    assert summary["profile_present"] is True

    old_path = db.DB_PATH
    db.DB_PATH = copied
    try:
        jobs = db.get_job_postings(limit=None)
    finally:
        db.DB_PATH = old_path
    assert len(jobs) == 2
