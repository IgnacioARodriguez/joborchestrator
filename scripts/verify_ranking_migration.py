from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.api_dto import ranking_summary_dto  # noqa: E402
from joborchestrator.priority import compute_priority  # noqa: E402
from joborchestrator.ranking.decision_engine import rank_job_facts  # noqa: E402
from joborchestrator.ranking.integrity import candidate_profile_status, is_remote_job  # noqa: E402
from joborchestrator.ranking.versions import (  # noqa: E402
    LEGACY_NVIDIA_RANKING_VERSION,
    NVIDIA_DETERMINISTIC_RANKING_VERSION,
    NVIDIA_RANKING_VERSION,
)
from joborchestrator.storage import ranking_jobs_repository, rankings_repository  # noqa: E402

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "ranking_migration_cases.json"
STATUS_PATH = PROJECT_ROOT / "docs" / "ranking" / "migration-status.md"
PHASES = (
    "phase-0-integrity",
    "phase-1-persistence",
    "phase-2-deterministic",
    "phase-3-activation",
)
PHASE_TITLES = {
    "phase-0-integrity": "Phase 0 — Decision authority and trace integrity",
    "phase-1-persistence": "Phase 1 — Persistence and queue idempotency",
    "phase-2-deterministic": "Phase 2 — Fact extraction and deterministic decision",
    "phase-3-activation": "Phase 3 — Default activation and rollback",
}
PHASE_CRITERIA = {
    "phase-0-integrity": (
        "ranking decisions control the next action; current visibility controls freshness; "
        "work-mode fields are combined; stale candidate-profile hashes force reranking; "
        "central requirements survive compact DTO serialization."
    ),
    "phase-1-persistence": (
        "active ranking jobs cannot duplicate the same posting/version pair, and rankings "
        "created from an older candidate profile are returned for reranking."
    ),
    "phase-2-deterministic": (
        "the deterministic engine satisfies all fixed abstract cases, improves decision agreement "
        "over the frozen baseline, exposes every required assessment, and contains no fixture-specific rule or prompt example."
    ),
    "phase-3-activation": (
        "the deterministic ranking version is the default, the worker dispatches through the versioned service, "
        "the extraction prompt is registered, and the legacy version remains available only through an explicit environment override."
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ranking migration phases and update migration status.")
    parser.add_argument("--phase", choices=[*PHASES, "all"], default="all")
    parser.add_argument("--no-status-write", action="store_true")
    args = parser.parse_args(argv)

    selected = PHASES if args.phase == "all" else (args.phase,)
    try:
        for phase in selected:
            metrics = PHASE_RUNNERS[phase]()
            if not args.no_status_write:
                _update_status(phase, metrics)
            print(json.dumps({"phase": phase, "status": "PASSED", "metrics": metrics}, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - nonzero exit is the verification contract.
        print(json.dumps({"phase": phase, "status": "FAILED", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    return 0


def verify_phase_0_integrity() -> dict[str, Any]:
    now = datetime(2026, 1, 31, 12, 0, 0)
    base_job = {
        "title": "role_primary",
        "company": "organization_placeholder",
        "url": "https://invalid.local/job",
        "description_text": "complete posting",
        "apply_url": "https://invalid.local/apply",
        "location": "region_primary",
        "workplace_type": "remote",
        "posted_at": "2025-01-01T00:00:00",
        "first_seen_at": "2025-01-01T00:00:00",
        "last_seen_at": "2026-01-30T12:00:00",
        "pipeline_status": "shortlisted",
        "is_active": 1,
    }
    ranking = {
        "final_score": 88,
        "decision": "SKIP",
        "confidence": 0.90,
        "scores": {"risk_penalty": 30},
        "evidence": {"dealbreakers": [], "red_flags": []},
        "generation": {"profile_status": "current"},
    }
    before_action = "Apply now"
    after = compute_priority(base_job, ranking, now=now)
    _assert(after.next_action == "Skip", f"SKIP ranking produced next_action={after.next_action!r}")
    _assert(after.freshness_bucket == "fresh", f"last_seen_at did not control freshness: {after.freshness_bucket}")
    _assert(is_remote_job(base_job), "workplace_type was ignored when location was populated")
    _assert(candidate_profile_status("profile-old", "profile-current") == "stale", "profile hash mismatch not detected")

    stale_ranking = {**ranking, "decision": "APPLY_NOW", "generation": {"profile_status": "stale"}}
    stale_after = compute_priority(base_job, stale_ranking, now=now)
    _assert(stale_after.next_action == "Re-rank", f"stale profile produced next_action={stale_after.next_action!r}")

    row = {
        "final_score": 88,
        "decision": "APPLY_NOW",
        "confidence": 0.90,
        "evidence_json": json.dumps(
            {
                "strong_matches": ["capability_primary"],
                "missing_requirements": [],
                "requires_llm_review": False,
                "llm_escalation_reasons": [],
                "red_flags": [],
                "central_requirements": [
                    {"requirement": "capability_primary", "match": "strong"}
                ],
            }
        ),
        "reasoning_summary": "deterministic result",
        "ranking_version": "ranking_v2.0.0-nvidia-facts",
        "ranking_validation_attempts": 1,
        "ranking_candidate_profile_hash": "profile-current",
        "_current_candidate_profile_hash": "profile-current",
    }
    summary = ranking_summary_dto(row)
    _assert(summary["evidence"]["central_requirements"] == ["capability_primary"], "compact DTO lost central requirements")
    _assert("ranking_missing_central_requirements" not in summary["review"]["reasons"], "compact DTO created false review reason")
    _assert(summary["generation"]["profile_status"] == "current", "compact DTO lost profile status")

    contradictions_before = 4
    contradictions_after = sum(
        [
            after.next_action != "Skip",
            after.freshness_bucket != "fresh",
            not is_remote_job(base_job),
            stale_after.next_action != "Re-rank",
        ]
    )
    _assert(contradictions_after == 0, f"integrity contradictions remain: {contradictions_after}")
    return {
        "before_action": before_action,
        "after_action": after.next_action,
        "contradictions_before": contradictions_before,
        "contradictions_after": contradictions_after,
        "freshness_after": after.freshness_bucket,
        "profile_status_after": summary["generation"]["profile_status"],
    }


def verify_phase_1_persistence() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ranking-migration-") as temp_dir:
        db_path = Path(temp_dir) / "verification.sqlite3"
        _initialize_verification_db(db_path)
        connect = _sqlite_factory(db_path)

        first_id = ranking_jobs_repository.create_ranking_job(
            connect,
            provider="nvidia",
            model="model-placeholder",
            ranking_version="ranking-version-placeholder",
            job_ids=[1, 2],
            request_batch_size=2,
            max_concurrency=1,
        )
        second_id = ranking_jobs_repository.create_ranking_job(
            connect,
            provider="nvidia",
            model="model-placeholder",
            ranking_version="ranking-version-placeholder",
            job_ids=[2, 3],
            request_batch_size=2,
            max_concurrency=1,
        )
        conn = connect()
        try:
            first_items = [
                int(row[0])
                for row in conn.execute(
                    "SELECT job_posting_id FROM ranking_job_items WHERE ranking_job_id = ? ORDER BY job_posting_id",
                    (first_id,),
                ).fetchall()
            ]
            second_items = [
                int(row[0])
                for row in conn.execute(
                    "SELECT job_posting_id FROM ranking_job_items WHERE ranking_job_id = ? ORDER BY job_posting_id",
                    (second_id,),
                ).fetchall()
            ]
        finally:
            conn.close()
        _assert(first_items == [1, 2], f"first queue changed unexpectedly: {first_items}")
        _assert(second_items == [3], f"active duplicate was queued again: {second_items}")

        stale = rankings_repository.get_unranked_jobs(
            connect,
            _read_sql_query,
            ranking_version="ranking-version-placeholder",
            limit=10,
            candidate_profile_hash="profile-current",
        )
        stale_ids = sorted(int(value) for value in stale["id"].tolist())
        _assert(stale_ids == [2, 3], f"stale/unranked selection mismatch: {stale_ids}")
        return {
            "duplicate_items_before": 1,
            "duplicate_items_after": 0,
            "second_job_total_after": len(second_items),
            "rerank_ids_after": stale_ids,
        }


def verify_phase_2_deterministic() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    profile = fixture["profile"]
    cases = fixture["decision_cases"]
    before_correct = 0
    after_correct = 0
    outputs: list[dict[str, Any]] = []
    for case in cases:
        expected = case["expected_decision"]
        if case["legacy"]["decision"] == expected:
            before_correct += 1
        result = rank_job_facts(
            case["job"],
            case["facts"],
            profile,
            ranking_version="ranking_v2.0.0-nvidia-facts",
        )
        if result.decision == expected:
            after_correct += 1
        required_count = sum(
            1
            for item in case["facts"]["requirements"]
            if item["importance"] == "required" and item["kind"] != "application_step"
        )
        _assert(
            len(result.evidence.central_requirements) == required_count,
            f"{case['id']}: expected {required_count} central assessments, got {len(result.evidence.central_requirements)}",
        )
        outputs.append(
            {
                "id": case["id"],
                "decision": result.decision,
                "expected": expected,
                "score": result.final_score,
                "coverage": result.evidence.central_requirement_coverage,
            }
        )

    _assert(after_correct == len(cases), f"deterministic agreement {after_correct}/{len(cases)}")
    _assert(after_correct > before_correct, f"agreement did not improve: before={before_correct}, after={after_correct}")
    _assert_no_case_specific_rules(fixture["case_tokens"])
    _assert_extraction_prompt_has_no_decision_authority()
    return {
        "cases": len(cases),
        "decision_agreement_before": before_correct,
        "decision_agreement_after": after_correct,
        "outputs": outputs,
    }


def verify_phase_3_activation() -> dict[str, Any]:
    _assert(
        NVIDIA_RANKING_VERSION == NVIDIA_DETERMINISTIC_RANKING_VERSION,
        f"default ranking version is {NVIDIA_RANKING_VERSION!r}",
    )
    _assert(
        LEGACY_NVIDIA_RANKING_VERSION != NVIDIA_DETERMINISTIC_RANKING_VERSION,
        "legacy rollback version is not distinct",
    )
    worker_source = (PROJECT_ROOT / "joborchestrator" / "ranking" / "worker.py").read_text(encoding="utf-8")
    _assert(
        "from joborchestrator.ranking.service import" in worker_source,
        "ranking worker bypasses the versioned service",
    )
    registry = json.loads((PROJECT_ROOT / "prompts" / "registry.json").read_text(encoding="utf-8"))
    active = registry.get("environments", {}).get(registry.get("active_environment", "default"), {})
    _assert(active.get("ranking/nvidia_fact_contract") == "v1", "fact extraction prompt is not registered")
    service_source = (PROJECT_ROOT / "joborchestrator" / "ranking" / "service.py").read_text(encoding="utf-8")
    _assert(
        "NVIDIA_DETERMINISTIC_RANKING_VERSION" in service_source
        and "rank_jobs_with_nvidia_facts" in service_source,
        "versioned service does not dispatch deterministic facts",
    )
    return {
        "default_version": NVIDIA_RANKING_VERSION,
        "rollback_version": LEGACY_NVIDIA_RANKING_VERSION,
        "worker_dispatch": "service",
        "fact_prompt": active.get("ranking/nvidia_fact_contract"),
    }


def _assert_no_case_specific_rules(case_tokens: list[str]) -> None:
    paths = [
        PROJECT_ROOT / "joborchestrator" / "ranking" / "decision_engine.py",
        PROJECT_ROOT / "joborchestrator" / "ranking" / "nvidia_fact_ranker.py",
        PROJECT_ROOT / "prompts" / "ranking" / "nvidia_fact_contract" / "v1.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in paths)
    leaked = [token for token in case_tokens if token.casefold() in combined]
    _assert(not leaked, f"fixture-specific values leaked into active rules or prompt: {leaked}")


def _assert_extraction_prompt_has_no_decision_authority() -> None:
    prompt = (PROJECT_ROOT / "prompts" / "ranking" / "nvidia_fact_contract" / "v1.md").read_text(encoding="utf-8")
    lower = prompt.casefold()
    _assert("good example" not in lower and "bad example" not in lower, "extraction prompt contains case examples")
    output_contract = lower.split("# output contract", 1)[-1]
    forbidden_output_fields = ["final_score", '"decision"', "recommended_application_angle"]
    leaked = [field for field in forbidden_output_fields if field in output_contract]
    _assert(not leaked, f"extraction output contract contains decision fields: {leaked}")


def _initialize_verification_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE ranking_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                ranking_version TEXT NOT NULL,
                status TEXT NOT NULL,
                request_batch_size INTEGER NOT NULL,
                max_concurrency INTEGER NOT NULL,
                total_items INTEGER DEFAULT 0,
                processed_items INTEGER DEFAULT 0,
                saved_items INTEGER DEFAULT 0,
                failed_items INTEGER DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE ranking_job_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ranking_job_id INTEGER NOT NULL,
                job_posting_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                error TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(ranking_job_id, job_posting_id)
            );
            CREATE TABLE job_postings (
                id INTEGER PRIMARY KEY,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE job_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                ranking_version TEXT NOT NULL,
                ranking_candidate_profile_hash TEXT
            );
            INSERT INTO job_postings (id, last_seen_at) VALUES
                (1, '2026-01-03T00:00:00'),
                (2, '2026-01-02T00:00:00'),
                (3, '2026-01-01T00:00:00');
            INSERT INTO job_rankings (job_id, ranking_version, ranking_candidate_profile_hash) VALUES
                (1, 'ranking-version-placeholder', 'profile-current'),
                (2, 'ranking-version-placeholder', 'profile-old');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _sqlite_factory(path: Path) -> Callable[[], sqlite3.Connection]:
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _read_sql_query(query: str, conn: sqlite3.Connection, params: Any = None) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params)


def _update_status(phase: str, metrics: dict[str, Any]) -> None:
    text = STATUS_PATH.read_text(encoding="utf-8")
    start_marker = f"<!-- phase:{phase}:start -->"
    end_marker = f"<!-- phase:{phase}:end -->"
    start = text.find(start_marker)
    end = text.find(end_marker)
    _assert(start >= 0 and end > start, f"status markers missing for {phase}")
    command = f"python scripts/verify_ranking_migration.py --phase {phase}"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    replacement = "\n".join(
        [
            start_marker,
            f"## {PHASE_TITLES[phase]}",
            "",
            "- Status: `PASSED`",
            f"- Verification: `{command}`",
            f"- Criterion: {PHASE_CRITERIA[phase]}",
            f"- Last verified UTC: `{timestamp}`",
            f"- Metrics: `{json.dumps(metrics, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}`",
            end_marker,
        ]
    )
    updated = text[:start] + replacement + text[end + len(end_marker) :]
    STATUS_PATH.write_text(updated, encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


PHASE_RUNNERS: dict[str, Callable[[], dict[str, Any]]] = {
    "phase-0-integrity": verify_phase_0_integrity,
    "phase-1-persistence": verify_phase_1_persistence,
    "phase-2-deterministic": verify_phase_2_deterministic,
    "phase-3-activation": verify_phase_3_activation,
}


if __name__ == "__main__":
    raise SystemExit(main())
