from scripts import capture_llm_eval_fixture as capture


def _job() -> dict:
    return {
        "id": 105,
        "source": "linkedin",
        "title": "Backend Engineer",
        "company": "Acme Labs",
        "location": "Remote Spain",
        "description_text": "Build Python FastAPI APIs with PostgreSQL for product teams.",
        "apply_url": None,
        "easy_apply": True,
        "ats_cv_text": "Professional Summary\nPython FastAPI PostgreSQL",
        "recruiter_message": "Hi Acme, Python/FastAPI fit.",
        "cover_letter": "Acme Labs backend role.",
        "autofill_notes": "Use the backend angle.",
    }


def _profile() -> dict:
    return {
        "base_cv_text": "Ignacio Rodriguez\nExperience\nFiction Express\nPython FastAPI PostgreSQL APIs",
        "skills": [
            {"name": "Python", "level": "strong"},
            {"name": "FastAPI", "level": "strong"},
            {"name": "PostgreSQL", "level": "strong"},
        ],
    }


def test_capture_fixture_marks_expectations_for_human_review(monkeypatch):
    monkeypatch.setattr(capture.db, "get_job_posting", lambda job_id: _job())
    monkeypatch.setattr(capture.db, "get_candidate_profile_payload", _profile)

    fixture = capture.build_capture_fixture(
        job_id=105,
        artifact="ats_cv",
        label="ats-cv-internal-notes",
    )

    assert fixture["surface"] == "ats_cv"
    assert fixture["review_status"] == "needs_human_review"
    assert fixture["raw_input"]["source"] == "linkedin"
    assert fixture["raw_input"]["easy_apply"] is True
    assert fixture["current_output"]["ats_cv_text"].startswith("Professional Summary")
    assert {"Python", "FastAPI", "PostgreSQL"}.issubset(set(fixture["expected"]["required_keywords"]))
    assert "Review and edit" in fixture["human_review_instructions"]


def test_capture_fixture_writes_under_surface_directory(tmp_path):
    fixture = {
        "case_id": "linkedin-acme-backend-ats-cv-internal-notes",
        "surface": "ats_cv",
    }

    path = capture.write_fixture(fixture, tmp_path)

    assert path == tmp_path / "ats_cv" / "linkedin-acme-backend-ats-cv-internal-notes.json"
    assert path.exists()
