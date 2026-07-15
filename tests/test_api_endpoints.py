from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from joborchestrator import api
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
from joborchestrator.storage import persistence as db


def client_for_tmp_db(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    db.init_db()
    return TestClient(api.app)


def make_job(
    *,
    external_id: str = "job-1",
    title: str = "Backend Engineer",
    company: str = "Acme",
    description: str = "Build APIs with Python and FastAPI.",
) -> JobPosting:
    apply_url = f"https://example.com/apply/{external_id}"
    content_hash = compute_content_hash(title, company, "Remote", description, apply_url)
    return JobPosting(
        external_id=external_id,
        source="greenhouse",
        company=company,
        title=title,
        location="Remote",
        apply_url=apply_url,
        description_text=description,
        content_hash=content_hash,
        raw_payload={"id": external_id, "title": title},
    )


def make_ranking(version: str, score: int, decision: str = "APPLY_NOW") -> RankingResult:
    return RankingResult(
        final_score=score,
        decision=decision,  # type: ignore[arg-type]
        confidence=0.9,
        scores=RankingScores(
            technical_fit=score,
            seniority_fit=score,
            role_fit=score,
            opportunity_quality=score,
            application_roi=score,
            market_alignment=score,
            risk_penalty=2,
        ),
        evidence=RankingEvidence(strong_matches=["Python"]),
        reasoning_summary=f"{version} summary",
        recommended_application_angle=f"{version} angle",
        cv_keywords_to_emphasize=["Python", "FastAPI"],
        cv_keywords_to_avoid_overclaiming=[],
        ranking_version=version,
    )


def save_job_with_rankings() -> int:
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.save_job_ranking(job_id, make_ranking("ranking_v1.1.0-nvidia", 91, "APPLY_NOW"))
    db.save_job_ranking(job_id, make_ranking("ranking_v1.1.0-openai:gpt-5.4-mini", 72, "APPLY_WITH_TAILORED_CV"))
    db.save_job_ranking(job_id, make_ranking("ranking_v1.1.0-speed", 15, "AVOID"))
    return job_id


def profile_payload() -> dict:
    return {
        "schema_version": 1,
        "headline": "Backend engineer",
        "target_roles": ["Backend Engineer"],
        "secondary_roles": [],
        "role_aliases": {},
        "skills": [{"name": "Python", "category": "Programming", "level": "strong", "evidence": "Profile"}],
        "industries": [],
        "preferred_locations": ["Remote"],
        "preferred_work_modes": ["remote"],
        "application_targets": [{"label": "Remote", "location": "Remote", "work_modes": ["remote"]}],
        "dealbreakers": [],
        "avoid_roles": [],
        "real_experience_years": 4,
        "notes": "",
        "suggested_roles_reasoning": "",
    }


def test_health_and_profile_round_trip(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/profile").json() == {"profile": None}

    response = client.put("/api/profile", json={"profile": profile_payload()})

    assert response.status_code == 200
    assert response.json()["profile"]["headline"] == "Backend engineer"
    assert client.get("/api/profile").json()["profile"]["target_roles"] == ["Backend Engineer"]


def test_jobs_can_select_ranking_version_and_hide_heuristic_versions(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    save_job_with_rankings()

    default_response = client.get("/api/jobs")
    openai_response = client.get("/api/jobs", params={"ranking_version": "ranking_v1.1.0-openai:gpt-5.4-mini"})

    assert default_response.status_code == 200
    default_body = default_response.json()
    assert default_body["jobs"][0]["ranking"]["ranking_version"] == "ranking_v1.1.0-nvidia"
    assert default_body["jobs"][0]["ranking"]["final_score"] == 91
    assert "ranking_v1.1.0-speed" not in default_body["ranking_versions"]
    assert set(default_body["ranking_versions"]) == {
        "ranking_v1.1.0-nvidia",
        "ranking_v1.1.0-openai:gpt-5.4-mini",
    }

    assert openai_response.status_code == 200
    openai_body = openai_response.json()
    assert openai_body["selected_ranking_version"] == "ranking_v1.1.0-openai:gpt-5.4-mini"
    assert openai_body["jobs"][0]["ranking"]["final_score"] == 72


def test_jobs_reject_heuristic_ranking_versions(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.get("/api/jobs", params={"ranking_version": "ranking_v1.1.0-speed"})

    assert response.status_code == 400
    assert "Heuristic rankings" in response.json()["detail"]


def test_apply_queue_paginates_after_priority_sort(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    for index, score in enumerate([20, 95, 60], start=1):
        external_id = f"job-{index}"
        db.upsert_job_posting(
            make_job(external_id=external_id, title=f"Role {index}"),
            seen_at=(datetime.now() - timedelta(hours=index)).isoformat(timespec="seconds"),
        )
        row = db.get_job_postings(limit=None)
        job_id = int(row[row["external_id"] == external_id].iloc[0]["id"])
        db.save_job_ranking(job_id, make_ranking("ranking_v1.1.0-nvidia", score, "APPLY_NOW"))

    first_page = client.get("/api/apply-queue", params={"limit": 1, "offset": 0}).json()
    second_page = client.get("/api/apply-queue", params={"limit": 1, "offset": 1}).json()

    assert first_page["jobs"][0]["title"] == "Role 2"
    assert second_page["jobs"][0]["title"] == "Role 3"
    assert first_page["meta"]["total"] == 3
    assert first_page["meta"]["limit"] == 1
    assert first_page["meta"]["has_next"] is True
    assert second_page["meta"]["has_previous"] is True


def test_apply_queue_filters_stale_test_data(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(
        make_job(external_id="fresh-job", title="Fresh Role"),
        seen_at=datetime.now().isoformat(timespec="seconds"),
    )
    db.upsert_job_posting(
        make_job(external_id="old-job", title="Old Role"),
        seen_at=(datetime.now() - timedelta(days=14)).isoformat(timespec="seconds"),
    )
    rows = db.get_job_postings(limit=None)
    for _, row in rows.iterrows():
        db.save_job_ranking(int(row["id"]), make_ranking("ranking_v1.1.0-nvidia", 80, "APPLY_NOW"))

    active = client.get("/api/apply-queue").json()
    stale = client.get("/api/apply-queue", params={"freshness": "stale"}).json()

    assert [job["title"] for job in active["jobs"]] == ["Fresh Role"]
    assert [job["title"] for job in stale["jobs"]] == ["Old Role"]
    assert active["meta"]["freshness_counts"]["fresh"] == 1
    assert active["meta"]["freshness_counts"]["stale"] == 1


def test_scan_fresh_queues_scan_with_auto_ranking(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    client.put("/api/profile", json={"profile": profile_payload()})

    response = client.post("/api/scans/fresh")

    assert response.status_code == 200
    body = response.json()
    operation = client.get(f"/api/operations/{body['operation_id']}").json()["operation"]
    assert operation["type"] == "job_scan"
    assert operation["input_json"]["auto_rank_new"] is True
    assert operation["input_json"]["include_linkedin"] is True
    assert "Backend Engineer" in operation["input_json"]["queries"]


def test_ops_status_reports_local_and_ranking_work(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.create_operation("job_scan", {"include_ats": True}, "Queued scan.")
    db.upsert_job_posting(
        make_job(external_id="rank-me", title="Rank Me"),
        seen_at=datetime.now().isoformat(timespec="seconds"),
    )
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    db.create_ranking_job(
        provider="nvidia",
        model="test-model",
        ranking_version="ranking_v1.1.0-nvidia",
        job_ids=[job_id],
        request_batch_size=1,
        max_concurrency=1,
    )

    response = client.get("/api/ops/status")

    assert response.status_code == 200
    body = response.json()
    assert body["local_worker_needed"] is True
    assert body["ranking_worker_needed"] is True
    assert body["latest_scan_operation"]["type"] == "job_scan"
    assert body["latest_ranking_job"]["status"] == "queued"
    assert body["expected_commands"]["workers"] == "npm run workers"


def test_create_job_endpoint_for_extension(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post(
        "/api/jobs",
        json={
            "title": "Greenhouse Role",
            "company": "Acme",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
        },
    )

    assert response.status_code == 200
    job = response.json()["job"]
    assert job["title"] == "Greenhouse Role"
    assert job["company"] == "Acme"
    assert job["apply_url"] == "https://boards.greenhouse.io/acme/jobs/1"


def test_skill_catalog_can_be_extended_via_api(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post("/api/profile/skill-catalog", json={"category": "Legal", "name": "Contract Review"})

    assert response.status_code == 200
    body = response.json()
    assert body["skill"]["category"] == "Legal"
    assert body["skill"]["name"] == "Contract Review"
    assert any(skill["name"] == "Contract Review" for skill in body["skills"])


def test_linkedin_profile_setting_round_trip(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    initial = client.get("/api/linkedin/profile")
    assert initial.status_code == 200
    assert initial.json()["linkedin_profile"]["current"] == "test"

    response = client.put("/api/linkedin/profile", json={"profile_name": "Test Account"})

    assert response.status_code == 200
    body = response.json()["linkedin_profile"]
    assert body["current"] == "test_account"
    assert "test_account" in body["profiles"]
    assert body["profile_dir"].endswith("linkedin_user_profile_test_account")
    assert client.get("/api/linkedin/profile").json()["linkedin_profile"]["current"] == "test_account"

    blocked = client.put("/api/linkedin/profile", json={"profile_name": "main"})
    assert blocked.status_code == 400
    assert "disabled" in blocked.json()["detail"]


def test_scan_all_queues_job_scan_operation(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post(
        "/api/scans/all",
        json={
            "include_ats": True,
            "include_search": True,
            "search_providers": ["remotive"],
            "queries": ["backend engineer"],
            "application_targets": [
                {"label": "Malaga", "location": "Malaga, Spain", "work_modes": ["onsite", "hybrid", "remote"]}
            ],
            "linkedin_limit": 50,
            "location": "Spain",
        },
    )

    assert response.status_code == 200
    body = response.json()
    operation = db.get_operation(body["operation_id"])
    assert body["status"] == "queued"
    assert operation["type"] == "job_scan"
    assert operation["input_json"]["queries"] == ["backend engineer"]
    assert operation["input_json"]["linkedin_limit"] == 50
    assert operation["input_json"]["application_targets"][0]["location"] == "Malaga, Spain"
    assert operation["progress_message"] == "Queued unified job scan. Waiting for local worker."


def test_scan_all_reuses_active_job_scan_operation(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    operation_id = db.create_operation("job_scan", {"include_ats": True}, "Still scanning.")
    claimed = db.claim_next_operation("worker-1", ["job_scan"])
    assert claimed["id"] == operation_id

    response = client.post(
        "/api/scans/all",
        json={
            "include_ats": True,
            "include_search": True,
            "queries": ["backend engineer"],
            "location": "Spain",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_id"] == operation_id
    assert body["status"] == "running"
    assert body["already_running"] is True
    assert body["progress_message"] == "Worker started processing."
    assert len(db.list_operations(limit=10)) == 1


def test_ranking_job_requires_profile(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": False})

    assert response.status_code == 400
    assert "No candidate profile configured" in response.json()["detail"]


def test_ranking_job_queues_unranked_jobs_with_profile(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    client.put("/api/profile", json={"profile": profile_payload()})

    response = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": False})

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] == 1
    assert body["ranking_job_id"] is not None


def test_ranking_job_run_once_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    client.put("/api/profile", json={"profile": profile_payload()})

    response = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": True})

    assert response.status_code == 409
    assert "local NVIDIA ranking worker" in response.json()["detail"]
    assert client.get("/api/ranking/jobs").json()["jobs"] == []


def test_existing_ranking_job_run_once_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    client.put("/api/profile", json={"profile": profile_payload()})
    ranking_job_id = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": False}).json()["ranking_job_id"]

    response = client.post(f"/api/ranking/jobs/{ranking_job_id}/run-once", json={})

    assert response.status_code == 409
    assert "local NVIDIA ranking worker" in response.json()["detail"]


def test_import_cv_queues_operation(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "extract_text_from_cv", lambda filename, content: "Python backend engineer")

    response = client.post(
        "/api/profile/import-cv",
        files={"file": ("cv.txt", b"Python backend engineer", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    operation = client.get(f"/api/operations/{body['operation_id']}").json()["operation"]
    assert operation["type"] == "cv_profile_import"
    assert operation["input_json"]["cv_text"] == "Python backend engineer"


def test_operations_list_returns_recent_operations(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    first_id = db.create_operation("first", {}, "Queued first")
    second_id = db.create_operation("second", {}, "Queued second")

    response = client.get("/api/operations", params={"limit": 5})

    assert response.status_code == 200
    operations = response.json()["operations"]
    assert [operation["id"] for operation in operations[:2]] == [second_id, first_id]


def test_ranking_job_can_be_cancelled_from_api(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    client.put("/api/profile", json={"profile": profile_payload()})
    ranking_job_id = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": False}).json()["ranking_job_id"]

    response = client.post(f"/api/ranking/jobs/{ranking_job_id}/cancel", json={})

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "cancelled"


def test_ranking_job_failed_items_can_be_requeued_from_api(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    client.put("/api/profile", json={"profile": profile_payload()})
    ranking_job_id = client.post("/api/ranking/jobs", json={"limit": 10, "run_once": False}).json()["ranking_job_id"]
    db.start_ranking_job(ranking_job_id)
    db.mark_ranking_items_running(ranking_job_id, [job_id])
    db.fail_ranking_job(ranking_job_id, "NVIDIA timeout")

    response = client.post(f"/api/ranking/jobs/{ranking_job_id}/requeue-failed", json={})

    assert response.status_code == 200
    assert response.json()["requeued"] == 1
    queued = db.get_queued_ranking_items(ranking_job_id, limit=10)
    assert int(queued.iloc[0]["id"]) == job_id
    refreshed = client.get("/api/ranking/jobs").json()["jobs"][0]
    assert refreshed["queued_items"] == 1
    assert refreshed["failed_item_count"] == 0


def test_import_cv_rejects_empty_file(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post(
        "/api/profile/import-cv",
        files={"file": ("cv.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_generate_materials_persists_application_kit(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    job_id = save_job_with_rankings()
    client.put("/api/profile", json={"profile": profile_payload()})
    monkeypatch.setattr(
        api,
        "build_application_kit",
        lambda job, keywords=None: {
            "recruiter_message": "Hello recruiter",
            "cover_letter": "Dear team",
            "ats_cv_text": "Python\nFastAPI",
            "autofill_notes": "Use tailored answers",
        },
    )

    response = client.post(f"/api/jobs/{job_id}/materials", json={"use_llm": False, "shortlist": True})

    assert response.status_code == 200
    job = response.json()["job"]
    assert job["pipeline_status"] == "shortlisted"
    assert job["materials"]["recruiter_message"] == "Hello recruiter"
    assert job["materials"]["cover_letter"] == "Dear team"
    assert job["materials"]["ats_cv_notes"] == "Python\nFastAPI"


def test_application_rest_endpoints(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])

    created = client.post(
        f"/api/jobs/{job_id}/applications",
        json={"ats_type": "greenhouse", "status": "preparing", "channel": "portal"},
    )
    assert created.status_code == 200
    app_id = created.json()["application"]["id"]

    patched = client.patch(f"/api/applications/{app_id}", json={"status": "submitted"})
    assert patched.status_code == 200
    assert patched.json()["application"]["status"] == "submitted"

    event = client.post(
        f"/api/applications/{app_id}/events",
        json={"event_type": "submitted", "note": "Submitted manually"},
    )
    assert event.status_code == 200
    assert event.json()["event"]["event_type"] == "submitted"

    listed = client.get("/api/applications")
    assert listed.status_code == 200
    assert listed.json()["applications"][0]["job_title"] == "Backend Engineer"
    assert listed.json()["applications"][0]["job_first_seen_at"] == "2026-01-01T10:00:00"


def test_mark_opened_creates_application_event_without_pipeline_state(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])

    response = client.post(f"/api/jobs/{job_id}/opened", json={})

    assert response.status_code == 200
    assert response.json()["event"]["event_type"] == "opened"
    assert db.get_job_posting(job_id)["pipeline_status"] == "new"
    application = db.list_applications()[0]
    assert application["status"] == "preparing"
    assert db.get_application(application["id"])["events"][0]["event_type"] == "opened"


def test_profile_support_rest_endpoints(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    db.upsert_job_posting(make_job(), seen_at="2026-01-01T10:00:00")
    job_id = int(db.get_job_postings(limit=1).iloc[0]["id"])
    application = db.create_application({"job_id": job_id, "status": "preparing", "channel": "portal"})

    assert client.post("/api/resumes", json={"label": "Backend CV"}).status_code == 200
    assert client.get("/api/resumes").json()["resumes"][0]["label"] == "Backend CV"

    answer = client.post(
        "/api/answers",
        json={
            "canonical_key": "salary_expectation",
            "question_patterns": ["Expected salary"],
            "answer_type": "text",
            "value": "Open to discuss",
            "source": "approved",
            "sensitivity": "preference",
        },
    )
    assert answer.status_code == 200
    assert client.get("/api/answers").json()["answers"][0]["canonical_key"] == "salary_expectation"

    assert client.post("/api/contacts", json={"job_id": job_id, "name": "Jane"}).status_code == 200
    assert client.get("/api/contacts").json()["contacts"][0]["name"] == "Jane"

    follow_up = client.post(
        "/api/follow-ups",
        json={"application_id": application["id"], "due_at": "2026-01-10T09:00:00", "note": "Follow up"},
    )
    assert follow_up.status_code == 200
    assert client.get("/api/follow-ups").json()["follow_ups"][0]["note"] == "Follow up"


def test_gmail_rule_preview_is_read_only(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post(
        "/api/gmail/rules/preview",
        json={
            "sender": "recruiter@example.com",
            "subject": "Interview schedule",
            "body": "Can we schedule a technical screen next week?",
        },
    )

    assert response.status_code == 200
    signal = response.json()["signal"]
    assert signal["event_type"] == "interview_scheduled"
    assert signal["confidence"] > 0


def test_generate_materials_queues_nvidia_provider(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    job_id = save_job_with_rankings()
    client.put("/api/profile", json={"profile": profile_payload()})

    response = client.post(f"/api/jobs/{job_id}/materials", json={"provider": "nvidia", "shortlist": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    operation = db.get_operation(body["operation_id"])
    assert operation["type"] == "application_materials_generation"
    assert operation["input_json"]["job_id"] == job_id
    assert operation["input_json"]["provider"] == "nvidia"


def test_download_optimized_cv_materials(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)
    job_id = save_job_with_rankings()
    db.update_job_application_materials(
        job_id,
        ats_cv_text="Ignacio Rodriguez\nBackend Engineer\nPython APIs and PostgreSQL.",
    )

    docx_response = client.get(f"/api/jobs/{job_id}/materials/ats-cv.docx")
    pdf_response = client.get(f"/api/jobs/{job_id}/materials/ats-cv.pdf")

    assert docx_response.status_code == 200
    assert docx_response.content.startswith(b"PK")
    assert "application/vnd.openxmlformats" in docx_response.headers["content-type"]
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF")
    assert pdf_response.headers["content-type"] == "application/pdf"


def test_generate_materials_reports_missing_job(tmp_path, monkeypatch):
    client = client_for_tmp_db(tmp_path, monkeypatch)

    response = client.post("/api/jobs/999/materials", json={"use_llm": False})

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"
