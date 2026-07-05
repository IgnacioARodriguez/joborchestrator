"""
Persistencia local (SQLite) para el pipeline de ofertas.

Guarda TODA oferta que pasó alguna vez por "Preparar lotes", para poder:
  - Deduplicar entre corridas (si en una semana vuelves a scrapear y salen
    las mismas ofertas, no se vuelven a mandar a la IA ni se re-muestran).
  - Marcar cuáles ya aplicaste, con fecha y notas.
  - Guardar el score de facilidad de entrada una vez consolidado.

El archivo .db vive junto a app.py, en la misma carpeta del proyecto —
mientras no borres o muevas esa carpeta, la persistencia sobrevive entre
sesiones y entre semanas.
"""

import sqlite3
import json
from datetime import datetime
import pandas as pd

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import normalize_job_identity
from joborchestrator.ranking.ranker import RANKING_VERSION, result_to_dict
from joborchestrator.ranking.schemas import RankingResult
from joborchestrator.paths import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ofertas (
    id TEXT PRIMARY KEY,
    titulo TEXT,
    empresa TEXT,
    ubicacion TEXT,
    modalidad TEXT,
    categoria TEXT,
    url TEXT,
    fecha_primera_vista TEXT,
    fecha_ultima_vista TEXT,
    veces_vista INTEGER DEFAULT 1,
    score_total REAL,
    fit_stack REAL,
    fit_seniority REAL,
    barreras_duras REAL,
    volumen_contratacion REAL,
    transferibilidad REAL,
    razon_breve TEXT,
    aplicado INTEGER DEFAULT 0,
    fecha_aplicado TEXT,
    notas TEXT
);
"""

SCANNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_ref TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_scan_at TEXT,
    last_scan_status TEXT,
    last_scan_error TEXT,
    UNIQUE(provider, company_ref)
);

CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT,
    location TEXT,
    workplace_type TEXT,
    department TEXT,
    url TEXT,
    apply_url TEXT,
    description_html TEXT,
    description_text TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    times_seen INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    content_hash TEXT,
    raw_payload TEXT,
    status TEXT DEFAULT 'seen',
    pipeline_status TEXT,
    identity_key TEXT,
    UNIQUE(source, company, external_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_status ON job_postings(status);
CREATE INDEX IF NOT EXISTS idx_job_postings_last_seen ON job_postings(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_job_postings_identity ON job_postings(identity_key);

CREATE TABLE IF NOT EXISTS scan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    provider TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_ref TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    found_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    unchanged_count INTEGER DEFAULT 0,
    error TEXT,
    duration_seconds REAL DEFAULT 0,
    FOREIGN KEY(source_id) REFERENCES company_sources(id)
);

CREATE TABLE IF NOT EXISTS job_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    final_score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    scores_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    reasoning_summary TEXT,
    recommended_application_angle TEXT,
    cv_keywords_to_emphasize_json TEXT,
    cv_keywords_to_avoid_overclaiming_json TEXT,
    ranking_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, ranking_version),
    FOREIGN KEY(job_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_job_rankings_decision ON job_rankings(decision);
CREATE INDEX IF NOT EXISTS idx_job_rankings_score ON job_rankings(final_score);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(SCHEMA)
    conn.executescript(SCANNER_SCHEMA)
    _ensure_scanner_columns(conn)
    return conn


def _ensure_scanner_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_postings)").fetchall()}
    if "pipeline_status" not in columns:
        conn.execute("ALTER TABLE job_postings ADD COLUMN pipeline_status TEXT")


def init_db():
    conn = _conn()
    conn.commit()
    conn.close()


def get_ids_ya_vistos() -> set:
    """Todos los ids que ya pasaron por el sistema alguna vez."""
    conn = _conn()
    try:
        rows = conn.execute("SELECT id FROM ofertas").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def registrar_ofertas_vistas(df: pd.DataFrame):
    """
    Inserta ofertas nuevas o actualiza fecha_ultima_vista/veces_vista si ya existían.
    No pisa el score ni el estado de aplicado si ya estaban seteados.
    """
    if df.empty or "id" not in df.columns:
        return

    ahora = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        for _, row in df.iterrows():
            existe = conn.execute(
                "SELECT id FROM ofertas WHERE id = ?", (row["id"],)
            ).fetchone()

            if existe:
                conn.execute(
                    "UPDATE ofertas SET fecha_ultima_vista = ?, veces_vista = veces_vista + 1 WHERE id = ?",
                    (ahora, row["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO ofertas
                       (id, titulo, empresa, ubicacion, modalidad, categoria, url,
                        fecha_primera_vista, fecha_ultima_vista, veces_vista)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        row["id"],
                        row.get("titulo", ""),
                        row.get("empresa", ""),
                        row.get("ubicacion", ""),
                        row.get("modalidad", ""),
                        row.get("categoria", ""),
                        row.get("url", ""),
                        ahora,
                        ahora,
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def guardar_scores(df_final: pd.DataFrame):
    """Actualiza los scores/razones de ranking una vez consolidado un lote de resultados."""
    if df_final.empty or "id" not in df_final.columns:
        return

    conn = _conn()
    try:
        for _, row in df_final.iterrows():
            conn.execute(
                """UPDATE ofertas SET
                       score_total = ?, fit_stack = ?, fit_seniority = ?,
                       barreras_duras = ?, volumen_contratacion = ?,
                       transferibilidad = ?, razon_breve = ?
                   WHERE id = ?""",
                (
                    row.get("SCORE_TOTAL"),
                    row.get("FIT_STACK"),
                    row.get("FIT_SENIORITY"),
                    row.get("BARRERAS_DURAS"),
                    row.get("VOLUMEN_CONTRATACION"),
                    row.get("TRANSFERIBILIDAD"),
                    row.get("razon_breve"),
                    row["id"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


def marcar_aplicado(id_oferta: str, aplicado: bool, notas: str = None):
    conn = _conn()
    try:
        fecha = datetime.now().isoformat(timespec="seconds") if aplicado else None
        if notas is not None:
            conn.execute(
                "UPDATE ofertas SET aplicado = ?, fecha_aplicado = ?, notas = ? WHERE id = ?",
                (int(aplicado), fecha, notas, id_oferta),
            )
        else:
            conn.execute(
                "UPDATE ofertas SET aplicado = ?, fecha_aplicado = ? WHERE id = ?",
                (int(aplicado), fecha, id_oferta),
            )
        conn.commit()
    finally:
        conn.close()


def actualizar_estado_bulk(df_editado: pd.DataFrame):
    """
    Recibe el DataFrame editado desde st.data_editor (con columnas id, aplicado, notas)
    y persiste todos los cambios de una vez.
    """
    conn = _conn()
    try:
        for _, row in df_editado.iterrows():
            aplicado = bool(row.get("aplicado", False))
            fecha = datetime.now().isoformat(timespec="seconds") if aplicado else None
            conn.execute(
                "UPDATE ofertas SET aplicado = ?, fecha_aplicado = COALESCE(?, fecha_aplicado), notas = ? WHERE id = ?",
                (int(aplicado), fecha if aplicado else None, row.get("notas", ""), row["id"]),
            )
        conn.commit()
    finally:
        conn.close()


def get_historial(solo_aplicadas: bool = False) -> pd.DataFrame:
    conn = _conn()
    try:
        query = "SELECT * FROM ofertas"
        if solo_aplicadas:
            query += " WHERE aplicado = 1"
        query += " ORDER BY score_total DESC NULLS LAST, fecha_ultima_vista DESC"
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    return df


def resetear_puntuaciones() -> int:
    """Borra scores y razones para poder recalcular con un sistema nuevo."""
    conn = _conn()
    try:
        cursor = conn.execute(
            """UPDATE ofertas SET
                   score_total = NULL,
                   fit_stack = NULL,
                   fit_seniority = NULL,
                   barreras_duras = NULL,
                   volumen_contratacion = NULL,
                   transferibilidad = NULL,
                   razon_breve = NULL
               WHERE score_total IS NOT NULL
                  OR fit_stack IS NOT NULL
                  OR fit_seniority IS NOT NULL
                  OR barreras_duras IS NOT NULL
                  OR volumen_contratacion IS NOT NULL
                  OR transferibilidad IS NOT NULL
                  OR razon_breve IS NOT NULL"""
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def borrar_historial() -> int:
    """Elimina todo el historial local de ofertas."""
    conn = _conn()
    try:
        cursor = conn.execute("DELETE FROM ofertas")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def add_company_source(
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool = True,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        cursor = conn.execute(
            """INSERT INTO company_sources
               (provider, company_name, company_ref, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, company_ref) DO UPDATE SET
                   company_name = excluded.company_name,
                   enabled = excluded.enabled,
                   updated_at = excluded.updated_at""",
            (provider, company_name, company_ref, int(enabled), now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM company_sources WHERE provider = ? AND company_ref = ?",
            (provider, company_ref),
        ).fetchone()
        return int(row["id"] if row else cursor.lastrowid)
    finally:
        conn.close()


def list_company_sources(enabled_only: bool = False) -> pd.DataFrame:
    conn = _conn()
    try:
        query = "SELECT * FROM company_sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY enabled DESC, company_name ASC"
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def update_company_source(
    source_id: int,
    provider: str,
    company_name: str,
    company_ref: str,
    enabled: bool,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE company_sources
               SET provider = ?, company_name = ?, company_ref = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (provider, company_name, company_ref, int(enabled), now, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_source_scan_state(source_id: int, status: str, error: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute(
            """UPDATE company_sources
               SET last_scan_at = ?, last_scan_status = ?, last_scan_error = ?, updated_at = ?
               WHERE id = ?""",
            (now, status, error, now, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_job_posting(job: JobPosting, seen_at: str | None = None) -> str:
    now = seen_at or datetime.now().isoformat(timespec="seconds")
    raw_payload = json.dumps(job.raw_payload, ensure_ascii=False, sort_keys=True)
    identity_key = normalize_job_identity(job.title, job.company, job.location)
    conn = _conn()
    try:
        existing = conn.execute(
            """SELECT id, first_seen_at, times_seen, content_hash, status
               FROM job_postings
               WHERE source = ? AND company = ? AND external_id = ?""",
            (job.source, job.company, job.external_id),
        ).fetchone()

        if existing is None:
            status = "new"
            conn.execute(
                """INSERT INTO job_postings (
                       external_id, source, company, title, location, workplace_type, department,
                       url, apply_url, description_html, description_text, salary_min, salary_max,
                       salary_currency, posted_at, first_seen_at, last_seen_at, times_seen,
                       is_active, content_hash, raw_payload, status, identity_key
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)""",
                (
                    job.external_id,
                    job.source,
                    job.company,
                    job.title,
                    job.location,
                    job.workplace_type,
                    job.department,
                    job.url,
                    job.apply_url,
                    job.description_html,
                    job.description_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.posted_at,
                    now,
                    now,
                    job.content_hash,
                    raw_payload,
                    status,
                    identity_key,
                ),
            )
        else:
            status = "updated" if existing["content_hash"] != job.content_hash else "seen"
            conn.execute(
                """UPDATE job_postings SET
                       title = ?, location = ?, workplace_type = ?, department = ?,
                       url = ?, apply_url = ?, description_html = ?, description_text = ?,
                       salary_min = ?, salary_max = ?, salary_currency = ?, posted_at = ?,
                       last_seen_at = ?, times_seen = times_seen + 1, is_active = 1,
                       content_hash = ?, raw_payload = ?, status = ?, identity_key = ?
                   WHERE source = ? AND company = ? AND external_id = ?""",
                (
                    job.title,
                    job.location,
                    job.workplace_type,
                    job.department,
                    job.url,
                    job.apply_url,
                    job.description_html,
                    job.description_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.posted_at,
                    now,
                    job.content_hash,
                    raw_payload,
                    status,
                    identity_key,
                    job.source,
                    job.company,
                    job.external_id,
                ),
            )
        conn.commit()
        return status
    finally:
        conn.close()


def upsert_job_postings(jobs: list[JobPosting], seen_at: str | None = None) -> dict[str, list[JobPosting]]:
    buckets = {"new": [], "updated": [], "seen": []}
    for job in jobs:
        status = upsert_job_posting(job, seen_at=seen_at)
        job.status = status
        buckets.setdefault(status, []).append(job)
    return buckets


def mark_jobs_inactive_for_source(source: str, company: str, active_external_ids: set[str]) -> int:
    if not active_external_ids:
        return 0
    placeholders = ",".join("?" for _ in active_external_ids)
    conn = _conn()
    try:
        cursor = conn.execute(
            f"""UPDATE job_postings
                SET is_active = 0
                WHERE source = ? AND company = ? AND external_id NOT IN ({placeholders})""",
            [source, company, *active_external_ids],
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def record_scan_event(
    source_id: int | None,
    provider: str,
    company_name: str,
    company_ref: str,
    started_at: str,
    finished_at: str,
    status: str,
    found_count: int,
    new_count: int,
    updated_count: int,
    unchanged_count: int,
    error: str | None,
    duration_seconds: float,
) -> int:
    conn = _conn()
    try:
        cursor = conn.execute(
            """INSERT INTO scan_events (
                   source_id, provider, company_name, company_ref, started_at, finished_at,
                   status, found_count, new_count, updated_count, unchanged_count, error, duration_seconds
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_id,
                provider,
                company_name,
                company_ref,
                started_at,
                finished_at,
                status,
                found_count,
                new_count,
                updated_count,
                unchanged_count,
                error,
                duration_seconds,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_job_postings(statuses: list[str] | None = None, limit: int = 200) -> pd.DataFrame:
    conn = _conn()
    try:
        params: list[object] = []
        query = "SELECT * FROM job_postings"
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_job_posting(job_id: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job_status(job_id: int, status: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE job_postings SET pipeline_status = ? WHERE id = ?", (status, job_id))
        conn.commit()
    finally:
        conn.close()


def get_scanner_overview() -> dict:
    conn = _conn()
    try:
        total_jobs = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        new_jobs = conn.execute("SELECT COUNT(*) FROM job_postings WHERE status = 'new'").fetchone()[0]
        updated_jobs = conn.execute("SELECT COUNT(*) FROM job_postings WHERE status = 'updated'").fetchone()[0]
        source_count = conn.execute("SELECT COUNT(*) FROM company_sources WHERE enabled = 1").fetchone()[0]
        recent_errors = conn.execute(
            "SELECT COUNT(*) FROM scan_events WHERE status = 'error' AND started_at >= datetime('now', '-7 day')"
        ).fetchone()[0]
        last_scan = conn.execute("SELECT MAX(finished_at) FROM scan_events").fetchone()[0]
        last_event = conn.execute(
            """SELECT new_count, updated_count, status
               FROM scan_events
               ORDER BY finished_at DESC
               LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    return {
        "total_jobs": total_jobs,
        "new_jobs": new_jobs,
        "updated_jobs": updated_jobs,
        "source_count": source_count,
        "recent_errors": recent_errors,
        "last_scan": last_scan,
        "last_scan_new": int(last_event["new_count"]) if last_event else 0,
        "last_scan_updated": int(last_event["updated_count"]) if last_event else 0,
        "last_scan_status": last_event["status"] if last_event else None,
    }


def get_recent_scan_errors(limit: int = 5) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(
            """SELECT company_name, provider, error, finished_at
               FROM scan_events
               WHERE status = 'error'
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def get_recent_scan_events(limit: int = 20) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(
            """SELECT *
               FROM scan_events
               ORDER BY finished_at DESC
               LIMIT ?""",
            conn,
            params=(limit,),
        )
    finally:
        conn.close()


def save_job_ranking(job_id: int, ranking: RankingResult) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    payload = result_to_dict(ranking)
    conn = _conn()
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
                       ranking_version, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    now,
                    now,
                ),
            )
            ranking_id = int(cursor.lastrowid)
        conn.commit()
        return ranking_id
    finally:
        conn.close()


def get_ranked_jobs(
    decisions: list[str] | None = None,
    min_score: int | None = None,
    sources: list[str] | None = None,
    with_red_flags: bool | None = None,
    ranking_version: str = RANKING_VERSION,
) -> pd.DataFrame:
    conn = _conn()
    try:
        params: list[object] = [ranking_version]
        query = """
            SELECT
                jp.id AS job_id, jp.title, jp.company, jp.location, jp.source, jp.url,
                jp.apply_url, jp.description_text, jp.department, jp.workplace_type,
                jp.first_seen_at, jp.last_seen_at, jp.status AS scan_status, jp.pipeline_status,
                jr.final_score, jr.decision, jr.confidence, jr.scores_json, jr.evidence_json,
                jr.reasoning_summary, jr.recommended_application_angle,
                jr.cv_keywords_to_emphasize_json, jr.cv_keywords_to_avoid_overclaiming_json,
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
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_unranked_jobs(ranking_version: str = RANKING_VERSION, limit: int = 500) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(
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


def stats_generales() -> dict:
    conn = _conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]
        aplicadas = conn.execute("SELECT COUNT(*) FROM ofertas WHERE aplicado = 1").fetchone()[0]
        con_score = conn.execute("SELECT COUNT(*) FROM ofertas WHERE score_total IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    return {"total_vistas": total, "aplicadas": aplicadas, "con_score": con_score}
