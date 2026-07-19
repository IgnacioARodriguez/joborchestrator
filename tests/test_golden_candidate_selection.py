from scripts import select_llm_golden_candidates as selector


def _row(job_id: int, **overrides):
    row = {
        "job_id": job_id,
        "source": "linkedin_scraper",
        "company": f"Company {job_id}",
        "title": "Backend Engineer",
        "location": "Remote",
        "status": "new",
        "description_text": "Build Python FastAPI APIs with PostgreSQL for product teams. " * 20,
        "data_quality_flags": "[]",
        "parse_confidence": 0.9,
        "recruiter_message": "",
        "cover_letter": "",
        "ats_cv_text": "",
        "autofill_notes": "",
        "ranking_id": job_id,
        "final_score": 82,
        "decision": "APPLY_NOW",
        "confidence": 0.9,
        "evidence_json": "{}",
        "scores_json": "{}",
        "ranking_updated_at": "2026-07-19T00:00:00",
    }
    row.update(overrides)
    return row


def test_candidate_buckets_cover_dealbreaker_and_low_context():
    row = _row(
        1,
        title="Senior Rust Kernel Engineer",
        description_text="Requires Rust kernel, device drivers, and relocation to Berlin.",
        final_score=22,
        decision="AVOID",
        parse_confidence=0.5,
    )

    buckets = selector.classify_buckets(row)

    assert "negative_or_dealbreaker" in buckets
    assert "low_context" in buckets
    assert {"rust", "kernel", "relocation"}.issubset(set(selector.dealbreaker_terms(row)))


def test_dealbreaker_terms_do_not_match_inside_other_words():
    row = _row(5, description_text="Build trusted APIs and customer trust workflows.")

    assert selector.dealbreaker_terms(row) == []


def test_candidate_record_uses_safe_draft_capture_root():
    row = _row(
        2,
        recruiter_message="Hi Company, Python/FastAPI fit.",
        ats_cv_text="Professional Summary\nPython FastAPI PostgreSQL",
    )

    record = selector.candidate_record(row)

    assert "materials_ready" in record["buckets"]
    assert record["recommended_surfaces"] == ["ranking", "application_materials", "ats_cv"]
    assert all("logs/llm_eval_fixture_drafts" in command for command in record["safe_capture_commands"])
    assert all("evals/fixtures" not in command for command in record["safe_capture_commands"])


def test_review_packet_selects_distinct_candidates_and_marks_human_review():
    rows = [
        _row(1, final_score=88, decision="APPLY_NOW"),
        _row(2, final_score=58, decision="MAYBE"),
        _row(3, final_score=20, decision="AVOID", description_text="Commission-only role with relocation."),
        _row(4, final_score=72, decision="APPLY_WITH_TAILORED_CV", ats_cv_text="CV text"),
    ]

    packet = selector.build_review_packet(
        rows,
        ranking_version="ranking_v1.1.0-nvidia",
        target_total=4,
        generated_at="2026-07-19T00:00:00+00:00",
    )

    assert packet["review_status"] == "needs_human_review"
    assert packet["candidate_count"] == 4
    assert len({candidate["job_id"] for candidate in packet["candidates"]}) == 4
    assert packet["protected_fixture_policy"].startswith("This packet is only a review queue")
