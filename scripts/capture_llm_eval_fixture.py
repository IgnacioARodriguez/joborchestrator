from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.evals.semantic import build_auto_eval_case  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import persistence as db  # noqa: E402

DEFAULT_OUTPUT_ROOT = Path("evals/fixtures/raw")
SURFACE_ALIASES = {
    "materials": "application_materials",
    "application_materials": "application_materials",
    "ranking": "ranking",
    "ats_cv": "ats_cv",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a raw LLM eval fixture from a real DB job.")
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--artifact", choices=sorted(SURFACE_ALIASES), required=True)
    parser.add_argument("--label", required=True, help="Human-readable issue/case label, e.g. ats-cv-internal-notes.")
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--critical", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    fixture = build_capture_fixture(
        job_id=args.job_id,
        artifact=args.artifact,
        label=args.label,
        ranking_version=args.ranking_version,
        critical=args.critical,
    )
    path = write_fixture(fixture, args.output_root, overwrite=args.overwrite)
    print(json.dumps({"fixture_path": str(path), "case_id": fixture["case_id"]}, ensure_ascii=False, indent=2))
    return 0


def build_capture_fixture(
    *,
    job_id: int,
    artifact: str,
    label: str,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    critical: bool = False,
) -> dict[str, Any]:
    surface = _surface_from_artifact(artifact)
    job = db.get_job_posting(int(job_id))
    if not job:
        raise SystemExit(f"Job id {job_id} was not found.")
    profile = db.get_candidate_profile_payload() or {}
    auto_case = build_auto_eval_case(job, profile)
    case_id = _case_id(job, label)
    output = _current_output(surface, job, ranking_version)
    return {
        "case_id": case_id,
        "surface": surface,
        "critical": critical,
        "review_status": "needs_human_review",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "job_id": int(job_id),
            "artifact": artifact,
            "ranking_version": ranking_version if surface == "ranking" else None,
            "label": label,
        },
        "raw_input": _raw_input(job),
        "candidate_profile_snapshot": {
            "source": "db.current_candidate_profile",
            "profile": profile,
        },
        "current_output": output,
        "expected": _expected_proposal(surface, auto_case),
        "human_review_instructions": (
            "Review and edit `expected` before treating this fixture as frozen. "
            "Do not promote fixtures with review_status=needs_human_review into gatekeeping evals."
        ),
    }


def write_fixture(fixture: dict[str, Any], output_root: Path, *, overwrite: bool = False) -> Path:
    surface = str(fixture["surface"])
    target_dir = output_root / surface
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{fixture['case_id']}.json"
    if path.exists() and not overwrite:
        raise SystemExit(f"Fixture already exists: {path}. Pass --overwrite to replace it.")
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _current_output(surface: str, job: dict[str, Any], ranking_version: str) -> dict[str, Any]:
    if surface == "application_materials":
        return {
            "recruiter_message": job.get("recruiter_message") or "",
            "cover_letter": job.get("cover_letter") or "",
            "ats_cv_text": job.get("ats_cv_text") or "",
            "autofill_notes": job.get("autofill_notes") or "",
        }
    if surface == "ats_cv":
        return {"ats_cv_text": job.get("ats_cv_text") or ""}
    rows = db.get_rankings_for_job_ids(ranking_version, [int(job["id"])])
    if rows.empty:
        return {}
    row = rows.iloc[0].to_dict()
    return {
        "final_score": _int_or_none(row.get("final_score")),
        "decision": row.get("decision"),
        "confidence": _float_or_none(row.get("confidence")),
        "scores": _loads_json(row.get("scores_json"), {}),
        "evidence": _loads_json(row.get("evidence_json"), {}),
        "reasoning_summary": row.get("reasoning_summary") or "",
        "recommended_application_angle": row.get("recommended_application_angle") or "",
        "cv_keywords_to_emphasize": _loads_json(row.get("cv_keywords_to_emphasize_json"), []),
        "cv_keywords_to_avoid_overclaiming": _loads_json(row.get("cv_keywords_to_avoid_overclaiming_json"), []),
    }


def _expected_proposal(surface: str, auto_case: dict[str, Any]) -> dict[str, Any]:
    if surface == "ranking":
        return dict(auto_case.get("ranking_expectations") or {})
    if surface == "ats_cv":
        return dict(auto_case.get("ats_cv_expectations") or {})
    return dict(auto_case.get("materials_expectations") or {})


def _raw_input(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_html_or_text": job.get("description_text") or job.get("description") or "",
        "source": job.get("source"),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "url": job.get("url"),
        "apply_url": job.get("apply_url"),
        "easy_apply": _bool_or_none(job.get("easy_apply")),
        "raw_payload": _loads_json(job.get("raw_payload_json"), job.get("raw_payload") or {}),
    }


def _case_id(job: dict[str, Any], label: str) -> str:
    parts = [
        str(job.get("source") or "job"),
        str(job.get("company") or ""),
        str(job.get("title") or ""),
        label,
    ]
    slug = "-".join(_slugify(part) for part in parts if str(part or "").strip())
    return re.sub(r"-{2,}", "-", slug).strip("-")[:120]


def _surface_from_artifact(artifact: str) -> str:
    return SURFACE_ALIASES[artifact]


def _slugify(value: str) -> str:
    lowered = value.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _bool_or_none(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
