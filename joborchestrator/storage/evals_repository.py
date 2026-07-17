from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[..., pd.DataFrame]


def save_llm_eval_run(connect: ConnectionFactory, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    conn = connect()
    try:
        cursor = conn.execute(
            """INSERT INTO llm_eval_runs (
                   case_id, artifact_type, job_id, ranking_version, provider, model,
                   passed, score, issues_json, metrics_json, output_json,
                   judge_payload_json, judge_provider, judge_model, judge_result_json,
                   notes, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["case_id"],
                payload["artifact_type"],
                payload.get("job_id"),
                payload.get("ranking_version"),
                payload.get("provider"),
                payload.get("model"),
                1 if payload.get("passed") else 0,
                int(payload.get("score") or 0),
                json.dumps(payload.get("issues") or [], ensure_ascii=False),
                json.dumps(payload.get("metrics") or {}, ensure_ascii=False),
                json.dumps(payload.get("output") or {}, ensure_ascii=False),
                json.dumps(payload.get("judge_payload") or {}, ensure_ascii=False),
                payload.get("judge_provider"),
                payload.get("judge_model"),
                json.dumps(payload.get("judge_result") or {}, ensure_ascii=False),
                payload.get("notes"),
                now,
            ),
        )
        conn.commit()
        saved = dict(payload)
        saved["id"] = int(cursor.lastrowid)
        saved["created_at"] = now
        return saved
    finally:
        conn.close()


def list_llm_eval_runs(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    *,
    limit: int = 50,
    case_id: str | None = None,
    artifact_type: str | None = None,
) -> pd.DataFrame:
    params: list[object] = []
    query = "SELECT * FROM llm_eval_runs WHERE 1 = 1"
    if case_id:
        query += " AND case_id = ?"
        params.append(case_id)
    if artifact_type:
        query += " AND artifact_type = ?"
        params.append(artifact_type)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    conn = connect()
    try:
        return read_sql_query(query, conn, params=params)
    finally:
        conn.close()
