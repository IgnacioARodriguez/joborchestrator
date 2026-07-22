from __future__ import annotations

import json
import asyncio

import pandas as pd

from joborchestrator.ranking import nvidia_ranker
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MODEL,
    NVIDIA_RANKING_VERSION,
    NvidiaRankingError,
    build_nvidia_ranking_payload,
    rank_jobs_with_nvidia_async,
    rank_jobs_with_nvidia,
)


def profile_payload() -> dict:
    return {
        "target_roles": ["Backend Engineer"],
        "role_aliases": {"Backend Engineer": ["API Engineer"]},
        "skills": [{"name": "Python", "category": "Programming", "level": "strong"}],
        "preferred_locations": ["Spain"],
        "preferred_work_modes": ["remote"],
        "real_experience_years": 4,
        "dealbreakers": ["unpaid", "commission only", "mandatory relocation outside Spain/EU without remote option"],
    }


def profile_payload_no_industrial_automation() -> dict:
    payload = profile_payload()
    payload["dealbreakers"] = [
        *payload["dealbreakers"],
        "No industrial automation, PLC, SCADA, robotics, or plant electrical engineering.",
    ]
    return payload


def profile_payload_with_negative_gaps() -> dict:
    payload = profile_payload()
    payload["dealbreakers"] = [
        *payload["dealbreakers"],
        "No German language, Munich relocation, ERP consulting, or MS Dynamics background.",
        "No core security, cybersecurity, AppSec, or DevSecOps trajectory.",
    ]
    return payload


def test_build_nvidia_ranking_payload_compacts_jobs(monkeypatch):
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)

    payload = build_nvidia_ranking_payload(
        [
            {
                "id": 7,
                "title": "Backend Engineer",
                "company": "Acme",
                "description_text": "Python APIs " * 1000,
            }
        ]
    )

    assert payload["jobs"][0]["job_id"] == 7
    assert payload["jobs"][0]["title"] == "Backend Engineer"
    assert "[truncated]" in payload["jobs"][0]["description_text"]
    assert "candidate_profile" in payload
    assert payload["candidate_profile"]["strong_skills"] == ["Python"]
    assert payload["candidate_profile"]["role_aliases"] == {"Backend Engineer": ["API Engineer"]}
    assert payload["ranking_goal"]
    assert "scoring_rubric" in payload
    assert any("role_aliases" in rule for rule in payload["rules"])


def test_build_nvidia_ranking_payload_requires_profile(monkeypatch):
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", lambda: None)

    try:
        build_nvidia_ranking_payload([{"id": 1, "title": "Backend Engineer"}])
    except NvidiaRankingError as exc:
        assert "No candidate profile configured" in str(exc)
    else:
        raise AssertionError("Expected NvidiaRankingError")


def test_rank_jobs_with_nvidia_saves_each_ranking(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python FastAPI"},
            {"id": 2, "title": "C++ Engineer", "company": "Widgets", "description_text": "C++ Qt"},
        ]
    )
    saved = {}
    saved_metadata = {}

    async def fake_call(batch, **kwargs):
        return {
            "rankings": [
                _ranking_payload(1, 82, "APPLY_NOW"),
                _ranking_payload(2, 35, "SKIP"),
            ]
        }

    def fake_save(job_id, ranking, **kwargs):
        saved[job_id] = ranking
        saved_metadata[job_id] = kwargs
        return 1

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", fake_save)

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=2)

    assert summary["processed"] == 2
    assert summary["saved"] == 2
    assert summary["APPLY_NOW"] == 1
    assert summary["SKIP"] == 1
    assert saved[1].final_score == 82
    assert saved[1].ranking_version == NVIDIA_RANKING_VERSION
    assert "nvidia_ranking_applied" in saved[1].evidence.llm_escalation_reasons
    assert saved_metadata[1]["ranking_provider"] == "nvidia"
    assert saved_metadata[1]["ranking_model"] == DEFAULT_NVIDIA_MODEL
    assert saved_metadata[1]["ranking_validation_attempts"] == 1
    assert saved_metadata[1]["ranking_validation_errors"] == []
    assert len(saved_metadata[1]["ranking_candidate_profile_hash"]) == 64
    assert saved_metadata[1]["ranking_candidate_profile_snapshot"]


def test_rank_jobs_with_nvidia_async_runs_batches_concurrently(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"},
            {"id": 2, "title": "API Engineer", "company": "Acme", "description_text": "FastAPI"},
            {"id": 3, "title": "C++ Engineer", "company": "Widgets", "description_text": "C++ Qt"},
        ]
    )
    saved = {}
    active = 0
    max_active = 0

    async def fake_call(batch, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"rankings": [_ranking_payload(int(row["id"]), 80, "APPLY_NOW") for row in batch]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = asyncio.run(rank_jobs_with_nvidia_async(jobs, request_batch_size=1, max_concurrency=2))

    assert summary["processed"] == 3
    assert summary["saved"] == 3
    assert max_active == 2
    assert set(saved) == {1, 2, 3}


def test_rank_jobs_with_nvidia_reports_progress(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"},
            {"id": 2, "title": "API Engineer", "company": "Acme", "description_text": "FastAPI"},
        ]
    )
    progress_events = []

    async def fake_call(batch, **kwargs):
        await asyncio.sleep(0)
        return {"rankings": [_ranking_payload(int(row["id"]), 80, "APPLY_NOW") for row in batch]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: 1)

    summary = rank_jobs_with_nvidia(
        jobs,
        request_batch_size=1,
        max_concurrency=2,
        progress_callback=lambda done, total, current: progress_events.append((done, total, current["saved"])),
    )

    assert summary["saved"] == 2
    assert progress_events[-1] == (2, 2, 2)
    assert len(progress_events) == 2


def test_rank_jobs_with_nvidia_saves_partial_batch_when_response_omits_job(monkeypatch):
    jobs = pd.DataFrame(
        [
            {"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"},
            {"id": 2, "title": "API Engineer", "company": "Acme", "description_text": "FastAPI"},
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 80, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=2)

    assert summary["processed"] == 2
    assert summary["saved"] == 1
    assert summary["failed"] == 1
    assert set(saved) == {1}


def test_nvidia_ranking_is_capped_by_profile_dealbreaker_guards(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Relocation-heavy role",
                "company": "Acme",
                "description_text": "Visa relocation manual QA commission-only",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        payload = _ranking_payload(1, 91, "APPLY_NOW")
        payload["scores"]["technical_fit"] = 20
        payload["scores"]["seniority_fit"] = 20
        payload["scores"]["role_fit"] = 20
        payload["evidence"]["red_flags"] = ["relocation", "visa", "manual qa", "commission-only"]
        return {"rankings": [payload]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["saved"] == 1
    assert summary["APPLY_NOW"] == 0
    assert summary["AVOID"] == 1
    assert saved[1].final_score == 20
    assert saved[1].decision == "AVOID"
    assert "commission only" in saved[1].evidence.dealbreakers
    assert "hard_override_dealbreaker" in saved[1].evidence.llm_escalation_reasons
    assert saved[1].evidence.requires_llm_review is True


def test_nvidia_ranking_blocks_explicit_location_restriction(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Staff Software Engineer, Product",
                "company": "LawnStarter",
                "location": "Belo Horizonte, Brazil",
                "workplace_type": "hybrid",
                "description_text": "Remote role for candidates located in Belo Horizonte, Brazil. Staff-level product engineering role.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 88, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["AVOID"] == 1
    assert saved[1].decision == "AVOID"
    assert saved[1].final_score == 35
    assert "location restriction outside preferences: belo horizonte" in saved[1].evidence.dealbreakers
    assert "hard_override_location_restriction" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_downgrades_required_language_gap(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Senior ERP Consultant",
                "company": "Mytheresa",
                "location": "Munich, Germany",
                "description_text": "ERP implementation consultant. Fluent German required for stakeholder workshops.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 82, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload_with_negative_gaps)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["MAYBE"] == 1
    assert saved[1].decision == "MAYBE"
    assert saved[1].final_score == 55
    assert "German language requirement not supported by profile" in saved[1].evidence.dealbreakers
    assert "Munich location outside preferred remote/Spain profile" in saved[1].evidence.dealbreakers
    assert "safety_cap_language_gap" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_blocks_industrial_automation_mismatch(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Automation Engineer",
                "company": "PBiovian",
                "location": "Turku, Finland",
                "workplace_type": "onsite",
                "description_text": "Presencial role with manufacturing equipment, robotic systems, machinery control systems, and production requirements.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 80, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["AVOID"] == 1
    assert saved[1].decision == "AVOID"
    assert saved[1].final_score == 35
    assert "industrial automation/electrical domain mismatch" in saved[1].evidence.dealbreakers
    assert "hard_override_domain_mismatch" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_treats_negative_industrial_profile_as_gap(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Automation Engineer",
                "company": "PBiovian",
                "description_text": "Onsite/presencial industrial automation role for manufacturing equipment and control systems.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 80, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(
        nvidia_ranker.db,
        "get_candidate_profile_payload",
        profile_payload_no_industrial_automation,
    )
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["AVOID"] == 1
    assert saved[1].final_score == 35
    assert "industrial automation/electrical domain mismatch" in saved[1].evidence.dealbreakers


def test_nvidia_ranking_caps_hybrid_six_year_seniority_gap(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Backend Engineer (Python)",
                "company": "Datavant",
                "location": "Hibrido",
                "description_text": "Hybrid setting in Barcelona for Python backend, AWS/Kubernetes, and seniority around 6+ years.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 88, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].final_score == 82
    assert "hybrid role with 6+ years seniority gap" in saved[1].evidence.dealbreakers
    assert "safety_cap_hybrid_seniority_review" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_caps_unclear_india_remote_location(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Backend Developer- Python",
                "company": "Kyndryl",
                "location": "Bangalore, India, Chennai, India, Flexible / Remote",
                "description_text": "Locations listed as Bangalore India, Chennai India, Flexible/Remote, and Hyderabad India.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 88, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].final_score == 70
    assert "India location/remote eligibility requires review" in saved[1].evidence.dealbreakers


def test_nvidia_ranking_evidences_madrid_freelance_review(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Backend Python Freelance",
                "company": "Pixie",
                "location": "Madrid",
                "description_text": "Freelance backend Python contract role in Madrid for a client project.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 86, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].final_score == 75
    assert "Madrid freelance role requires tailored review" in saved[1].evidence.red_flags


def test_nvidia_ranking_caps_specialized_adjacent_roles(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Senior Security Engineer",
                "company": "MLB",
                "description_text": "Senior security engineer focused on AppSec, threat modeling, and vulnerability management.",
            },
            {
                "id": 2,
                "title": "Solutions Architect",
                "company": "GitLab",
                "description_text": "Customer-facing solutions architect for a DevSecOps platform with presales technical discovery and demos.",
            },
            {
                "id": 3,
                "title": "Sr. Infrastructure Engineer - Kubernetes",
                "company": "CrowdStrike",
                "description_text": "Senior Infrastructure Engineer for Kubernetes, reliability, and platform infrastructure.",
            },
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {
            "rankings": [
                _ranking_payload(1, 82, "APPLY_NOW"),
                _ranking_payload(2, 92, "APPLY_NOW"),
                _ranking_payload(3, 86, "APPLY_NOW"),
            ]
        }

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload_with_negative_gaps)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=3)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 3
    assert saved[1].decision == "APPLY_WITH_TAILORED_CV"
    assert saved[1].final_score == 68
    assert "security specialization outside core profile" in saved[1].evidence.red_flags
    assert saved[2].decision == "APPLY_WITH_TAILORED_CV"
    assert saved[2].final_score == 78
    assert "solutions architect/presales pivot requires tailoring" in saved[2].evidence.red_flags
    assert "security specialization outside core profile" not in saved[2].evidence.red_flags
    assert saved[3].decision == "APPLY_WITH_TAILORED_CV"
    assert saved[3].final_score == 68
    assert "senior infrastructure specialization outside core profile" in saved[3].evidence.red_flags


def test_nvidia_ranking_skips_low_context_spam_like_posting(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Apply Here",
                "company": "Conquer AI",
                "description_text": "Apply here. Include the magic word in your response.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 86, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["SKIP"] == 1
    assert saved[1].decision == "SKIP"
    assert saved[1].final_score == 25
    assert "low-context or spam-like posting" in saved[1].evidence.red_flags
    assert "generic low-context posting with magic word filter" in saved[1].evidence.dealbreakers


def test_nvidia_ranking_caps_contract_ai_training(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "AI Verification Contractor",
                "company": "HireFeed",
                "description_text": (
                    "Remote contract Python Developer. Work directly influences training and performance "
                    "of next-generation AI systems and shapes how AI models learn and reason."
                ),
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 88, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].final_score == 70
    assert "contract AI training/verification work" in saved[1].evidence.dealbreakers
    assert "safety_cap_contract_ai_training" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_blocks_autonomous_simulation_specialization(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Staff Simulation Engineer",
                "company": "GM",
                "description_text": "Autonomous driving vehicle simulation engineer for test frameworks and robotics simulation.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 84, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["AVOID"] == 1
    assert saved[1].final_score == 35
    assert "autonomous driving simulation specialization outside core profile" in saved[1].evidence.red_flags


def test_nvidia_ranking_caps_apply_now_when_model_reports_risky_evidence(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Senior AI Engineer",
                "company": "Acme",
                "description_text": "Build Python APIs plus production RAG systems and vector databases.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        payload = _ranking_payload(1, 88, "APPLY_NOW")
        payload["evidence"]["missing_requirements"] = ["production RAG systems", "vector databases"]
        payload["evidence"]["central_requirement_coverage"] = 0.65
        payload["scores"]["central_requirement_coverage"] = 65
        return {"rankings": [payload]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_NOW"] == 0
    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].decision == "APPLY_WITH_TAILORED_CV"
    assert saved[1].final_score == 78
    assert saved[1].evidence.requires_llm_review is True
    assert "evidence_consistency_cap_apply_now" in saved[1].evidence.llm_escalation_reasons
    assert "evidence_requires_review" in saved[1].evidence.llm_escalation_reasons


def test_nvidia_ranking_marks_tailored_risky_evidence_for_review(monkeypatch):
    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "title": "Hybrid Backend Engineer",
                "company": "Acme",
                "description_text": "Hybrid backend role with Python and location eligibility to verify.",
            }
        ]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        payload = _ranking_payload(1, 68, "APPLY_WITH_TAILORED_CV")
        payload["evidence"]["red_flags"] = ["location eligibility unclear"]
        return {"rankings": [payload]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["APPLY_WITH_TAILORED_CV"] == 1
    assert saved[1].evidence.requires_llm_review is True
    assert "evidence_requires_review" in saved[1].evidence.llm_escalation_reasons


def test_call_nvidia_batch_uses_chat_completions(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"rankings": [_ranking_payload(1, 80, "APPLY_NOW")]})
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(nvidia_ranker.httpx, "post", fake_post)
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)

    payload = nvidia_ranker._call_nvidia_batch(
        [{"id": 1, "title": "Backend Engineer", "description_text": "Python"}],
        model="test-model",
        api_key="nvapi-test",
        base_url="https://integrate.api.nvidia.com/v1",
        timeout=1,
    )

    assert payload["rankings"][0]["job_id"] == 1
    assert calls[0][0] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert calls[0][1]["json"]["model"] == "test-model"
    assert calls[0][1]["json"]["temperature"] == 0
    assert calls[0][1]["json"]["top_p"] == 0.95
    assert calls[0][1]["json"]["frequency_penalty"] == 0
    assert calls[0][1]["json"]["presence_penalty"] == 0
    assert calls[0][1]["json"]["stream"] is False
    assert calls[0][1]["json"]["response_format"] == {"type": "json_object"}


def test_default_nvidia_model_matches_nvidia_snippet():
    assert DEFAULT_NVIDIA_MODEL == "nvidia/llama-3.3-nemotron-super-49b-v1"


def test_nvidia_response_contract_does_not_request_speed_signal():
    assert "speed_signal" not in nvidia_ranker._response_contract()


def test_nvidia_response_contract_avoids_decision_placeholder():
    contract = nvidia_ranker._response_contract()

    assert "APPLY_NOW | APPLY_WITH_TAILORED_CV" not in contract
    assert "Never return the pipe-separated placeholder" in contract


def test_nvidia_response_contract_caps_apply_now_for_central_risk():
    contract = nvidia_ranker._response_contract()

    assert "APPLY_NOW is allowed only when" in contract
    assert "If evidence.dealbreakers is non-empty, decision must not be APPLY_NOW" in contract
    assert "If central_requirement_coverage is below 80, decision must not be APPLY_NOW" in contract
    assert "location, work mode, seniority, language, central domain, contract type, or role pivot" in contract


def test_nvidia_batch_validation_reports_missing_ids_and_invalid_decisions():
    result = {
        "rankings": [
            _ranking_payload(1, 80, "APPLY_NOW | APPLY_WITH_TAILORED_CV | MAYBE | SKIP | AVOID")
        ]
    }

    error = nvidia_ranker._nvidia_batch_validation_error(
        result,
        [{"id": 1}, {"id": 2}],
    )

    assert error is not None
    assert "missing job_id values [2]" in error
    assert "invalid decision values" in error


def test_nvidia_batch_validation_rejects_apply_with_zero_score():
    result = {"rankings": [_ranking_payload(1, 0, "APPLY_NOW")]}

    error = nvidia_ranker._nvidia_batch_validation_error(result, [{"id": 1}])

    assert error is not None
    assert "decision/score mismatch for job_id values [1]" in error


def test_nvidia_batch_validation_rejects_missing_contract_fields():
    payload = _ranking_payload(1, 80, "APPLY_NOW")
    del payload["scores"]["opportunity_quality"]
    del payload["evidence"]["requires_llm_review"]

    error = nvidia_ranker._nvidia_batch_validation_error({"rankings": [payload]}, [{"id": 1}])

    assert error is not None
    assert "contract shape errors" in error
    assert "job_id 1 missing" in error
    assert "scores.opportunity_quality" in error
    assert "evidence.requires_llm_review" in error


def test_rank_jobs_with_nvidia_skips_inconsistent_partial_result(monkeypatch):
    jobs = pd.DataFrame(
        [{"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"}]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        return {"rankings": [_ranking_payload(1, 0, "APPLY_NOW")]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["saved"] == 0
    assert summary["failed"] == 1
    assert saved == {}


def test_rank_jobs_with_nvidia_skips_incomplete_contract_partial_result(monkeypatch):
    jobs = pd.DataFrame(
        [{"id": 1, "title": "Backend Engineer", "company": "Acme", "description_text": "Python"}]
    )
    saved = {}

    async def fake_call(batch, **kwargs):
        payload = _ranking_payload(1, 80, "APPLY_NOW")
        del payload["evidence"]["central_requirement_thresholds"]
        return {"rankings": [payload]}

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia_ranker.db, "get_candidate_profile_payload", profile_payload)
    monkeypatch.setattr(nvidia_ranker, "_call_nvidia_batch_async", fake_call)
    monkeypatch.setattr(nvidia_ranker.db, "save_job_ranking", lambda job_id, ranking, **kwargs: saved.setdefault(job_id, ranking))

    summary = rank_jobs_with_nvidia(jobs, request_batch_size=1)

    assert summary["saved"] == 0
    assert summary["failed"] == 1
    assert saved == {}


def _ranking_payload(job_id: int, score: int, decision: str) -> dict:
    return {
        "job_id": job_id,
        "final_score": score,
        "decision": decision,
        "confidence": 0.88,
        "scores": {
            "technical_fit": score,
            "seniority_fit": score,
            "role_fit": score,
            "opportunity_quality": score,
            "application_roi": score,
            "market_alignment": score,
            "risk_penalty": 5,
            "technical_readiness": score,
            "central_requirement_coverage": score,
            "role_confidence": score,
            "application_effort_signal": score,
            "data_quality_signal": 80,
            "source_reliability_signal": 70,
        },
        "evidence": {
            "strong_matches": ["Python"] if decision == "APPLY_NOW" else [],
            "partial_matches": [],
            "missing_requirements": ["Core stack mismatch"] if decision == "SKIP" else [],
            "nice_to_have_matches": [],
            "dealbreakers": [],
            "red_flags": [],
            "central_requirement_coverage": score / 100,
            "central_requirement_raw_coverage": score / 100,
            "central_requirement_evidence_quality": 0.8,
            "requirement_backed_signal_count": 3,
            "central_requirement_thresholds": {},
            "central_requirements": [],
            "requires_llm_review": False,
            "llm_escalation_reasons": [],
        },
        "reasoning_summary": "Test ranking.",
        "recommended_application_angle": "Test angle.",
        "cv_keywords_to_emphasize": ["Python"],
        "cv_keywords_to_avoid_overclaiming": [],
    }
