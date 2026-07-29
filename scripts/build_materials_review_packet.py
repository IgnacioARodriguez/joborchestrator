from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_ARTIFACT_ROOT = Path("data/materials_live_probe")
DEFAULT_OUTPUT = Path("docs/MATERIALS_V3_GENERATED_REVIEW_PACKET.md")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized materials probe review packet.")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case", action="append", dest="cases", help="Case id to include. Repeat for multiple cases.")
    parser.add_argument("--include-all", action="store_true", help="Include every completed probe JSON under artifact root.")
    args = parser.parse_args()

    records = load_records(args.artifact_root, include_cases=args.cases, include_all=args.include_all)
    if not records:
        raise SystemExit("No matching materials probe artifacts found.")
    packet = render_packet(records, args.artifact_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(packet, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "records": len(records)}, indent=2))
    return 0


def load_records(root: Path, *, include_cases: list[str] | None, include_all: bool) -> list[dict[str, Any]]:
    selected = set(include_cases or [])
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        for item in _records_from_payload(payload, path):
            case_id = str(item.get("case") or "")
            if include_all or not selected or case_id in selected:
                records.append(item)
    return sorted(_dedupe_records(records), key=lambda item: (str(item.get("case") or ""), str(item.get("artifact") or "")))


def _records_from_payload(payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if isinstance(payload.get("results"), list):
        return [_summary_record(item, path) for item in payload["results"] if isinstance(item, dict)]
    return [_artifact_record(payload, path)]


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    by_case: dict[str, dict[str, Any]] = {}
    for record in records:
        key = (str(record.get("case") or ""), str(record.get("artifact") or ""))
        by_key[key] = _preferred_record(by_key.get(key), record)
    for record in by_key.values():
        case = str(record.get("case") or "")
        if case:
            by_case[case] = _preferred_record(by_case.get(case), record)
    return list(by_case.values())


def _preferred_record(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_timestamp = _artifact_timestamp(current)
    candidate_timestamp = _artifact_timestamp(candidate)
    if candidate_timestamp != current_timestamp:
        return candidate if candidate_timestamp > current_timestamp else current
    return candidate if _record_completeness(candidate) > _record_completeness(current) else current


def _artifact_timestamp(record: dict[str, Any]) -> str:
    artifact = Path(str(record.get("artifact") or ""))
    match = re.match(r"^(\d{8}_\d{6})_", artifact.name)
    if match:
        return match.group(1)
    return ""


def _record_completeness(record: dict[str, Any]) -> int:
    score = 0
    score += 3 if record.get("cv_text") else 0
    score += 2 if record.get("semantic_eval") else 0
    score += 1 if record.get("job") else 0
    score += 1 if record.get("cv_metadata") else 0
    score += 1 if record.get("kit_metadata") else 0
    return score


def _artifact_record(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    cv = payload.get("cv") if isinstance(payload.get("cv"), dict) else {}
    kit = payload.get("kit") if isinstance(payload.get("kit"), dict) else {}
    return {
        "case": payload.get("case") or path.stem,
        "artifact": str(path),
        "job": payload.get("job") if isinstance(payload.get("job"), dict) else {},
        "ranking": payload.get("ranking") if isinstance(payload.get("ranking"), dict) else {},
        "cv_status": payload.get("cv_status") or ("completed" if cv else "failed" if payload.get("cv_error") else ""),
        "kit_status": payload.get("kit_status") or ("completed" if kit else "failed" if payload.get("kit_error") else ""),
        "cv_error": payload.get("cv_error"),
        "kit_error": payload.get("kit_error"),
        "cv_metadata": cv.get("_generation_metadata") if isinstance(cv.get("_generation_metadata"), dict) else {},
        "kit_metadata": kit.get("_generation_metadata") if isinstance(kit.get("_generation_metadata"), dict) else {},
        "semantic_eval": payload.get("semantic_eval") if isinstance(payload.get("semantic_eval"), dict) else None,
        "cv_text": str(cv.get("ats_cv_text") or ""),
        "recruiter_message": str(kit.get("recruiter_message") or ""),
        "cover_letter": str(kit.get("cover_letter") or ""),
    }


def _summary_record(item: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    artifact_path = Path(str(item.get("artifact") or ""))
    payload = _load_json(artifact_path) if artifact_path.exists() else {}
    record = _artifact_record(payload, artifact_path) if isinstance(payload, dict) and payload else {}
    record.update(
        {
            "case": item.get("case") or record.get("case"),
            "artifact": str(item.get("artifact") or record.get("artifact") or summary_path),
            "cv_status": item.get("cv_status") or item.get("status") or record.get("cv_status"),
            "kit_status": item.get("kit_status") or item.get("status") or record.get("kit_status"),
            "cv_error": item.get("cv_error") or record.get("cv_error"),
            "kit_error": item.get("kit_error") or record.get("kit_error"),
            "cv_metadata": item.get("cv_metadata") or (item.get("metadata") or {}).get("cv") or record.get("cv_metadata", {}),
            "kit_metadata": item.get("kit_metadata") or (item.get("metadata") or {}).get("kit") or record.get("kit_metadata", {}),
            "semantic_eval": item.get("semantic_eval") or record.get("semantic_eval"),
        }
    )
    return record


def render_packet(records: list[dict[str, Any]], artifact_root: Path) -> str:
    lines = [
        "# Generated Materials Review Packet",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"Artifact root: `{artifact_root}`",
        "",
        "This packet is sanitized. It reports metrics, statuses, attempts, and issue codes only; it does not include generated CV or cover-letter text.",
        "",
        "## Summary",
        "",
        f"- Records: {len(records)}",
        f"- Completed CVs: {sum(1 for item in records if item.get('cv_status') == 'completed')}",
        f"- Failed CVs: {sum(1 for item in records if item.get('cv_status') == 'failed')}",
        f"- Completed kits: {sum(1 for item in records if item.get('kit_status') == 'completed')}",
        f"- Failed kits: {sum(1 for item in records if item.get('kit_status') == 'failed')}",
        "",
        "## Cases",
        "",
        "| Case | Job | Artifact | Status | Attempts | Semantic | CV Size | Issues / Errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in records:
        lines.append(_case_row(item))
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Use the artifact paths locally when a reviewer needs full generated text.",
            "- Keep generated artifacts out of git unless they are intentionally redacted fixtures.",
            "- Treat automatic scores as evidence, not as a replacement for qualitative review.",
            "",
        ]
    )
    return "\n".join(lines)


def _case_row(item: dict[str, Any]) -> str:
    cv_text = str(item.get("cv_text") or "")
    cv_lines = len([line for line in cv_text.splitlines() if line.strip()])
    cv_chars = len(cv_text)
    job = item.get("job") if isinstance(item.get("job"), dict) else {}
    semantic = item.get("semantic_eval") if isinstance(item.get("semantic_eval"), dict) else {}
    materials = semantic.get("materials") if isinstance(semantic.get("materials"), dict) else {}
    ats = semantic.get("ats_cv") if isinstance(semantic.get("ats_cv"), dict) else {}
    cv_meta = item.get("cv_metadata") if isinstance(item.get("cv_metadata"), dict) else {}
    kit_meta = item.get("kit_metadata") if isinstance(item.get("kit_metadata"), dict) else {}
    issues = _compact_issues(materials, ats, item)
    return (
        f"| `{_escape(item.get('case'))}` "
        f"| {_escape(_job_label(job))} "
        f"| `{_escape(_display_path(item.get('artifact')))}` "
        f"| CV: {_escape(item.get('cv_status'))}<br>Kit: {_escape(item.get('kit_status'))} "
        f"| CV: {_escape(cv_meta.get('validation_attempts'))}<br>Kit: {_escape(kit_meta.get('validation_attempts'))} "
        f"| Materials: {_score_label(materials)}<br>ATS: {_score_label(ats)} "
        f"| {cv_chars} chars<br>{cv_lines} lines "
        f"| {_escape(issues)} |"
    )


def _compact_issues(materials: dict[str, Any], ats: dict[str, Any], item: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, payload in [("materials", materials), ("ats", ats)]:
        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        if issues:
            issue_labels = [_truncate(str(issue), 90) for issue in issues[:3]]
            parts.append(f"{label}: {', '.join(issue_labels)}")
    for label in ["cv_error", "kit_error"]:
        if item.get(label):
            parts.append(f"{label}: {_truncate(str(item[label]), 180)}")
    if not parts:
        return "none"
    return _truncate(" | ".join(parts), 320)


def _score_label(payload: dict[str, Any]) -> str:
    if not payload:
        return "n/a"
    return f"{'pass' if payload.get('passed') else 'fail'} {payload.get('score')}"


def _job_label(job: dict[str, Any]) -> str:
    title = str(job.get("title") or "Unknown job")
    company = str(job.get("company") or "Unknown company")
    return f"{title} @ {company}"


def _escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _display_path(value: Any) -> str:
    return Path(str(value if value is not None else "")).as_posix()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
