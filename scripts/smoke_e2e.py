from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from joborchestrator import api
from joborchestrator import worker as operation_worker
from joborchestrator.evals.llm_judge import judge_with_configured_providers
from joborchestrator.evals.semantic import (
    build_auto_eval_case,
    build_llm_judge_payload,
    evaluate_application_materials,
    evaluate_ats_cv_result,
    evaluate_ranking_result,
)
from joborchestrator.ranking import worker as ranking_worker
from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.storage import persistence as db

DEFAULT_PRIMARY_JUDGE_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1"
DEFAULT_SECONDARY_JUDGE_MODEL = "mistralai/mistral-nemotron"


def run_smoke_e2e(
    *,
    db_path: Path | None = None,
    live_llm: bool = False,
    live_judge: bool = False,
    judge_artifacts: list[str] | None = None,
    ranking_model: str | None = None,
    materials_model: str | None = None,
    judge_model: str = DEFAULT_PRIMARY_JUDGE_MODEL,
    secondary_judge_model: str = DEFAULT_SECONDARY_JUDGE_MODEL,
) -> dict[str, Any]:
    """Run a narrow full-flow smoke test against a temporary SQLite database."""
    with _isolated_sqlite_db(db_path) as active_db:
        db.init_db()
        client = TestClient(api.app)

        profile = synthetic_profile()
        profile_response = client.put("/api/profile", json={"profile": profile})
        _require_status(profile_response.status_code, 200, "profile.put", profile_response.text)

        job_response = client.post("/api/jobs", json=synthetic_job_payload())
        _require_status(job_response.status_code, 200, "jobs.create", job_response.text)
        job = job_response.json()["job"]
        job_id = int(job["id"])

        ranking_job_id = _queue_ranking(client, job_id, ranking_model)
        with _external_call_patches(live_llm):
            ranking_processed = ranking_worker.run_worker_once(ranking_job_id=ranking_job_id, chunk_size=5)
            materials_operation_id = _queue_materials(client, job_id, materials_model)
            materials_processed = operation_worker.process_once(worker_id="smoke-e2e")

        refreshed = db.get_job_posting(job_id)
        if not refreshed:
            raise RuntimeError("Smoke e2e job disappeared after materials generation.")
        rankings = db.get_rankings_for_job_ids(NVIDIA_RANKING_VERSION, [job_id])
        if rankings.empty:
            raise RuntimeError("Smoke e2e did not persist a ranking.")

        ranking_output = _ranking_row_to_output(rankings.iloc[0].to_dict())
        materials_output = {
            "recruiter_message": refreshed.get("recruiter_message") or "",
            "cover_letter": refreshed.get("cover_letter") or "",
            "ats_cv_text": refreshed.get("ats_cv_text") or "",
            "autofill_notes": refreshed.get("autofill_notes") or "",
        }
        case = build_auto_eval_case(db.get_job_posting(job_id), profile)
        ranking_eval = evaluate_ranking_result(case, ranking_output)
        materials_eval = evaluate_application_materials(case, materials_output)
        ats_cv_eval = evaluate_ats_cv_result(case, {"ats_cv_text": materials_output["ats_cv_text"]})

        opened = client.post(f"/api/jobs/{job_id}/opened", json={})
        _require_status(opened.status_code, 200, "jobs.opened", opened.text)
        application = client.post(
            f"/api/jobs/{job_id}/applications",
            json={"ats_type": "greenhouse", "status": "preparing", "channel": "portal"},
        )
        _require_status(application.status_code, 200, "applications.create", application.text)
        application_id = int(application.json()["application"]["id"])
        submitted = client.patch(f"/api/applications/{application_id}", json={"status": "submitted"})
        _require_status(submitted.status_code, 200, "applications.submit", submitted.text)

        evals = {
            "ranking": _eval_to_dict(ranking_eval),
            "application_materials": _eval_to_dict(materials_eval),
            "ats_cv": _eval_to_dict(ats_cv_eval),
        }
        judge_results = _run_live_judges(
            live_judge=live_judge,
            judge_artifacts=judge_artifacts or ["ranking", "application_materials", "ats_cv"],
            case=case,
            outputs={
                "ranking": ranking_output,
                "application_materials": materials_output,
                "ats_cv": {"ats_cv_text": materials_output["ats_cv_text"]},
            },
            judge_model=judge_model,
            secondary_judge_model=secondary_judge_model,
        )

        return {
            "passed": all(result["passed"] for result in evals.values())
            and all(result.get("passed") for result in judge_results.values()),
            "mode": "live_llm" if live_llm else "offline",
            "database": str(active_db),
            "job_id": job_id,
            "ranking_job_id": ranking_job_id,
            "materials_operation_id": materials_operation_id,
            "processed": {
                "ranking_worker": ranking_processed,
                "materials_worker": materials_processed,
            },
            "api": {
                "job_title": refreshed["title"],
                "pipeline_status": refreshed["pipeline_status"],
                "application_status": submitted.json()["application"]["status"],
                "ranking_decision": ranking_output["decision"],
                "ranking_score": ranking_output["final_score"],
            },
            "evals": evals,
            "judge_results": judge_results,
        }


def synthetic_profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "headline": "Senior backend engineer",
        "target_roles": ["Senior Backend Engineer", "Platform Engineer"],
        "secondary_roles": ["API Engineer"],
        "role_aliases": {},
        "skills": [
            {"name": "Python", "category": "Programming", "level": "strong", "evidence": "Built production APIs."},
            {"name": "FastAPI", "category": "Backend", "level": "strong", "evidence": "Maintained FastAPI services."},
            {"name": "PostgreSQL", "category": "Data", "level": "strong", "evidence": "Designed relational schemas."},
            {"name": "AWS", "category": "Cloud", "level": "medium", "evidence": "Operated cloud services."},
        ],
        "industries": ["SaaS"],
        "preferred_locations": ["Remote Spain"],
        "preferred_work_modes": ["remote"],
        "application_targets": [{"label": "Spain remote", "location": "Spain", "work_modes": ["remote"]}],
        "dealbreakers": [],
        "avoid_roles": ["commission-only sales"],
        "real_experience_years": 7,
        "notes": "Prefers backend/platform roles with Python.",
        "base_cv_text": (
            "Ignacio Rodriguez\n"
            "Senior Backend Engineer\n\n"
            "Summary\n"
            "Backend engineer with 7 years building Python, FastAPI, PostgreSQL and AWS systems.\n\n"
            "Skills\n"
            "Python, FastAPI, PostgreSQL, AWS, APIs, distributed systems.\n\n"
            "Experience\n"
            "Acme SaaS - Senior Backend Engineer - Built FastAPI services and PostgreSQL data models.\n\n"
            "Education\n"
            "BSc Computer Science."
        ),
        "base_cv_filename": "synthetic-cv.txt",
    }


def synthetic_job_payload() -> dict[str, Any]:
    return {
        "external_id": "smoke-e2e-senior-backend",
        "source": "greenhouse",
        "company": "Acme Cloud",
        "title": "Senior Backend Engineer",
        "url": "https://boards.greenhouse.io/acmecloud/jobs/smoke-e2e",
        "apply_url": "https://boards.greenhouse.io/acmecloud/jobs/smoke-e2e",
        "description_text": (
            "Acme Cloud is hiring a Senior Backend Engineer in Remote Spain. "
            "Requirements: 5+ years backend experience, Python, FastAPI, PostgreSQL, AWS, API design. "
            "The role builds production services and data models for a SaaS platform."
        ),
    }


def _queue_ranking(client: TestClient, job_id: int, model: str | None) -> int:
    response = client.post(
        "/api/ranking/jobs",
        json={
            "job_ids": [job_id],
            "limit": 1,
            "run_once": False,
            "model": model or "smoke/offline-ranking",
            "ranking_version": NVIDIA_RANKING_VERSION,
            "request_batch_size": 1,
            "max_concurrency": 1,
        },
    )
    _require_status(response.status_code, 200, "ranking.queue", response.text)
    ranking_job_id = response.json().get("ranking_job_id")
    if not ranking_job_id:
        raise RuntimeError("Ranking queue did not create a ranking job.")
    return int(ranking_job_id)


def _queue_materials(client: TestClient, job_id: int, model: str | None) -> int:
    payload = {"provider": "nvidia", "shortlist": True}
    if model:
        payload["model"] = model
    response = client.post(
        f"/api/jobs/{job_id}/materials",
        json=payload,
    )
    _require_status(response.status_code, 200, "materials.queue", response.text)
    operation_id = response.json().get("operation_id")
    if not operation_id:
        raise RuntimeError("Materials queue did not create an operation.")
    return int(operation_id)


@contextmanager
def _isolated_sqlite_db(db_path: Path | None) -> Iterator[Path]:
    old_path = db.DB_PATH
    old_turso_url = os.environ.pop("TURSO_DATABASE_URL", None)
    old_turso_token = os.environ.pop("TURSO_AUTH_TOKEN", None)
    with tempfile.TemporaryDirectory(prefix="joborchestrator-smoke-") as tmp_dir:
        active_path = db_path or Path(tmp_dir) / "smoke_e2e.db"
        db.DB_PATH = active_path
        try:
            yield active_path
        finally:
            db.DB_PATH = old_path
            if old_turso_url is not None:
                os.environ["TURSO_DATABASE_URL"] = old_turso_url
            if old_turso_token is not None:
                os.environ["TURSO_AUTH_TOKEN"] = old_turso_token


@contextmanager
def _external_call_patches(live_llm: bool) -> Iterator[None]:
    if live_llm:
        yield
        return
    with patch.object(ranking_worker, "rank_jobs_with_nvidia", _fake_rank_jobs_with_nvidia), patch.object(
        operation_worker,
        "build_application_kit_with_nvidia",
        _fake_build_application_kit_with_nvidia,
    ):
        yield


def _fake_rank_jobs_with_nvidia(jobs: Any, **kwargs: Any) -> dict[str, int]:
    saved = 0
    for _, row in jobs.iterrows():
        ranking = RankingResult(
            final_score=91,
            decision="APPLY_NOW",
            confidence=0.93,
            scores=RankingScores(
                technical_fit=94,
                seniority_fit=92,
                role_fit=93,
                opportunity_quality=84,
                application_roi=92,
                market_alignment=88,
                risk_penalty=1,
                central_requirement_coverage=96,
            ),
            evidence=RankingEvidence(
                strong_matches=["Python", "FastAPI", "PostgreSQL", "AWS", "5+ years backend experience"],
                partial_matches=[],
                missing_requirements=[],
                dealbreakers=[],
                central_requirement_coverage=96,
                central_requirements=[
                    {"requirement": "Python", "status": "met", "evidence": "Profile lists production Python APIs."},
                    {"requirement": "FastAPI", "status": "met", "evidence": "Profile lists maintained FastAPI services."},
                ],
            ),
            reasoning_summary=(
                "Strong synthetic match for Acme Cloud Senior Backend Engineer: Python, FastAPI, "
                "PostgreSQL, AWS and 7 years backend experience all match central requirements."
            ),
            recommended_application_angle="Emphasize production Python APIs, FastAPI services, PostgreSQL and AWS.",
            cv_keywords_to_emphasize=["Python", "FastAPI", "PostgreSQL", "AWS", "API design"],
            cv_keywords_to_avoid_overclaiming=[],
            ranking_version=str(kwargs["ranking_version"]),
        )
        db.save_job_ranking(int(row["id"]), ranking)
        saved += 1
    return {"processed": len(jobs), "saved": saved, "failed": len(jobs) - saved}


def _fake_build_application_kit_with_nvidia(job: Any, ranking: Any | None = None, **kwargs: Any) -> dict[str, str]:
    return {
        "recruiter_message": (
            "Hi Acme Cloud team, my Python/FastAPI backend work maps closely to this Senior Backend Engineer role. "
            "I would be glad to share my CV."
        ),
        "cover_letter": (
            "Dear Acme Cloud team,\n\n"
            "I am interested in the Senior Backend Engineer role. My experience building Python, FastAPI, "
            "PostgreSQL and AWS-backed SaaS systems matches the role's core requirements.\n\n"
            "Best regards,\nIgnacio Rodriguez"
        ),
        "ats_cv_text": synthetic_profile()["base_cv_text"]
        + (
            "\n\nSelected Fit\n"
            "Python FastAPI PostgreSQL AWS API design for Acme Cloud Senior Backend Engineer.\n"
            "Built backend services with clear API contracts, database migrations, observability, "
            "and production support practices. Partnered with product and platform teams to deliver "
            "reliable SaaS features while keeping implementation details grounded in existing experience."
        ),
        "autofill_notes": "Use the generated ATS CV. Highlight Python, FastAPI, PostgreSQL, AWS and API design.",
    }


def _ranking_row_to_output(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_score": int(row["final_score"]),
        "decision": row["decision"],
        "confidence": float(row["confidence"] or 0),
        "scores": _loads_json(row.get("scores_json"), {}),
        "evidence": _loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": _loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": _loads_json(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
        "ranking_version": row.get("ranking_version") or NVIDIA_RANKING_VERSION,
    }


def _run_live_judges(
    *,
    live_judge: bool,
    judge_artifacts: list[str],
    case: dict[str, Any],
    outputs: dict[str, Any],
    judge_model: str,
    secondary_judge_model: str,
) -> dict[str, Any]:
    if not live_judge:
        return {}
    results = {}
    for artifact in judge_artifacts:
        if artifact not in outputs:
            raise ValueError(f"Unsupported judge artifact: {artifact}")
        payload = build_llm_judge_payload(case, outputs[artifact], artifact)
        results[artifact] = judge_with_configured_providers(
            payload,
            provider="nvidia",
            model=judge_model,
            secondary_provider="nvidia",
            secondary_model=secondary_judge_model,
        )
    return results


def _eval_to_dict(result: Any) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "score": result.score,
        "issues": result.issues,
        "metrics": result.metrics,
    }


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _require_status(actual: int, expected: int, label: str, body: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} returned HTTP {actual}, expected {expected}: {body}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Job Orchestrator smoke e2e flow.")
    parser.add_argument("--db-path", type=Path, help="Optional SQLite path. Defaults to a temporary DB.")
    parser.add_argument("--live-llm", action="store_true", help="Use real NVIDIA ranking/materials calls.")
    parser.add_argument("--live-judge", action="store_true", help="Run real NVIDIA judge cross-checks.")
    parser.add_argument("--ranking-model", help="NVIDIA ranking model for --live-llm.")
    parser.add_argument("--materials-model", help="NVIDIA materials model for --live-llm.")
    parser.add_argument("--judge-model", default=DEFAULT_PRIMARY_JUDGE_MODEL)
    parser.add_argument("--judge-model-secondary", default=DEFAULT_SECONDARY_JUDGE_MODEL)
    parser.add_argument(
        "--judge-artifacts",
        default="ranking,application_materials,ats_cv",
        help="Comma-separated artifacts for --live-judge.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_smoke_e2e(
            db_path=args.db_path,
            live_llm=args.live_llm,
            live_judge=args.live_judge,
            judge_artifacts=[item.strip() for item in args.judge_artifacts.split(",") if item.strip()],
            ranking_model=args.ranking_model,
            materials_model=args.materials_model,
            judge_model=args.judge_model,
            secondary_judge_model=args.judge_model_secondary,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should return a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
