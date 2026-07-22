import json

from scripts import select_probe_cases as selector


def _row(job_id: int, **overrides):
    row = {
        "job_id": job_id,
        "ranking_id": job_id,
        "item_status": "completed",
        "source": "linkedin_scraper",
        "company": f"Company {job_id}",
        "title": "Backend Engineer",
        "location": "Remote",
        "description_text": "Build Python FastAPI APIs.",
        "decision": "MAYBE",
        "final_score": 60,
        "confidence": 0.75,
        "scores_json": json.dumps({"central_requirement_coverage": 75}),
        "evidence_json": json.dumps(
            {
                "dealbreakers": [],
                "red_flags": [],
                "missing_requirements": [],
                "requires_llm_review": False,
                "central_requirement_coverage": 0.75,
            }
        ),
        "ranking_validation_attempts": 1,
        "ranking_validation_errors_json": "[]",
    }
    row.update(overrides)
    return row


def test_classify_probe_categories_detects_suspicious_apply_now():
    row = _row(
        10,
        decision="APPLY_NOW",
        final_score=88,
        evidence_json=json.dumps(
            {
                "dealbreakers": [],
                "red_flags": ["onsite location mismatch"],
                "missing_requirements": [],
                "requires_llm_review": False,
                "central_requirement_coverage": 0.7,
            }
        ),
    )

    categories = selector.classify_probe_categories(row, set(), {})

    assert "suspicious_apply_now" in categories
    assert "risk_evidence" in categories
    assert "low_central_coverage" in categories


def test_select_probe_cases_uses_known_hard_and_quotas():
    rows = [
        _row(1, decision="APPLY_NOW", final_score=90),
        _row(2, decision="SKIP", final_score=25),
        _row(3, item_status="queued", ranking_id=None, decision=None, final_score=None),
        _row(4, ranking_validation_attempts=2),
    ]
    known_hard = {2: {"job_id": 2, "label": "hard-skip"}}

    selected = selector.select_probe_cases(
        rows,
        target_total=3,
        category_quotas={"golden_failure": 1, "retry_or_schema": 1, "queued": 1},
        golden_failure_ids=set(),
        known_hard_cases=known_hard,
    )

    assert len(selected) == 3
    selected_by_id = {item["job_id"]: item for item in selected}
    assert selected_by_id[2]["known_hard_case"]["label"] == "hard-skip"
    assert "retry_or_schema" in selected_by_id[4]["categories"]
    assert "queued" in selected_by_id[3]["categories"]
