from __future__ import annotations

from joborchestrator import worker


def test_worker_processes_cv_profile_import(monkeypatch):
    saved = {}
    completed = {}
    progress = []

    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: {
            "id": 12,
            "type": "cv_profile_import",
            "input_json": {"filename": "cv.pdf", "cv_text": "Python FastAPI"},
        },
    )
    monkeypatch.setattr(worker.db, "update_operation_progress", lambda op_id, message: progress.append(message))
    monkeypatch.setattr(
        worker,
        "build_profile_from_cv_text",
        lambda cv_text, timeout: {
            "skills": [{"name": "Python", "category": "Programming", "level": "strong"}],
            "target_roles": ["Backend Engineer"],
        },
    )
    monkeypatch.setattr(worker.db, "save_candidate_profile_payload", lambda profile: saved.update(profile))
    monkeypatch.setattr(
        worker.db,
        "complete_operation",
        lambda op_id, output, message: completed.update({"id": op_id, "output": output, "message": message}),
    )
    monkeypatch.setattr(worker.db, "fail_operation", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected failure")))

    assert worker.process_once("worker-1") is True

    assert saved["target_roles"] == ["Backend Engineer"]
    assert saved["base_cv_text"] == "Python FastAPI"
    assert saved["base_cv_filename"] == "cv.pdf"
    assert completed["id"] == 12
    assert completed["output"]["profile_saved"] is True
    assert "Calling NVIDIA to analyze your CV." in progress


def test_worker_persists_cv_profile_import_failure(monkeypatch):
    failed = {}

    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: {
            "id": 13,
            "type": "cv_profile_import",
            "input_json": {"filename": "cv.pdf", "cv_text": "Python FastAPI"},
        },
    )
    monkeypatch.setattr(worker.db, "update_operation_progress", lambda op_id, message: None)

    def fail_analysis(cv_text, timeout):
        raise RuntimeError("NVIDIA timeout")

    monkeypatch.setattr(worker, "build_profile_from_cv_text", fail_analysis)
    monkeypatch.setattr(worker.db, "save_candidate_profile_payload", lambda profile: (_ for _ in ()).throw(AssertionError("no save expected")))
    monkeypatch.setattr(
        worker.db,
        "fail_operation",
        lambda op_id, error, message: failed.update({"id": op_id, "error": error, "message": message}),
    )

    assert worker.process_once("worker-1") is True

    assert failed["id"] == 13
    assert "NVIDIA timeout" in failed["error"]
    assert failed["message"] == "Worker failed. Check local logs."


def test_worker_processes_application_materials_generation(monkeypatch):
    saved = {}
    completed = {}
    progress = []

    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: {
            "id": 21,
            "type": "application_materials_generation",
            "input_json": {"job_id": 5, "provider": "nvidia", "model": "test-model", "shortlist": True},
        },
    )
    monkeypatch.setattr(worker.db, "update_operation_progress", lambda op_id, message: progress.append(message))
    monkeypatch.setattr(
        worker,
        "_job_for_materials",
        lambda job_id: ({"id": job_id, "title": "Backend Engineer", "company": "Acme"}, None),
    )
    monkeypatch.setattr(
        worker,
        "build_application_kit_with_nvidia",
        lambda job, ranking=None, model=None: {
            "recruiter_message": "Hi recruiter",
            "cover_letter": "Dear team",
            "ats_cv_text": "Professional Summary\nBackend engineer\n\nTechnical Skills\nPython\n\nProfessional Experience\nBuilt APIs\n\nEducation\nCS",
            "autofill_notes": "Paste answers",
        },
    )
    monkeypatch.setattr(
        worker.db,
        "update_job_application_materials",
        lambda job_id, **kwargs: saved.update({"job_id": job_id, **kwargs}),
    )
    monkeypatch.setattr(
        worker.db,
        "complete_operation",
        lambda op_id, output, message: completed.update({"id": op_id, "output": output, "message": message}),
    )
    monkeypatch.setattr(worker.db, "fail_operation", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected failure")))

    assert worker.process_once("worker-1") is True

    assert saved["job_id"] == 5
    assert saved["pipeline_status"] == "shortlisted"
    assert saved["recruiter_message"] == "Hi recruiter"
    assert completed["output"]["materials_saved"] is True
    assert "Generating nvidia application materials." in progress
