from scripts import run_evals_loop as loop
from argparse import Namespace
import json


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
    assert summary["judge_issue_counts"] == {}
    assert summary["all_issue_counts"] == {"ats_cv_contains_internal_notes": 1}


def test_loop_summarizes_judge_issue_counts_separately():
    summary = loop.summarize_records(
        [
            {
                "artifact_type": "ats_cv",
                "case_id": "a",
                "passed": False,
                "score": 70,
                "issues": ["ats_cv_contains_internal_notes:target role"],
                "judge_result": {"issue_codes": ["unsupported_claims"]},
            },
        ]
    )

    assert summary["issue_counts"] == {"ats_cv_contains_internal_notes": 1}
    assert summary["judge_issue_counts"] == {"unsupported_claims": 1}
    assert summary["all_issue_counts"] == {"ats_cv_contains_internal_notes": 1, "unsupported_claims": 1}


def test_loop_maps_issues_to_prompt_owner():
    assert loop.prompt_owner_for_issue("missing_evidence_terms") == "ranking/nvidia_response_contract"
    assert loop.prompt_owner_for_issue("recruiter_message_too_long") == "materials/nvidia_kit_contract"
    assert loop.prompt_owner_for_issue("omitted_base_experience") == "materials/nvidia_cv_contract"


def test_loop_selects_worst_issue_by_frequency_times_severity():
    selected = loop.select_worst_issue(
        {"issue_counts": {"recruiter_message_too_long": 3, "unsupported_claims": 2}}
    )

    assert selected == {"issue": "unsupported_claims", "count": 2, "severity": 3, "source": "deterministic"}


def test_loop_selects_worst_issue_skips_unowned_issues():
    selected = loop.select_worst_issue(
        {"issue_counts": {"judge_other": 99, "recruiter_message_too_long": 1}}
    )

    assert selected == {"issue": "recruiter_message_too_long", "count": 1, "severity": 1, "source": "deterministic"}


def test_loop_selects_worst_issue_from_judge_pool():
    selected = loop.select_worst_issue(
        {"issue_counts": {}, "judge_issue_counts": {"missing_evidence_terms": 2}}
    )

    assert selected == {"issue": "missing_evidence_terms", "count": 2, "severity": 1, "source": "judge"}


def test_loop_detects_wired_prompt_targets():
    assert loop.is_prompt_target_wired("ranking/nvidia_response_contract") is True
    assert loop.is_prompt_target_wired("materials/nvidia_cv_contract") is True
    assert loop.is_prompt_target_wired("materials/nvidia_kit_contract") is True
    assert loop.is_prompt_target_wired("materials/missing_contract") is False


def test_loop_detects_critical_hard_stop():
    summary = {"issue_counts": {"unsupported_claims": 1}}

    assert loop.hard_stop_reason(summary) == "critical_issue:unsupported_claims"


def test_loop_promotion_rule_rejects_regressions():
    before = {"pass_rate": 0.7, "failed": 3, "issue_counts": {}}
    after = {"pass_rate": 0.6, "failed": 4, "issue_counts": {}}

    assert loop.is_promotion_allowed(before, after) is False


def test_loop_promotion_rule_rejects_case_regression_despite_better_aggregate():
    before = {
        "pass_rate": 0.5,
        "failed": 2,
        "issue_counts": {},
        "records": [
            {"artifact_type": "ranking", "case_id": "stable-pass", "passed": True},
            {"artifact_type": "ranking", "case_id": "regressed", "passed": True},
            {"artifact_type": "ranking", "case_id": "fixed-a", "passed": False},
            {"artifact_type": "ranking", "case_id": "fixed-b", "passed": False},
        ],
    }
    after = {
        "pass_rate": 0.75,
        "failed": 1,
        "issue_counts": {},
        "records": [
            {"artifact_type": "ranking", "case_id": "stable-pass", "passed": True},
            {"artifact_type": "ranking", "case_id": "regressed", "passed": False},
            {"artifact_type": "ranking", "case_id": "fixed-a", "passed": True},
            {"artifact_type": "ranking", "case_id": "fixed-b", "passed": True},
        ],
    }

    assert loop.is_promotion_allowed(before, after) is False


def test_loop_promotion_rule_excludes_needs_human_review_records():
    before = {
        "records": [
            {"artifact_type": "ats_cv", "case_id": "draft-a", "passed": False, "review_status": "needs_human_review"},
        ]
    }
    after = {
        "records": [
            {"artifact_type": "ats_cv", "case_id": "draft-a", "passed": True, "review_status": "needs_human_review"},
        ]
    }

    assert loop.promotion_gate_summary(before)["promotion_gate_excluded"] == 1
    assert loop.is_promotion_allowed(before, after) is False


def test_loop_promotion_rule_rejects_reviewed_regression_when_unreviewed_improves():
    before = {
        "records": [
            {"artifact_type": "ranking", "case_id": "reviewed", "passed": True, "review_status": "reviewed"},
            {"artifact_type": "ats_cv", "case_id": "draft-a", "passed": False, "review_status": "needs_human_review"},
            {"artifact_type": "ats_cv", "case_id": "draft-b", "passed": False, "review_status": "needs_human_review"},
        ]
    }
    after = {
        "records": [
            {"artifact_type": "ranking", "case_id": "reviewed", "passed": False, "review_status": "reviewed"},
            {"artifact_type": "ats_cv", "case_id": "draft-a", "passed": True, "review_status": "needs_human_review"},
            {"artifact_type": "ats_cv", "case_id": "draft-b", "passed": True, "review_status": "needs_human_review"},
        ]
    }

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


def test_loop_prompt_diff_is_unified():
    diff = loop.unified_prompt_diff(
        "Line one\nLine two\n",
        "Line one\nLine three\n",
        from_label="prompt:v1",
        to_label="prompt:v2",
    )

    assert "--- prompt:v1" in diff
    assert "+++ prompt:v2" in diff
    assert "-Line two" in diff
    assert "+Line three" in diff


def test_loop_commit_accepted_patch_stages_registry_and_prompt(monkeypatch, tmp_path):
    calls = []
    prompt_path = loop.PROJECT_ROOT / "prompts" / "materials" / "nvidia_cv_contract" / "v2.md"

    def fake_run(command, cwd=None, check=None, **kwargs):
        calls.append((command, cwd, check))

    monkeypatch.setattr(loop.subprocess, "run", fake_run)

    loop.commit_accepted_patch(prompt_path, "ats_cv_contains_internal_notes", 2)

    assert calls[0][0][:3] == ["git", "add", "--"]
    assert "prompts\\registry.json" in calls[0][0] or "prompts/registry.json" in calls[0][0]
    assert calls[1][0][:3] == ["git", "commit", "-m"]
    assert "iteration 2" in calls[1][0][3]


def test_loop_compare_uses_case_statuses_without_records():
    previous = {"case_statuses": {"ranking:a": True, "ats_cv:b": True}, "pass_rate": 1.0, "average_score": 95}
    current = {"case_statuses": {"ranking:a": True, "ats_cv:b": False}, "pass_rate": 0.5, "average_score": 80}

    diff = loop.compare_summaries(previous, current)

    assert diff["pass_rate_delta"] == -0.5
    assert diff["score_delta"] == -15
    assert diff["regressions"] == ["ats_cv:b"]


def test_loop_loads_previous_audit_summary(tmp_path):
    audit = tmp_path / "eval_loop_20260101_120000.json"
    audit.write_text(
        json.dumps(
            {
                "iterations": [
                    {
                        "summary": {"pass_rate": 0.75, "average_score": 88},
                        "case_statuses": {"ranking:a": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = loop.load_previous_audit_summary(tmp_path)

    assert summary == {"pass_rate": 0.75, "average_score": 88, "case_statuses": {"ranking:a": True}}
