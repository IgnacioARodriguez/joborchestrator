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
from datetime import datetime
import pandas as pd

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


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


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


def stats_generales() -> dict:
    conn = _conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0]
        aplicadas = conn.execute("SELECT COUNT(*) FROM ofertas WHERE aplicado = 1").fetchone()[0]
        con_score = conn.execute("SELECT COUNT(*) FROM ofertas WHERE score_total IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    return {"total_vistas": total, "aplicadas": aplicadas, "con_score": con_score}
