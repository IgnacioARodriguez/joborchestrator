from __future__ import annotations

import pandas as pd

from joborchestrator import worker


def test_worker_processes_cv_profile_import(monkeypatch):
    saved = {}
    completed = {}
    progress = []

    monkeypatch.setattr(worker.db, "requeue_stale_operations", lambda operation_types, stale_seconds: 0)
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

    monkeypatch.setattr(worker.db, "requeue_stale_operations", lambda operation_types, stale_seconds: 0)
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

    monkeypatch.setattr(worker.db, "requeue_stale_operations", lambda operation_types, stale_seconds: 0)
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
            "_generation_metadata": {
                "validation_attempts": 2,
                "validation_errors": ["recruiter_message is generic"],
            },
        },
    )
    monkeypatch.setattr(
        worker,
        "materials_prompt_versions",
        lambda: {"materials/nvidia_cv_contract": "v2", "materials/nvidia_kit_contract": "v2"},
    )
    monkeypatch.setattr(
        worker.db,
        "update_job_application_materials",
        lambda job_id, **kwargs: saved.update({"job_id": job_id, **kwargs}),
    )
    monkeypatch.setattr(
        worker.db,
        "register_generated_resume_variant",
        lambda job_id, label, ats_cv_text: {"id": 9, "label": label},
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
    assert saved["materials_provider"] == "nvidia"
    assert saved["materials_model"] == "test-model"
    assert saved["materials_prompt_versions"] == {
        "materials/nvidia_cv_contract": "v2",
        "materials/nvidia_kit_contract": "v2",
    }
    assert saved["materials_validation_attempts"] == 2
    assert saved["materials_validation_errors"] == ["recruiter_message is generic"]
    assert completed["output"]["materials_saved"] is True
    assert completed["output"]["resume_variant_id"] == 9
    assert "Generating nvidia application materials." in progress


def test_worker_processes_job_scan(monkeypatch):
    completed = {}
    progress = []

    monkeypatch.setattr(worker.db, "requeue_stale_operations", lambda operation_types, stale_seconds: 0)
    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: {
            "id": 31,
            "type": "job_scan",
            "input_json": {"include_ats": True, "include_search": False, "auto_rank_new": False},
        },
    )
    monkeypatch.setattr(worker.db, "update_operation_progress", lambda op_id, message: progress.append(message))

    async def fake_scan(input_payload, progress=None):
        if progress:
            progress("Fake scan running.")
        return {
            "ats": [],
            "search": [],
            "linkedin": None,
            "errors": {},
            "summary": {"new": 2, "updated": 1, "errors": 0},
        }

    monkeypatch.setattr(worker, "run_unified_job_scan", fake_scan)
    monkeypatch.setattr(
        worker.db,
        "complete_operation",
        lambda op_id, output, message: completed.update({"id": op_id, "output": output, "message": message}),
    )
    monkeypatch.setattr(worker.db, "fail_operation", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected failure")))

    assert worker.process_once("worker-1") is True

    assert completed["id"] == 31
    assert completed["output"]["summary"]["new"] == 2
    assert completed["message"] == "Job scan completed: 2 new, 1 updated, 0 errors."
    assert "Fake scan running." in progress


def test_worker_queues_ranking_for_new_scan_jobs(monkeypatch):
    completed = {}
    progress = []
    created_ranking_jobs = []

    monkeypatch.setattr(worker.db, "requeue_stale_operations", lambda operation_types, stale_seconds: 0)
    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: {
            "id": 32,
            "type": "job_scan",
            "created_at": "2026-07-15T10:00:00",
            "started_at": "2026-07-15T10:00:01",
            "input_json": {
                "include_ats": True,
                "include_search": False,
                "auto_rank_new": True,
                "ranking_limit": 10,
                "ranking_version": "ranking_v1.1.0-nvidia",
            },
        },
    )
    monkeypatch.setattr(worker.db, "update_operation_progress", lambda op_id, message: progress.append(message))

    async def fake_scan(input_payload, progress=None):
        return {
            "ats": [],
            "search": [],
            "linkedin": None,
            "errors": {},
            "summary": {"new": 1, "updated": 1, "errors": 0},
        }

    monkeypatch.setattr(worker, "run_unified_job_scan", fake_scan)
    monkeypatch.setattr(worker.db, "get_candidate_profile_payload", lambda: {"headline": "Backend engineer"})
    monkeypatch.setattr(
        worker.db,
        "get_jobs_for_post_scan_ranking",
        lambda seen_since, ranking_version, limit: pd.DataFrame([{"id": 10}, {"id": 11}]),
    )
    monkeypatch.setattr(
        worker.db,
        "create_ranking_job",
        lambda **kwargs: created_ranking_jobs.append(kwargs) or 77,
    )
    monkeypatch.setattr(
        worker.db,
        "complete_operation",
        lambda op_id, output, message: completed.update({"id": op_id, "output": output, "message": message}),
    )
    monkeypatch.setattr(worker.db, "fail_operation", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected failure")))

    assert worker.process_once("worker-1") is True

    assert completed["output"]["ranking_job"]["ranking_job_id"] == 77
    assert completed["output"]["ranking_job"]["queued"] == 2
    assert created_ranking_jobs[0]["job_ids"] == [10, 11]
    assert created_ranking_jobs[0]["ranking_version"] == "ranking_v1.1.0-nvidia"
    assert "Queueing NVIDIA ranking for 2 new or updated job(s)." in progress


def test_worker_requeues_stale_operations_before_claiming(monkeypatch):
    calls = []

    monkeypatch.setattr(
        worker.db,
        "requeue_stale_operations",
        lambda operation_types, stale_seconds: calls.append(("requeue", operation_types, stale_seconds)) or 1,
    )
    monkeypatch.setattr(
        worker.db,
        "claim_next_operation",
        lambda worker_id, operation_types: calls.append(("claim", operation_types)) or None,
    )

    assert worker.process_once("worker-1") is False
    assert calls[0] == ("requeue", worker.OPERATION_TYPES, worker.DEFAULT_STALE_SECONDS)
    assert calls[1] == ("claim", worker.OPERATION_TYPES)
