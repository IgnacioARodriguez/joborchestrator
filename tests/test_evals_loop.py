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


def test_loop_loads_only_reviewed_golden_fixtures(tmp_path):
    reviewed = tmp_path / "reviewed.json"
    draft = tmp_path / "draft.json"
    reviewed.write_text(json.dumps({"case_id": "reviewed", "review_status": "reviewed"}), encoding="utf-8")
    draft.write_text(json.dumps({"case_id": "draft", "review_status": "needs_human_review"}), encoding="utf-8")

    fixtures = loop.load_golden_fixtures(tmp_path)

    assert [fixture["case_id"] for fixture in fixtures] == ["reviewed"]


def test_loop_golden_fixture_case_maps_expected_by_surface():
    fixture = {
        "case_id": "golden-ats",
        "surface": "ats_cv",
        "review_status": "reviewed",
        "raw_input": {
            "title": "Backend Engineer",
            "company": "Acme",
            "job_html_or_text": "Python APIs",
        },
        "candidate_profile_snapshot": {
            "profile": {
                "base_cv_text": "Experience\nPython APIs",
                "skills": [{"name": "Python", "level": "strong"}],
            }
        },
        "expected": {"required_keywords": ["Python"]},
    }

    case = loop.golden_fixture_case(fixture)

    assert case["id"] == "golden-ats"
    assert case["review_status"] == "reviewed"
    assert case["ats_cv_expectations"] == {"required_keywords": ["Python"]}


def test_loop_golden_gate_requires_all_cases_to_pass():
    assert loop.is_golden_promotion_allowed({"reason": "no_golden_cases", "records": [], "skipped": []}) is True
    assert loop.is_golden_promotion_allowed(
        {"reason": "evaluated", "records": [{"artifact_type": "ats_cv", "case_id": "a", "passed": True, "score": 100, "issues": []}], "skipped": []}
    ) is True
    assert loop.is_golden_promotion_allowed(
        {"reason": "evaluated", "records": [{"artifact_type": "ats_cv", "case_id": "a", "passed": False, "score": 70, "issues": ["missing_required_keywords:Python"]}], "skipped": []}
    ) is False
    assert loop.is_golden_promotion_allowed(
        {"reason": "evaluated", "records": [], "skipped": [{"case_id": "a", "reason": "llm_call_cap"}]}
    ) is False


def test_loop_prompt_patch_failed_cases_are_limited():
    summary = {
        "records": [
            {
                "case_id": f"case-{index}",
                "artifact_type": "ats_cv",
                "job_id": index,
                "issues": ["missing_required_keywords:Python"],
                "candidate_output": {"ats_cv_text": "Draft"},
            }
            for index in range(7)
        ]
    }

    cases = loop.prompt_patch_failed_cases(summary, "missing_required_keywords")

    assert len(cases) == 5
    assert cases[0]["case_id"] == "case-0"
    assert cases[-1]["case_id"] == "case-4"


def test_loop_generates_llm_prompt_patch_proposal(monkeypatch):
    calls = []

    class FakeResponse:
        text = json.dumps({"proposed_prompt": "New prompt text", "rationale": "Tighten the rule."})

    class FakeProvider:
        def complete(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return FakeResponse()

    class FakeRegistry:
        def get(self, role, **kwargs):
            assert role == "judge"
            return FakeProvider()

    monkeypatch.setattr(loop, "ProviderRegistry", FakeRegistry)

    proposal = loop.generate_prompt_patch_proposal(
        Namespace(hypothesis_provider="openai", hypothesis_model="patch-model"),
        prompt_target="materials/nvidia_cv_contract",
        current_prompt="Current prompt",
        worst_issue={"issue": "missing_required_keywords", "count": 2},
        before_summary={"records": []},
        remaining_llm_calls=1,
    )

    assert proposal["proposed_prompt"] == "New prompt text"
    assert proposal["rationale"] == "Tighten the rule."
    assert proposal["llm_calls_used"] == 1
    assert calls[0][1]["model"] == "patch-model"


def test_loop_prompt_patch_proposal_requires_call_budget():
    try:
        loop.generate_prompt_patch_proposal(
            Namespace(hypothesis_provider="openai", hypothesis_model=None),
            prompt_target="materials/nvidia_cv_contract",
            current_prompt="Current prompt",
            worst_issue={"issue": "missing_required_keywords"},
            before_summary={"records": []},
            remaining_llm_calls=0,
        )
    except RuntimeError as exc:
        assert "No LLM calls remaining" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


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


def test_loop_renders_human_readable_summary_report():
    report = loop.render_summary_report(
        {
            "branch": "agent/test",
            "accepted_patches": 1,
            "iterations": [
                {
                    "iteration": 1,
                    "summary": {"pass_rate": 0.75, "passed": 3, "evaluated": 4, "failed": 1},
                    "worst_issue": {"issue": "missing_required_keywords"},
                    "prompt_target": "materials/nvidia_cv_contract",
                    "patch": {
                        "mode": "applied",
                        "accepted": True,
                        "before": {"pass_rate": 0.5, "failed": 2},
                        "after": {"pass_rate": 0.75, "failed": 1},
                        "golden": {"reason": "no_golden_cases", "skipped": []},
                    },
                }
            ],
        }
    )

    assert "# Eval Loop Summary" in report
    assert "Branch: agent/test" in report
    assert "Worst issue: missing_required_keywords" in report
    assert "Patch gate: before pass_rate=0.5 failed=2; after pass_rate=0.75 failed=1" in report


def test_loop_write_audit_also_writes_markdown_report(tmp_path):
    audit_path = tmp_path / "eval_loop_test.json"
    args = Namespace(
        surfaces="ranking",
        max_iterations=1,
        stop_if_no_improvement=2,
        llm_call_cap=0,
        apply_prompt_patch=False,
        regenerate_affected=False,
        regeneration_provider="openai",
        hypothesis_provider="openai",
        commit_accepted_patches=False,
        no_compare_last_run=True,
        golden_cases=tmp_path / "golden",
    )

    loop.write_audit(audit_path, args, "agent/test", [{"iteration": 1, "summary": {}}], 0)

    assert audit_path.exists()
    assert audit_path.with_suffix(".md").exists()
    assert "Eval Loop Summary" in audit_path.with_suffix(".md").read_text(encoding="utf-8")
