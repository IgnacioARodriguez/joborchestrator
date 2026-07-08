from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from joborchestrator.paths import DATA_DIR
from joborchestrator.ranking.llm_ranker import (
    DEFAULT_LLM_MODEL,
    LLMRankingError,
    _extract_response_text,
    _ranking_from_payload,
    build_ranking_response_body,
    llm_ranking_version,
)
from joborchestrator.ranking.profile import load_candidate_profile
from joborchestrator.ranking.ranking_rules import OPENAI_BATCH_INSTRUCTIONS
from joborchestrator.storage import persistence as db

OPENAI_BATCH_DIR = DATA_DIR / "openai_batches"
OPENAI_BATCH_ENDPOINT = "/v1/responses"


class OpenAIBatchError(RuntimeError):
    pass


def create_ranking_batch_jsonl(
    jobs: pd.DataFrame,
    *,
    model: str = DEFAULT_LLM_MODEL,
    output_dir: Path = OPENAI_BATCH_DIR,
    max_description_chars: int = 7000,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"ranking_batch_{timestamp}.jsonl"
    profile = load_candidate_profile()
    profile_payload = asdict(profile)

    with path.open("w", encoding="utf-8") as file:
        for row in jobs.to_dict("records"):
            job_id = int(row.get("id") or row.get("job_id"))
            payload = {
                "profile": profile_payload,
                "job": _compact_job(row, max_description_chars=max_description_chars),
                "ranking_goal": OPENAI_BATCH_INSTRUCTIONS["ranking_goal"],
                "instructions": OPENAI_BATCH_INSTRUCTIONS,
            }
            line = {
                "custom_id": f"job_ranking_{job_id}",
                "method": "POST",
                "url": OPENAI_BATCH_ENDPOINT,
                "body": build_ranking_response_body(payload, model),
            }
            file.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def submit_ranking_batch(
    jsonl_path: Path,
    *,
    api_key: str | None = None,
    completion_window: str = "24h",
    timeout: float = 60.0,
) -> dict[str, Any]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise OpenAIBatchError("OPENAI_API_KEY is required to submit an OpenAI Batch job.")

    headers = {"Authorization": f"Bearer {key}"}
    try:
        with jsonl_path.open("rb") as file:
            upload = httpx.post(
                "https://api.openai.com/v1/files",
                headers=headers,
                files={"file": (jsonl_path.name, file, "application/jsonl")},
                data={"purpose": "batch"},
                timeout=timeout,
            )
        upload.raise_for_status()
        input_file_id = upload.json()["id"]
        batch = httpx.post(
            "https://api.openai.com/v1/batches",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "input_file_id": input_file_id,
                "endpoint": OPENAI_BATCH_ENDPOINT,
                "completion_window": completion_window,
                "metadata": {"job_orchestrator_kind": "ranking"},
            },
            timeout=timeout,
        )
        batch.raise_for_status()
    except (OSError, KeyError, httpx.HTTPError) as exc:
        raise OpenAIBatchError(f"Could not submit OpenAI Batch job: {exc}") from exc

    metadata = batch.json()
    metadata["local_input_path"] = str(jsonl_path)
    _write_batch_metadata(metadata)
    return metadata


def retrieve_batch(batch_id: str, *, api_key: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise OpenAIBatchError("OPENAI_API_KEY is required to retrieve an OpenAI Batch job.")
    try:
        response = httpx.get(
            f"https://api.openai.com/v1/batches/{batch_id}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenAIBatchError(f"Could not retrieve OpenAI Batch job: {exc}") from exc
    metadata = response.json()
    _write_batch_metadata(metadata)
    return metadata


def download_file_content(file_id: str, *, api_key: str | None = None, timeout: float = 60.0) -> str:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise OpenAIBatchError("OPENAI_API_KEY is required to download OpenAI Batch output.")
    try:
        response = httpx.get(
            f"https://api.openai.com/v1/files/{file_id}/content",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenAIBatchError(f"Could not download OpenAI Batch output: {exc}") from exc
    return response.text


def import_ranking_batch_output(output_jsonl: str, *, ranking_version: str | None = None) -> dict[str, int]:
    version = ranking_version or llm_ranking_version(DEFAULT_LLM_MODEL)
    summary = {
        "processed": 0,
        "saved": 0,
        "failed": 0,
        "APPLY_NOW": 0,
        "APPLY_WITH_TAILORED_CV": 0,
        "MAYBE": 0,
        "SKIP": 0,
        "AVOID": 0,
    }
    for line in output_jsonl.splitlines():
        if not line.strip():
            continue
        summary["processed"] += 1
        try:
            item = json.loads(line)
            job_id = _job_id_from_custom_id(item.get("custom_id", ""))
            if item.get("error"):
                raise LLMRankingError(str(item["error"]))
            body = (item.get("response") or {}).get("body") or {}
            status_code = int((item.get("response") or {}).get("status_code") or 0)
            if status_code >= 400:
                raise LLMRankingError(f"Batch item failed with status {status_code}: {body}")
            payload = json.loads(_extract_response_text(body))
            ranking = _ranking_from_payload(payload, version)
            ranking.evidence.requires_llm_review = False
            reasons = list(ranking.evidence.llm_escalation_reasons or [])
            if "openai_batch_ranking_applied" not in reasons:
                reasons.append("openai_batch_ranking_applied")
            ranking.evidence.llm_escalation_reasons = reasons
            ranking.ranking_version = version
            db.save_job_ranking(job_id, ranking)
            summary["saved"] += 1
            summary[ranking.decision] += 1
        except (ValueError, KeyError, json.JSONDecodeError, LLMRankingError, OpenAIBatchError):
            summary["failed"] += 1
    return summary


def latest_batch_metadata(output_dir: Path = OPENAI_BATCH_DIR) -> dict[str, Any] | None:
    if not output_dir.exists():
        return None
    files = sorted(output_dir.glob("batch_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_batch_metadata(metadata: dict[str, Any], output_dir: Path = OPENAI_BATCH_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = metadata.get("id") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"batch_{batch_id}.json"
    payload = {**metadata, "saved_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _compact_job(job: dict[str, Any], *, max_description_chars: int) -> dict[str, Any]:
    keys = [
        "id",
        "job_id",
        "title",
        "company",
        "location",
        "workplace_type",
        "source",
        "url",
        "apply_url",
        "description_text",
        "posted_at",
        "posted_at_raw",
        "first_seen_at",
        "last_seen_at",
        "parse_confidence",
        "data_quality_flags",
    ]
    compact = {key: job.get(key) for key in keys if job.get(key) is not None}
    description = str(compact.get("description_text") or "")
    if len(description) > max_description_chars:
        compact["description_text"] = description[:max_description_chars] + "\n[truncated]"
    return compact


def _job_id_from_custom_id(custom_id: str) -> int:
    match = re.fullmatch(r"job_ranking_(\d+)", custom_id)
    if not match:
        raise OpenAIBatchError(f"Invalid batch custom_id: {custom_id}")
    return int(match.group(1))
