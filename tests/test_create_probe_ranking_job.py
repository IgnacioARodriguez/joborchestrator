import argparse
import json

from scripts import create_probe_ranking_job as creator


def test_selected_job_ids_filters_categories_and_dedupes():
    probe = {
        "cases": [
            {"job_id": 1, "categories": ["general"]},
            {"job_id": 2, "categories": ["suspicious_apply_now"]},
            {"job_id": 2, "categories": ["suspicious_apply_now"]},
            {"job_id": 3, "categories": ["risk_evidence"]},
        ]
    }

    assert creator.selected_job_ids(probe, categories=["suspicious_apply_now", "risk_evidence"], limit=5) == [2, 3]


def test_create_probe_job_dry_run_does_not_create_db_job(tmp_path, monkeypatch):
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps({"cases": [{"job_id": 7, "categories": ["general"]}]}), encoding="utf-8")
    monkeypatch.setattr(creator.db, "create_ranking_job", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected create")))
    args = argparse.Namespace(
        probe=probe_path,
        ranking_version="ranking-test",
        model="nvidia/test",
        category=[],
        limit=8,
        request_batch_size=2,
        max_concurrency=1,
        execute=False,
    )

    response = creator.create_probe_job(args)

    assert response["dry_run"] is True
    assert response["selected_job_ids"] == [7]
    assert "ranking_job_id" not in response


def test_create_probe_job_execute_creates_db_job(tmp_path, monkeypatch):
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps({"cases": [{"job_id": 7, "categories": ["risk_evidence"]}]}), encoding="utf-8")
    calls = {}

    def fake_create_ranking_job(**kwargs):
        calls.update(kwargs)
        return 123

    monkeypatch.setattr(creator.db, "create_ranking_job", fake_create_ranking_job)
    args = argparse.Namespace(
        probe=probe_path,
        ranking_version="ranking-test",
        model="nvidia/test",
        category=["risk_evidence"],
        limit=8,
        request_batch_size=2,
        max_concurrency=1,
        execute=True,
    )

    response = creator.create_probe_job(args)

    assert response["ranking_job_id"] == 123
    assert calls["provider"] == "nvidia"
    assert calls["job_ids"] == [7]
