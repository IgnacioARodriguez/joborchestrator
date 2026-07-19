from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Callable

import pandas as pd

from joborchestrator.ranking.schemas import RankingResult
from joborchestrator.ranking.serialization import result_to_dict
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.storage import db_connection

ConnectionFactory = Callable[[], db_connection.LibsqlConnection]
ReadSqlQuery = Callable[
    [str, sqlite3.Connection | db_connection.LibsqlConnection, list[object] | tuple[object, ...] | None],
    pd.DataFrame,
]


def save_job_ranking(
    connect: ConnectionFactory,
    job_id: int,
    ranking: RankingResult,
    *,
    ranking_provider: str | None = None,
    ranking_model: str | None = None,
    ranking_prompt_versions: dict | None = None,
    ranking_validation_attempts: int | None = None,
    ranking_validation_errors: list | None = None,
    ranking_candidate_profile_hash: str | None = None,
    ranking_candidate_profile_snapshot: dict | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    payload = result_to_dict(ranking)
    prompt_versions_json = (
        json.dumps(ranking_prompt_versions, ensure_ascii=False, sort_keys=True)
        if ranking_prompt_versions is not None
        else None
    )
    validation_errors_json = (
        json.dumps(ranking_validation_errors, ensure_ascii=False)
        if ranking_validation_errors is not None
        else None
    )
    profile_snapshot_json = (
        json.dumps(ranking_candidate_profile_snapshot, ensure_ascii=False, sort_keys=True)
        if ranking_candidate_profile_snapshot is not None
        else None
    )
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT id, created_at FROM job_rankings WHERE job_id = ? AND ranking_version = ?",
            (job_id, ranking.ranking_version),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE job_rankings SET
                       final_score = ?, decision = ?, confidence = ?, scores_json = ?,
                       evidence_json = ?, reasoning_summary = ?, recommended_application_angle = ?,
                       cv_keywords_to_emphasize_json = ?, cv_keywords_to_avoid_overclaiming_json = ?,
                       ranking_provider = COALESCE(?, ranking_provider),
                       ranking_model = COALESCE(?, ranking_model),
                       ranking_prompt_versions_json = COALESCE(?, ranking_prompt_versions_json),
                       ranking_validation_attempts = COALESCE(?, ranking_validation_attempts),
                       ranking_validation_errors_json = COALESCE(?, ranking_validation_errors_json),
                       ranking_candidate_profile_hash = COALESCE(?, ranking_candidate_profile_hash),
                       ranking_candidate_profile_snapshot_json = COALESCE(?, ranking_candidate_profile_snapshot_json),
                       updated_at = ?
                   WHERE id = ?""",
                (
                    ranking.final_score,
                    ranking.decision,
                    ranking.confidence,
                    json.dumps(payload["scores"], ensure_ascii=False),
                    json.dumps(payload["evidence"], ensure_ascii=False),
                    ranking.reasoning_summary,
                    ranking.recommended_application_angle,
                    json.dumps(ranking.cv_keywords_to_emphasize, ensure_ascii=False),
                    json.dumps(ranking.cv_keywords_to_avoid_overclaiming, ensure_ascii=False),
                    ranking_provider,
                    ranking_model,
                    prompt_versions_json,
                    ranking_validation_attempts,
                    validation_errors_json,
                    ranking_candidate_profile_hash,
                    profile_snapshot_json,
                    now,
                    existing["id"],
                ),
            )
            ranking_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """INSERT INTO job_rankings (
                       job_id, final_score, decision, confidence, scores_json, evidence_json,
                       reasoning_summary, recommended_application_angle,
                       cv_keywords_to_emphasize_json, cv_keywords_to_avoid_overclaiming_json,
                       ranking_version, ranking_provider, ranking_model, ranking_prompt_versions_json,
                       ranking_validation_attempts, ranking_validation_errors_json,
                       ranking_candidate_profile_hash, ranking_candidate_profile_snapshot_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    ranking.final_score,
                    ranking.decision,
                    ranking.confidence,
                    json.dumps(payload["scores"], ensure_ascii=False),
                    json.dumps(payload["evidence"], ensure_ascii=False),
                    ranking.reasoning_summary,
                    ranking.recommended_application_angle,
                    json.dumps(ranking.cv_keywords_to_emphasize, ensure_ascii=False),
                    json.dumps(ranking.cv_keywords_to_avoid_overclaiming, ensure_ascii=False),
                    ranking.ranking_version,
                    ranking_provider,
                    ranking_model,
                    prompt_versions_json,
                    ranking_validation_attempts,
                    validation_errors_json,
                    ranking_candidate_profile_hash,
                    profile_snapshot_json,
                    now,
                    now,
                ),
            )
            ranking_id = int(cursor.lastrowid)
        _update_job_posting_ranking_signals(conn, job_id, ranking)
        conn.commit()
        return ranking_id
    finally:
        conn.close()


def delete_job_rankings(connect: ConnectionFactory, ranking_version: str | None = None) -> int:
    conn = connect()
    try:
        if ranking_version:
            cursor = conn.execute("DELETE FROM job_rankings WHERE ranking_version = ?", (ranking_version,))
        else:
            cursor = conn.execute("DELETE FROM job_rankings")
        deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_postings)").fetchall()}
        reset_columns = [
            "speed_signal",
            "role_viable",
            "duplicate_of_job_id",
            "application_effort_signal",
            "data_quality_signal",
            "source_reliability_signal",
        ]
        assignments = [f"{column} = NULL" for column in reset_columns if column in columns]
        if assignments:
            conn.execute(f"UPDATE job_postings SET {', '.join(assignments)}")
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_ranked_jobs(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    decisions: list[str] | None = None,
    min_score: int | None = None,
    sources: list[str] | None = None,
    with_red_flags: bool | None = None,
    ranking_version: str = NVIDIA_RANKING_VERSION,
) -> pd.DataFrame:
    conn = connect()
    try:
        params: list[object] = [ranking_version]
        query = """
            SELECT
                jp.id AS job_id, jp.title, jp.company, jp.location, jp.source, jp.url,
                jp.apply_url, jp.description_text, jp.department, jp.workplace_type,
                jp.first_seen_at, jp.last_seen_at, jp.status AS scan_status, jp.pipeline_status,
                jp.recruiter_message, jp.cover_letter, jp.ats_cv_text, jp.autofill_notes,
                jp.parse_confidence, jp.data_quality_flags,
                jr.final_score, jr.decision, jr.confidence, jr.scores_json, jr.evidence_json,
                jr.reasoning_summary, jr.recommended_application_angle,
                jr.cv_keywords_to_emphasize_json, jr.cv_keywords_to_avoid_overclaiming_json,
                jr.ranking_provider, jr.ranking_model, jr.ranking_prompt_versions_json,
                jr.ranking_validation_attempts, jr.ranking_validation_errors_json,
                jr.ranking_candidate_profile_hash,
                jr.ranking_version, jr.updated_at AS ranked_at
            FROM job_rankings jr
            JOIN job_postings jp ON jp.id = jr.job_id
            WHERE jr.ranking_version = ?
        """
        if decisions:
            placeholders = ",".join("?" for _ in decisions)
            query += f" AND jr.decision IN ({placeholders})"
            params.extend(decisions)
        if min_score is not None:
            query += " AND jr.final_score >= ?"
            params.append(min_score)
        if sources:
            placeholders = ",".join("?" for _ in sources)
            query += f" AND jp.source IN ({placeholders})"
            params.extend(sources)
        if with_red_flags is True:
            query += " AND jr.evidence_json LIKE '%red_flags%' AND jr.evidence_json NOT LIKE '%\"red_flags\": []%'"
        elif with_red_flags is False:
            query += " AND (jr.evidence_json LIKE '%\"red_flags\": []%' OR jr.evidence_json NOT LIKE '%red_flags%')"
        query += """
            ORDER BY
              CASE jr.decision
                WHEN 'APPLY_NOW' THEN 1
                WHEN 'APPLY_WITH_TAILORED_CV' THEN 2
                WHEN 'MAYBE' THEN 3
                WHEN 'SKIP' THEN 4
                WHEN 'AVOID' THEN 5
                ELSE 6
              END,
              jr.final_score DESC
        """
        return read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_ranking_versions(connect: ConnectionFactory) -> list[str]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT ranking_version FROM job_rankings ORDER BY ranking_version DESC"
        ).fetchall()
        return [row["ranking_version"] for row in rows]
    finally:
        conn.close()


def get_rankings_for_job_ids(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    ranking_version: str,
    job_ids: list[int],
) -> pd.DataFrame:
    if not job_ids:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in job_ids)
    conn = connect()
    try:
        return read_sql_query(
            f"""SELECT *
                FROM job_rankings
                WHERE ranking_version = ?
                  AND job_id IN ({placeholders})""",
            conn,
            params=[ranking_version, *job_ids],
        )
    finally:
        conn.close()


def get_unranked_jobs(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    limit: int = 500,
) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
            """SELECT jp.*
               FROM job_postings jp
               LEFT JOIN job_rankings jr
                 ON jr.job_id = jp.id AND jr.ranking_version = ?
               WHERE jr.id IS NULL
               ORDER BY jp.last_seen_at DESC
               LIMIT ?""",
            conn,
            params=(ranking_version, limit),
        )
    finally:
        conn.close()


def get_jobs_for_post_scan_ranking(
    connect: ConnectionFactory,
    read_sql_query: ReadSqlQuery,
    *,
    seen_since: str,
    ranking_version: str = NVIDIA_RANKING_VERSION,
    limit: int = 500,
) -> pd.DataFrame:
    conn = connect()
    try:
        return read_sql_query(
            """SELECT jp.*
               FROM job_postings jp
               LEFT JOIN job_rankings jr
                 ON jr.job_id = jp.id AND jr.ranking_version = ?
               WHERE jp.last_seen_at >= ?
                 AND (jp.status IN ('new', 'updated') OR jr.id IS NULL)
               ORDER BY
                 CASE jp.status WHEN 'new' THEN 2 WHEN 'updated' THEN 1 ELSE 0 END DESC,
                 jp.last_seen_at DESC
               LIMIT ?""",
            conn,
            params=(ranking_version, seen_since, limit),
        )
    finally:
        conn.close()


def _update_job_posting_ranking_signals(
    conn: sqlite3.Connection,
    job_id: int,
    ranking: RankingResult,
) -> None:
    role_fit = float(ranking.scores.role_fit)
    requires_llm_review = bool(ranking.evidence.requires_llm_review)
    role_viable = role_fit >= 55 and ranking.decision not in {"SKIP", "AVOID"} and not requires_llm_review
    conn.execute(
        """UPDATE job_postings SET
               speed_signal = ?,
               role_viable = ?,
               application_effort_signal = ?,
               data_quality_signal = ?,
               source_reliability_signal = ?
           WHERE id = ?""",
        (
            ranking.scores.speed_signal,
            int(role_viable),
            ranking.scores.application_effort_signal,
            ranking.scores.data_quality_signal,
            ranking.scores.source_reliability_signal,
            job_id,
        ),
    )
