from __future__ import annotations

from pathlib import Path

from test_api_endpoints import client_for_tmp_db


def test_apply_queue_and_greenhouse_session_api(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    created = client.post(
        "/api/jobs",
        json={
            "title": "Software Engineer",
            "company": "Acme",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
            "description_text": "Build reliable systems.",
        },
    ).json()["job"]

    queue = client.get("/api/apply-queue?limit=10")
    assert queue.status_code == 200
    assert queue.json()["jobs"][0]["priority"]["priority_score"] >= 0

    html = Path("tests/fixtures/greenhouse_application.html").read_text(encoding="utf-8")
    response = client.post(
        f"/api/jobs/{created['id']}/application-sessions",
        json={"provider": "greenhouse", "mode": "review_before_submit", "html": html, "dry_run": True},
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["provider"] == "greenhouse"
    assert session["state"] == "needs_user_input"
    assert session["fields_detected"] == 5
    assert session["fields_autofilled"] >= 0


def test_external_apply_session_queues_application_execution(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    created = client.post(
        "/api/jobs",
        json={
            "title": "Platform Engineer",
            "company": "Acme",
            "url": "https://www.linkedin.com/jobs/view/123",
            "apply_url": "https://boards.greenhouse.io/acme/jobs/123",
            "source": "linkedin_scraper",
            "description_text": "Build platforms.",
        },
    ).json()["job"]

    response = client.post(
        f"/api/jobs/{created['id']}/application-sessions",
        json={"provider": "greenhouse", "mode": "review_before_submit", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_id"] is not None
    operation = client.get(f"/api/operations/{body['operation_id']}").json()["operation"]
    assert operation["type"] == "application_execution"
    assert operation["input_json"]["apply_url"] == "https://boards.greenhouse.io/acme/jobs/123"
    assert body["session"]["state"] == "preflight"


def test_worker_status_reports_pending_local_work(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db = __import__("joborchestrator.storage.persistence", fromlist=[""])
    operation_id = db.create_operation("application_execution", {"job_id": 1}, "Queued browser work.")

    response = client.get("/api/workers/status")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == 1
    assert body["needs_local_worker"] is True
    assert body["latest_worker_operation"]["id"] == operation_id


def test_continue_application_session_requeues_same_session(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    created = client.post(
        "/api/jobs",
        json={
            "title": "Platform Engineer",
            "company": "Acme",
            "url": "https://www.linkedin.com/jobs/view/456",
            "apply_url": "https://boards.greenhouse.io/acme/jobs/456",
            "source": "linkedin_scraper",
            "description_text": "Build platforms.",
        },
    ).json()["job"]
    session = client.post(
        f"/api/jobs/{created['id']}/application-sessions",
        json={"provider": "greenhouse", "mode": "review_before_submit", "html": "<form id='application_form'></form>", "dry_run": True},
    ).json()["session"]

    response = client.post(f"/api/application-sessions/{session['id']}/continue", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["id"] == session["id"]
    assert body["operation_id"] is not None
    operation = client.get(f"/api/operations/{body['operation_id']}").json()["operation"]
    assert operation["type"] == "application_execution"
    assert operation["input_json"]["continue_after_manual_step"] is True


def test_automation_accounts_api_hides_password_ref(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("ALLOW_PLAINTEXT_CREDENTIAL_STORE", "1")

    response = client.post(
        "/api/automation/accounts",
        json={
            "provider": "greenhouse",
            "domain": "boards.greenhouse.io",
            "status": "ready",
            "username": "me@example.com",
            "password": "secret",
        },
    )

    assert response.status_code == 200
    account = response.json()["account"]
    assert account["has_password"] is True
    assert "password_ref" not in account
    listed = client.get("/api/automation/accounts").json()["accounts"][0]
    assert listed["has_password"] is True
    assert "password_ref" not in listed


def test_duplicate_application_creation_returns_existing(tmp_path, monkeypatch) -> None:
    client = client_for_tmp_db(tmp_path, monkeypatch)
    created = client.post(
        "/api/jobs",
        json={
            "title": "Data Engineer",
            "company": "Acme",
            "url": "https://example.com/job/2",
            "source": "manual",
            "description_text": "Move data.",
        },
    ).json()["job"]

    first = client.post(f"/api/jobs/{created['id']}/applications", json={}).json()["application"]
    second = client.post(f"/api/jobs/{created['id']}/applications", json={}).json()["application"]

    assert first["id"] == second["id"]
