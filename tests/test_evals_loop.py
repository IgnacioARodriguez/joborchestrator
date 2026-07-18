from scripts import run_evals_loop as loop
from argparse import Namespace


def test_loop_summarizes_by_surface_and_issue_counts():
    summary = loop.summarize_records(
        [
            {"artifact_type": "ranking", "case_id": "a", "passed": True, "score": 100, "issues": []},
            {
                "artifact_type": "ats_cv",
                "case_id": "b",
                "passed": False,
                "score": 70,
                "issues": ["ats_cv_contains_internal_notes:target role"],
            },
        ]
    )

    assert summary["pass_rate"] == 0.5
    assert summary["by_surface"]["ranking"]["pass_rate"] == 1.0
    assert summary["by_surface"]["ats_cv"]["failed"] == 1
    assert summary["issue_counts"] == {"ats_cv_contains_internal_notes": 1}


def test_loop_maps_issues_to_prompt_owner():
    assert loop.prompt_owner_for_issue("missing_evidence_terms") == "ranking/nvidia_response_contract"
    assert loop.prompt_owner_for_issue("recruiter_message_too_long") == "materials/nvidia_kit_contract"
    assert loop.prompt_owner_for_issue("omitted_base_experience") == "materials/nvidia_cv_contract"


def test_loop_selects_worst_issue_by_frequency_times_severity():
    selected = loop.select_worst_issue(
        {"issue_counts": {"recruiter_message_too_long": 3, "unsupported_claims": 2}}
    )

    assert selected == {"issue": "unsupported_claims", "count": 2, "severity": 3}


def test_loop_detects_critical_hard_stop():
    summary = {"issue_counts": {"unsupported_claims": 1}}

    assert loop.hard_stop_reason(summary) == "critical_issue:unsupported_claims"


def test_loop_promotion_rule_rejects_regressions():
    before = {"pass_rate": 0.7, "failed": 3, "issue_counts": {}}
    after = {"pass_rate": 0.6, "failed": 4, "issue_counts": {}}

    assert loop.is_promotion_allowed(before, after) is False


def test_loop_parses_surface_aliases():
    assert loop.parse_surfaces("ranking,materials,ats_cv") == [
        "ranking",
        "application_materials",
        "ats_cv",
    ]


def test_loop_selects_affected_records_for_prompt_owner():
    summary = {
        "records": [
            {
                "artifact_type": "ats_cv",
                "case_id": "a",
                "issues": ["ats_cv_contains_internal_notes:target role"],
            },
            {
                "artifact_type": "application_materials",
                "case_id": "b",
                "issues": ["ats_cv_contains_internal_notes:target role"],
            },
        ]
    }

    affected = loop.affected_records(summary, "ats_cv_contains_internal_notes", "materials/nvidia_cv_contract")

    assert [record["case_id"] for record in affected] == ["a"]


def test_loop_regeneration_respects_llm_call_cap(monkeypatch):
    before = {
        "records": [
            {"artifact_type": "application_materials", "case_id": "a", "job_id": 1, "issues": ["recruiter_message_too_long:400>320"]},
            {"artifact_type": "application_materials", "case_id": "b", "job_id": 2, "issues": ["recruiter_message_too_long:420>320"]},
        ]
    }

    def fake_regenerate(args, record):
        return {**record, "passed": True, "score": 100, "issues": []}

    monkeypatch.setattr(loop, "regenerate_record", fake_regenerate)

    result = loop.regenerate_affected_records(
        Namespace(regeneration_provider="nvidia"),
        before,
        "recruiter_message_too_long",
        "materials/nvidia_kit_contract",
        remaining_llm_calls=2,
    )

    assert [record["case_id"] for record in result["records"]] == ["a"]
    assert result["llm_calls_used"] == 2
    assert result["skipped"] == [{"case_id": "b", "reason": "llm_call_cap"}]
