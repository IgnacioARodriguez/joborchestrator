import json

from scripts import select_probe_cases


def test_classify_probe_categories_treats_zero_coverage_as_low_and_suspicious():
    row = {
        "job_id": 1,
        "item_status": "completed",
        "decision": "APPLY_NOW",
        "final_score": 90,
        "scores_json": json.dumps({"central_requirement_coverage": 0.0}),
        "evidence_json": json.dumps(
            {
                "dealbreakers": [],
                "red_flags": [],
                "missing_requirements": [],
                "requires_llm_review": False,
                "central_requirement_coverage": 0.0,
            }
        ),
        "ranking_validation_attempts": 1,
        "ranking_validation_errors_json": "[]",
    }

    categories = select_probe_cases.classify_probe_categories(
        row,
        golden_failure_ids=set(),
        known_hard_cases={},
    )

    assert "low_central_coverage" in categories
    assert "suspicious_apply_now" in categories
