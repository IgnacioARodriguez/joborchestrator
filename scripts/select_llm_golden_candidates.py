from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from joborchestrator.env import load_local_env  # noqa: E402
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION  # noqa: E402
from joborchestrator.storage import db_connection  # noqa: E402

DEFAULT_OUTPUT = Path("logs/llm_golden_candidate_review_packet.json")
SAFE_DRAFT_FIXTURE_ROOT = Path("logs/llm_eval_fixture_drafts")
DEFAULT_BUCKET_QUOTAS = {
    "strong_fit": 8,
    "borderline": 8,
    "negative_or_dealbreaker": 10,
    "low_context": 6,
    "materials_ready": 8,
}
DEALBREAKER_TERMS = [
    "relocation",
    "relocate",
    "onsite",
    "on-site",
    "commission",
    "no base salary",
    "visa",
    "work authorization",
    "security clearance",
    "native english",
    "german",
    "rust",
    "kernel",
    "driver",
]


def main() -> int:
    args = parse_args()
    load_local_env()
    rows = fetch_rows(args.ranking_version, args.limit)
    packet = build_review_packet(
        rows,
        ranking_version=args.ranking_version,
        target_total=args.target_total,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "candidate_count": len(packet["candidates"])}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select review candidates for the LLM trust golden set.")
    parser.add_argument("--ranking-version", default=NVIDIA_RANKING_VERSION)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--target-total", type=int, default=40)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def fetch_rows(ranking_version: str, limit: int) -> list[dict[str, Any]]:
    conn = db_connection.connect(":memory:")
    try:
        rows = conn.execute(
            """SELECT jp.id AS job_id, jp.source, jp.company, jp.title, jp.location, jp.status,
                      jp.description_text, jp.data_quality_flags, jp.parse_confidence,
                      jp.recruiter_message, jp.cover_letter, jp.ats_cv_text, jp.autofill_notes,
                      jr.id AS ranking_id, jr.final_score, jr.decision, jr.confidence,
                      jr.evidence_json, jr.scores_json, jr.updated_at AS ranking_updated_at
               FROM job_postings jp
               LEFT JOIN job_rankings jr
                 ON jr.job_id = jp.id AND jr.ranking_version = ?
               WHERE jp.is_active = 1
               ORDER BY
                 CASE WHEN jr.id IS NULL THEN 1 ELSE 0 END ASC,
                 jp.last_seen_at DESC,
                 jp.id DESC
               LIMIT ?""",
            (ranking_version, int(limit)),
        ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]
    finally:
        conn.close()


def build_review_packet(
    rows: list[dict[str, Any]],
    *,
    ranking_version: str,
    target_total: int = 40,
    generated_at: str,
) -> dict[str, Any]:
    candidates = select_candidates(rows, target_total=target_total)
    bucket_counts = Counter(bucket for candidate in candidates for bucket in candidate["buckets"])
    return {
        "generated_at": generated_at,
        "ranking_version": ranking_version,
        "review_status": "needs_human_review",
        "protected_fixture_policy": (
            "This packet is only a review queue. Do not write reviewed cases into evals/fixtures/ "
            "without explicit human approval."
        ),
        "target_total": target_total,
        "candidate_count": len(candidates),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "recommended_review_flow": [
            "Open this packet and pick cases that are genuinely representative or risky.",
            "Review raw job text, current ranking/material outputs, and expected behavior.",
            "Use the safe capture commands only for draft fixtures under logs/.",
            "After human approval, promote reviewed cases into the protected golden fixture location.",
        ],
        "candidates": candidates,
    }


def select_candidates(rows: list[dict[str, Any]], *, target_total: int = 40) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for bucket, quota in DEFAULT_BUCKET_QUOTAS.items():
        for row in sorted(rows, key=lambda item: bucket_priority(item, bucket), reverse=True):
            job_id = int(row["job_id"])
            if job_id in seen or bucket not in classify_buckets(row):
                continue
            selected.append(candidate_record(row))
            seen.add(job_id)
            if sum(1 for candidate in selected if bucket in candidate["buckets"]) >= quota:
                break
    if len(selected) < target_total:
        for row in sorted(rows, key=general_priority, reverse=True):
            job_id = int(row["job_id"])
            if job_id in seen:
                continue
            selected.append(candidate_record(row))
            seen.add(job_id)
            if len(selected) >= target_total:
                break
    return selected[:target_total]


def candidate_record(row: dict[str, Any]) -> dict[str, Any]:
    buckets = classify_buckets(row)
    recommended_surfaces = recommended_surfaces_for(row)
    label = label_for(row, buckets)
    return {
        "job_id": int(row["job_id"]),
        "case_label": label,
        "review_status": "needs_human_review",
        "buckets": buckets,
        "recommended_surfaces": recommended_surfaces,
        "source": row.get("source"),
        "company": row.get("company"),
        "title": row.get("title"),
        "location": row.get("location"),
        "ranking": {
            "has_ranking": bool(row.get("ranking_id")),
            "decision": row.get("decision"),
            "final_score": _int_or_none(row.get("final_score")),
            "confidence": _float_or_none(row.get("confidence")),
        },
        "signals": {
            "description_chars": len(str(row.get("description_text") or "")),
            "parse_confidence": _float_or_none(row.get("parse_confidence")),
            "data_quality_flags": _loads_json(row.get("data_quality_flags"), []),
            "dealbreaker_terms": dealbreaker_terms(row),
            "has_materials": has_materials(row),
        },
        "description_preview": compact_text(row.get("description_text"), limit=420),
        "review_focus": review_focus(row),
        "safe_capture_commands": safe_capture_commands(row, recommended_surfaces, label),
    }


def classify_buckets(row: dict[str, Any]) -> list[str]:
    buckets: list[str] = []
    score = _int_or_none(row.get("final_score"))
    decision = str(row.get("decision") or "")
    if decision in {"APPLY_NOW", "APPLY_WITH_TAILORED_CV"} or (score is not None and score >= 70):
        buckets.append("strong_fit")
    if decision == "MAYBE" or (score is not None and 45 <= score <= 69):
        buckets.append("borderline")
    if decision in {"SKIP", "AVOID"} or (score is not None and score < 45) or dealbreaker_terms(row):
        buckets.append("negative_or_dealbreaker")
    if is_low_context(row):
        buckets.append("low_context")
    if has_materials(row):
        buckets.append("materials_ready")
    if not buckets:
        buckets.append("general")
    return buckets


def recommended_surfaces_for(row: dict[str, Any]) -> list[str]:
    surfaces = ["ranking"] if row.get("ranking_id") else []
    if has_materials(row):
        surfaces.extend(["application_materials", "ats_cv"])
    if not surfaces:
        surfaces.append("ranking")
    return surfaces


def bucket_priority(row: dict[str, Any], bucket: str) -> tuple:
    score = _int_or_none(row.get("final_score")) or 0
    description_len = len(str(row.get("description_text") or ""))
    dealbreakers = len(dealbreaker_terms(row))
    if bucket == "strong_fit":
        return (score, description_len)
    if bucket == "borderline":
        return (-abs(score - 58), description_len)
    if bucket == "negative_or_dealbreaker":
        return (dealbreakers, 100 - score, description_len)
    if bucket == "low_context":
        return (1 if is_low_context(row) else 0, -description_len)
    if bucket == "materials_ready":
        return (1 if has_materials(row) else 0, score)
    return general_priority(row)


def general_priority(row: dict[str, Any]) -> tuple:
    return (len(classify_buckets(row)), _int_or_none(row.get("final_score")) or 0)


def is_low_context(row: dict[str, Any]) -> bool:
    description_len = len(str(row.get("description_text") or ""))
    parse_confidence = _float_or_none(row.get("parse_confidence"))
    flags = _loads_json(row.get("data_quality_flags"), [])
    return description_len < 700 or (parse_confidence is not None and parse_confidence < 0.65) or bool(flags)


def has_materials(row: dict[str, Any]) -> bool:
    return any(str(row.get(field) or "").strip() for field in ["recruiter_message", "cover_letter", "ats_cv_text", "autofill_notes"])


def dealbreaker_terms(row: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(row.get(field) or "")
        for field in ["title", "location", "description_text", "evidence_json"]
    ).lower()
    matches = []
    for term in DEALBREAKER_TERMS:
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(pattern, text):
            matches.append(term)
    return matches


def review_focus(row: dict[str, Any]) -> list[str]:
    focus: list[str] = []
    buckets = classify_buckets(row)
    if "strong_fit" in buckets:
        focus.append("Verify APPLY_NOW/APPLY_WITH_TAILORED_CV evidence is backed by the candidate profile.")
    if "borderline" in buckets:
        focus.append("Decide whether the correct behavior is MAYBE or a tailored application.")
    if "negative_or_dealbreaker" in buckets:
        focus.append("Confirm dealbreakers and make sure APPLY_NOW would be blocked.")
    if "low_context" in buckets:
        focus.append("Check whether sparse or noisy job text should require human review.")
    if "materials_ready" in buckets:
        focus.append("Inspect generated materials for specificity, length, and unsupported claims.")
    return focus


def safe_capture_commands(row: dict[str, Any], surfaces: list[str], label: str) -> list[str]:
    commands = []
    for surface in surfaces:
        artifact = "materials" if surface == "application_materials" else surface
        commands.append(
            " ".join(
                [
                    "python",
                    "scripts/capture_llm_eval_fixture.py",
                    f"--job-id {int(row['job_id'])}",
                    f"--artifact {artifact}",
                    f"--label {label}",
                    f"--output-root {SAFE_DRAFT_FIXTURE_ROOT.as_posix()}",
                ]
            )
        )
    return commands


def label_for(row: dict[str, Any], buckets: list[str]) -> str:
    base = buckets[0] if buckets else "general"
    title = str(row.get("title") or "job").lower()
    words = [word for word in re.split(r"[^a-z0-9]+", title) if len(word) >= 3][:3]
    return "-".join([base, *words])[:80]


def compact_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


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
