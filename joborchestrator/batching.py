"""Filtering utilities for LinkedIn scraper exports."""

from __future__ import annotations

import logging

import pandas as pd

MIN_DESCRIPCION_LEN_DEFAULT = 200
logger = logging.getLogger(__name__)


def filtrar_ofertas(df: pd.DataFrame, min_descripcion_len: int = MIN_DESCRIPCION_LEN_DEFAULT):
    """Return a filtered DataFrame plus counters without calling any LLM."""
    stats = {"original": len(df)}

    if "id" in df.columns:
        duplicated = df[df.duplicated(subset=["id"], keep="first")]
        _log_discarded_rows(duplicated, "duplicate_id")
        df = df.drop_duplicates(subset=["id"])
    stats["tras_duplicados"] = len(df)

    if "extraccion_ok" in df.columns:
        extraction_failed = df[df["extraccion_ok"] == False]  # noqa: E712
        _log_discarded_rows(extraction_failed, "extraction_not_ok")
        df = df[df["extraccion_ok"] != False]  # noqa: E712
    stats["tras_extraccion_ok"] = len(df)

    if "descripcion" in df.columns:
        short_description = df[df["descripcion"].fillna("").str.len() < min_descripcion_len]
        _log_discarded_rows(short_description, f"description_shorter_than_{min_descripcion_len}")
        df = df[df["descripcion"].fillna("").str.len() >= min_descripcion_len]
    stats["tras_descripcion_minima"] = len(df)

    if "categoria" not in df.columns:
        df = df.copy()
        df["categoria"] = "sin_categoria"
    df["categoria"] = df["categoria"].fillna("sin_categoria")

    return df.reset_index(drop=True), stats


def _log_discarded_rows(rows: pd.DataFrame, reason: str) -> None:
    if rows.empty:
        return
    for _, row in rows.iterrows():
        external_id = row.get("external_id") or row.get("id") or row.get("job_id") or ""
        title = row.get("titulo") or row.get("title") or ""
        company = row.get("empresa") or row.get("company") or ""
        logger.warning(
            "Discarded job row during filtrar_ofertas: id=%s reason=%s title=%s company=%s",
            external_id,
            reason,
            title,
            company,
        )
