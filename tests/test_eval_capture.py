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
        "contact": "igrodriguez.ar@gmail.com | +34 663 626 601 | linkedin.com/in/ignacio-a-rodriguez",
        "skills": [
            {"name": "Python", "level": "strong"},
            {"name": "FastAPI", "level": "strong"},
            {"name": "PostgreSQL", "level": "strong"},
        ],
    }


def test_capture_fixture_marks_expectations_for_human_review(monkeypatch):
    monkeypatch.setattr(capture.db, "get_job_posting", lambda job_id: _job())
    monkeypatch.setattr(capture.db, "get_candidate_profile_payload", _profile)
    monkeypatch.setattr(capture.db, "get_rankings_for_job_ids", lambda ranking_version, job_ids: _empty_rows())

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
    assert fixture["candidate_profile_snapshot"]["profile"]["contact"] == (
        "[redacted-email] | [redacted-phone] | [redacted-linkedin]"
    )
    assert {"Python", "FastAPI", "PostgreSQL"}.issubset(set(fixture["expected"]["required_keywords"]))
    assert "Review and edit" in fixture["human_review_instructions"]


def test_capture_fixture_drops_ranking_avoid_terms_from_materials_expectations(monkeypatch):
    job = {
        **_job(),
        "description_text": "Build AWS APIs with serverless architecture and Python.",
    }
    profile = {
        **_profile(),
        "skills": [
            *_profile()["skills"],
            {"name": "AWS", "level": "strong"},
            {"name": "Serverless", "level": "medium"},
        ],
    }
    monkeypatch.setattr(capture.db, "get_job_posting", lambda job_id: job)
    monkeypatch.setattr(capture.db, "get_candidate_profile_payload", lambda: profile)
    monkeypatch.setattr(capture.db, "get_rankings_for_job_ids", lambda ranking_version, job_ids: _ranking_rows())

    fixture = capture.build_capture_fixture(
        job_id=105,
        artifact="ats_cv",
        label="serverless-overclaiming",
    )

    assert "AWS" in fixture["expected"]["required_keywords"]
    assert "Serverless" not in fixture["expected"]["required_keywords"]


def test_capture_fixture_writes_under_surface_directory(tmp_path):
    fixture = {
        "case_id": "linkedin-acme-backend-ats-cv-internal-notes",
        "surface": "ats_cv",
    }

    path = capture.write_fixture(fixture, tmp_path)

    assert path == tmp_path / "ats_cv" / "linkedin-acme-backend-ats-cv-internal-notes.json"
    assert path.exists()


class _empty_rows:
    empty = True


class _ranking_rows:
    empty = False

    class _iloc:
        @staticmethod
        def __getitem__(index):
            return _row()

    iloc = _iloc()


class _row:
    @staticmethod
    def to_dict():
        return {
            "final_score": 78,
            "decision": "APPLY_WITH_TAILORED_CV",
            "confidence": 0.9,
            "scores_json": "{}",
            "evidence_json": "{}",
            "cv_keywords_to_emphasize_json": '["AWS", "Python"]',
            "cv_keywords_to_avoid_overclaiming_json": '["Serverless Architecture"]',
        }
