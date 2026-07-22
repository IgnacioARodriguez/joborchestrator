import argparse
import json

from scripts import requeue_non_active_prompt_items as requeue


def _row(job_id: int, *, status: str = "completed", prompt_version: str = "v3") -> dict:
    return {
        "job_id": job_id,
        "item_status": status,
        "ranking_prompt_versions_json": json.dumps({"ranking/nvidia_response_contract": prompt_version}),
    }


def test_non_active_prompt_job_ids_selects_completed_stale_versions():
    rows = [
        _row(1, prompt_version="v4"),
        _row(2, prompt_version="v3"),
        _row(3, status="queued", prompt_version="v3"),
        {"job_id": 4, "item_status": "completed", "ranking_prompt_versions_json": "{}"},
    ]

    assert requeue.non_active_prompt_job_ids(rows, active_version="v4") == [2]


def test_requeue_non_active_prompt_items_dry_run_writes_payload(tmp_path, monkeypatch):
    output = tmp_path / "payload.json"
    monkeypatch.setattr(requeue, "active_prompt_version", lambda surface, sub_case: "v4")
    monkeypatch.setattr(
        requeue,
        "fetch_ranking_rows",
        lambda **kwargs: [_row(1, prompt_version="v3"), _row(2, prompt_version="v4")],
    )
    monkeypatch.setattr(requeue.db, "requeue_ranking_items", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    args = argparse.Namespace(
        ranking_job_id=9,
        ranking_version="ranking-test",
        limit=None,
        output=output,
        execute=False,
        force=False,
    )

    payload = requeue.run(args)

    assert payload["candidate_count"] == 1
    assert payload["job_ids"] == [1]
    assert payload["requeued"] == 0
    assert json.loads(output.read_text(encoding="utf-8"))["job_ids"] == [1]


def test_requeue_non_active_prompt_items_execute_limits_and_requeues(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requeue, "active_prompt_version", lambda surface, sub_case: "v4")
    monkeypatch.setattr(
        requeue,
        "fetch_ranking_rows",
        lambda **kwargs: [_row(1, prompt_version="v3"), _row(2, prompt_version="v3")],
    )

    def fake_requeue(*args, **kwargs):
        calls.append((args, kwargs))
        return 1

    monkeypatch.setattr(requeue.db, "requeue_ranking_items", fake_requeue)
    args = argparse.Namespace(
        ranking_job_id=9,
        ranking_version="ranking-test",
        limit=1,
        output=tmp_path / "payload.json",
        execute=True,
        force=False,
    )

    payload = requeue.run(args)

    assert payload["job_ids"] == [1]
    assert payload["requeued"] == 1
    assert calls == [
        (
            (9, [1]),
            {
                "reason": "Requeued because ranking prompt version is no longer active.",
                "statuses": ("completed",),
            },
        )
    ]


def test_requeue_non_active_prompt_items_execute_rejects_running_items(tmp_path, monkeypatch):
    monkeypatch.setattr(requeue, "active_prompt_version", lambda surface, sub_case: "v4")
    monkeypatch.setattr(
        requeue,
        "fetch_ranking_rows",
        lambda **kwargs: [
            _row(1, prompt_version="v3"),
            _row(2, status="running", prompt_version="v3"),
        ],
    )
    monkeypatch.setattr(requeue.db, "requeue_ranking_items", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    args = argparse.Namespace(
        ranking_job_id=9,
        ranking_version="ranking-test",
        limit=None,
        output=tmp_path / "payload.json",
        execute=True,
        force=False,
    )

    try:
        requeue.run(args)
    except requeue.RequeueError as exc:
        assert "running items" in str(exc)
    else:
        raise AssertionError("Expected RequeueError")
