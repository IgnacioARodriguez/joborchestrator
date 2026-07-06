"""
Lógica de filtrado y generación de lotes para el ranking de ofertas.
Reutilizada tanto por la UI (app.py) como por el modo consola (preparar_lotes_cli.py).
"""

import math
import logging
import pandas as pd

FILAS_POR_LOTE_DEFAULT = 45
MIN_DESCRIPCION_LEN_DEFAULT = 200
logger = logging.getLogger(__name__)

PERFIL_CANDIDATO_DEFAULT = """\
PERFIL DEL CANDIDATO:
- 4+ años como backend/full stack developer (Python: Django, FastAPI, Flask;
  PostgreSQL, MongoDB, Redis, Docker, AWS, React, TypeScript, Three.js)
- Experiencia client-facing en cuentas grandes (Cepsa, Toyota, Abbott) vía consultoras
  (Fiction Express, Talan, Globant, Balloon Group)
- Sin experiencia formal en roles puramente comerciales/presales, pero con perfil
  técnico fuerte para apoyarlos
- Base en Málaga, España; abierto a remoto en España/UE
- Sin certificaciones de venta ni idiomas adicionales al inglés/español
"""

PROMPT_TEMPLATE = """\
Eres un analista de reclutamiento. Vas a puntuar ofertas de empleo NO por atractivo,
sueldo o prestigio, sino por PROBABILIDAD REALISTA de que este candidato consiga
el puesto rápido, dado su perfil.

{perfil}

CRITERIOS DE "FACILIDAD DE ENTRADA" (puntúa cada uno de 1 a 5, 5 = más fácil):

1. FIT_STACK: ¿cuánto de lo que pide la oferta ya lo tiene el candidato sin
   aprender nada nuevo? (5 = stack casi idéntico, 1 = stack totalmente distinto)
2. FIT_SENIORITY: ¿el nivel de experiencia pedido coincide con la del candidato?
   (5 = piden un rango que encaja bien, 3 = algo por encima/debajo pero razonable,
   1 = piden bastante más experiencia o es puramente junior sin transferibilidad)
3. BARRERAS_DURAS: ¿hay requisitos excluyentes difíciles de cumplir?
   (certificación obligatoria, idioma no dominado, título específico, sponsorship
   de visado necesario, etc.) (5 = sin barreras duras, 1 = varias barreras duras)
4. VOLUMEN_CONTRATACION: ¿es un rol de contratación masiva/frecuente (empresa grande,
   consultora, muchas vacantes similares) o un puesto muy nicho con pocas plazas?
   (5 = alta rotación/contratación frecuente, 1 = puesto único muy específico)
5. TRANSFERIBILIDAD_NARRATIVA: ¿qué tan fácil es justificar el fit en un CV/entrevista
   sin tener que "inventar" experiencia que no tiene? (5 = fit natural y obvio,
   1 = requeriría un salto narrativo forzado)

Para cada oferta del listado, devuelve SOLO una tabla en este formato (sin texto
adicional antes ni después):

id | titulo | empresa | FIT_STACK | FIT_SENIORITY | BARRERAS_DURAS | VOLUMEN_CONTRATACION | TRANSFERIBILIDAD | SCORE_TOTAL | razon_breve

Donde SCORE_TOTAL es la suma de los 5 criterios (máximo 25), y razon_breve es
UNA frase (máx 15 palabras) explicando el score.

No evalúes sueldo, prestigio de marca, ni interés personal del candidato en el
puesto -- solo facilidad de conseguirlo.

Este es el lote {num_lote} de {total_lotes} (categoría: {categoria}).
Devuelve la tabla completa para las {n_filas} ofertas de abajo, una fila por oferta.

OFERTAS A EVALUAR:
{datos}
"""


def slugify(texto: str) -> str:
    return (
        str(texto).lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
    )[:40] or "sin_categoria"


def formatear_oferta(row: pd.Series) -> str:
    desc = str(row.get("descripcion", "")).strip().replace("\n", " ")
    if len(desc) > 1200:
        desc = desc[:1200] + " [...]"
    return (
        f"---\n"
        f"id: {row.get('id', '')}\n"
        f"titulo: {row.get('titulo', '')}\n"
        f"empresa: {row.get('empresa', '')}\n"
        f"ubicacion: {row.get('ubicacion', '')}\n"
        f"modalidad: {row.get('modalidad', '')}\n"
        f"url: {row.get('url', '')}\n"
        f"descripcion: {desc}\n"
    )


def filtrar_ofertas(df: pd.DataFrame, min_descripcion_len: int = MIN_DESCRIPCION_LEN_DEFAULT):
    """Devuelve (df_filtrado, stats) sin gastar ni un token de IA."""
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


def generar_lotes(
    df: pd.DataFrame,
    filas_por_lote: int = FILAS_POR_LOTE_DEFAULT,
    perfil_candidato: str = PERFIL_CANDIDATO_DEFAULT,
):
    """
    Devuelve una lista de dicts:
    {numero, nombre, categoria, n_filas, prompt, ids}
    """
    lotes = []
    contador = 0

    for categoria, grupo in df.groupby("categoria"):
        grupo = grupo.reset_index(drop=True)
        n_sublotes = math.ceil(len(grupo) / filas_por_lote) if len(grupo) else 0

        for i in range(n_sublotes):
            sub = grupo.iloc[i * filas_por_lote : (i + 1) * filas_por_lote]
            contador += 1
            datos = "\n".join(formatear_oferta(row) for _, row in sub.iterrows())
            lotes.append(
                {
                    "numero": contador,
                    "nombre": f"lote_{contador:02d}_{slugify(categoria)}",
                    "categoria": categoria,
                    "n_filas": len(sub),
                    "ids": sub["id"].tolist() if "id" in sub.columns else [],
                    "datos_crudos": datos,
                    "sub_df": sub,
                }
            )

    total = len(lotes)
    for lote in lotes:
        lote["prompt"] = PROMPT_TEMPLATE.format(
            perfil=perfil_candidato,
            num_lote=lote["numero"],
            total_lotes=total,
            categoria=lote["categoria"],
            n_filas=lote["n_filas"],
            datos=lote["datos_crudos"],
        )

    return lotes


def parsear_tabla_respuesta(texto: str) -> pd.DataFrame:
    """
    Parsea la tabla markdown que devuelve la IA (formato pipe-separated) a un DataFrame.
    Tolerante a espacios, líneas separadoras (---) y texto extra antes/después.
    """
    columnas_esperadas = [
        "id", "titulo", "empresa", "FIT_STACK", "FIT_SENIORITY",
        "BARRERAS_DURAS", "VOLUMEN_CONTRATACION", "TRANSFERIBILIDAD",
        "SCORE_TOTAL", "razon_breve",
    ]

    filas = []
    header_vista = None

    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or "|" not in linea:
            continue
        # Salta líneas separadoras tipo | --- | --- |
        celdas_raw = [c.strip() for c in linea.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in celdas_raw if c):
            continue

        if header_vista is None and any(
            c.lower().replace(" ", "") in ("id", "score_total", "fit_stack") for c in [x.lower() for x in celdas_raw]
        ):
            header_vista = celdas_raw
            continue

        if header_vista is not None:
            if len(celdas_raw) < len(header_vista):
                celdas_raw += [""] * (len(header_vista) - len(celdas_raw))
            filas.append(celdas_raw[: len(header_vista)])

    if not header_vista or not filas:
        return pd.DataFrame(columns=columnas_esperadas)

    df = pd.DataFrame(filas, columns=header_vista)

    # Normaliza nombres de columna por si el modelo varía mayúsculas/espacios
    mapeo = {c: c for c in df.columns}
    for esperada in columnas_esperadas:
        for real in df.columns:
            if real.strip().lower().replace(" ", "_") == esperada.lower():
                mapeo[real] = esperada
    df = df.rename(columns=mapeo)

    for col in ["FIT_STACK", "FIT_SENIORITY", "BARRERAS_DURAS", "VOLUMEN_CONTRATACION",
                "TRANSFERIBILIDAD", "SCORE_TOTAL"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Asegurar que 'id' sea siempre string para evitar mismatch en merges
    if "id" in df.columns:
        df["id"] = df["id"].astype(str)

    return df
