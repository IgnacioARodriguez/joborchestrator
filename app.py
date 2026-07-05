"""
Job Orchestrator â€” UI local para tu pipeline de bÃºsqueda de empleo.

Corre con:
    streamlit run app.py

IMPORTANTE: el scraping SIGUE corriendo en local, con tu sesiÃ³n real de LinkedIn
y un navegador visible. Esta UI solo lo orquesta como subproceso; no automatiza
aplicar a ofertas ni enviar mensajes (eso sigue fuera de alcance a propÃ³sito).
"""

import subprocess
import sys
from io import BytesIO
import asyncio
import json
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from joborchestrator.batching import (
    filtrar_ofertas,
    generar_lotes,
    parsear_tabla_respuesta,
    PERFIL_CANDIDATO_DEFAULT,
    FILAS_POR_LOTE_DEFAULT,
    MIN_DESCRIPCION_LEN_DEFAULT,
)
from joborchestrator.paths import LINKEDIN_SCRAPER, PROJECT_ROOT, SALIDAS_DIR
from joborchestrator.storage import persistence as db
from joborchestrator.scanning import scanner as source_scanner
from joborchestrator.scanning.providers import PROVIDERS
from joborchestrator.ranking import persistence as ranking_store
from joborchestrator.ranking.ranker import RANKING_VERSION

db.init_db()

BASE_DIR = PROJECT_ROOT
CHATGPT_PROMPT_URL = "https://chatgpt.com/?q={prompt}"
MAX_PREFILL_URL_CHARS = 7500

st.set_page_config(page_title="Job Orchestrator", layout="wide")

if "lotes" not in st.session_state:
    st.session_state.lotes = []
if "resultados" not in st.session_state:
    st.session_state.resultados = {}  # nombre_lote -> DataFrame
if "df_filtrado" not in st.session_state:
    st.session_state.df_filtrado = None


def build_chatgpt_url(prompt: str) -> str:
    return CHATGPT_PROMPT_URL.format(prompt=quote(prompt))


def render_chatgpt_tabs_launcher(lotes: list[dict]) -> None:
    urls = [
        {
            "label": f"Lote {lote['numero']:02d} - {lote['categoria']}",
            "url": build_chatgpt_url(lote["prompt"]),
            "tooLong": len(lote["prompt"]) > MAX_PREFILL_URL_CHARS,
        }
        for lote in lotes
    ]
    payload = json.dumps(urls).replace("</", "<\\/")
    components.html(
        f"""
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button id="open-chatgpt-lots" style="
            border:0;border-radius:6px;padding:9px 14px;font-weight:600;
            background:#111827;color:white;cursor:pointer">
            Abrir todos en ChatGPT
          </button>
          <span id="open-chatgpt-status" style="font:13px sans-serif;color:#555"></span>
        </div>
        <script>
          const lots = {payload};
          const button = document.getElementById("open-chatgpt-lots");
          const status = document.getElementById("open-chatgpt-status");

          button.addEventListener("click", () => {{
            let opened = 0;
            lots.forEach((lot, index) => {{
              setTimeout(() => {{
                const tab = window.open(lot.url, "_blank", "noopener,noreferrer");
                if (tab) opened += 1;
                status.textContent = `Abiertas ${{opened}}/${{lots.length}} pestaÃ±as. Si falta alguna, permite popups.`;
              }}, index * 250);
            }});
          }});
        </script>
        """,
        height=46,
    )


def render_badge(label: str, tone: str = "neutral") -> str:
    colors = {
        "new": ("#e6f5ee", "#1f6f55"),
        "updated": ("#fff4df", "#8a5a11"),
        "seen": ("#eef1f4", "#52606d"),
        "applied": ("#e7f0ff", "#2454a6"),
        "discarded": ("#f7e8e8", "#9c2f2f"),
        "error": ("#fdecec", "#a83232"),
        "neutral": ("#eef1f4", "#52606d"),
    }
    bg, fg = colors.get(tone, colors["neutral"])
    return (
        f"<span style='display:inline-flex;align-items:center;border-radius:999px;"
        f"padding:3px 9px;font-size:12px;font-weight:700;background:{bg};color:{fg};'>"
        f"{label}</span>"
    )


def render_job_card(row: dict) -> None:
    scan_status = row.get("status") or "seen"
    pipeline_status = row.get("pipeline_status")
    badges = render_badge(scan_status.title(), scan_status)
    if pipeline_status:
        badges += " " + render_badge(str(pipeline_status).title(), str(pipeline_status))
    st.markdown(
        f"""
        <div style="border:1px solid #dfe5dc;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:white;box-shadow:0 1px 2px rgba(23,33,27,0.04);">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div>
              <div style="font-size:17px;font-weight:750;color:#17211b;">{row.get('title') or 'Untitled role'}</div>
              <div style="margin-top:4px;color:#6d756f;font-size:13px;">{row.get('company') or '-'} Â· {row.get('location') or 'Location not listed'} Â· {row.get('source') or '-'}</div>
            </div>
            <div>{badges}</div>
          </div>
          <div style="display:flex;gap:18px;margin-top:12px;color:#6d756f;font-size:12px;">
            <span>First seen: {row.get('first_seen_at') or '-'}</span>
            <span>Last seen: {row.get('last_seen_at') or '-'}</span>
            <span>Seen {row.get('times_seen') or 0}x</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_badge(decision: str) -> str:
    tone = {
        "APPLY_NOW": ("#e6f5ee", "#1f6f55"),
        "APPLY_WITH_TAILORED_CV": ("#e7f0ff", "#2454a6"),
        "MAYBE": ("#fff4df", "#8a5a11"),
        "SKIP": ("#eef1f4", "#52606d"),
        "AVOID": ("#fdecec", "#a83232"),
    }.get(decision, ("#eef1f4", "#52606d"))
    bg, fg = tone
    label = "TAILOR_CV" if decision == "APPLY_WITH_TAILORED_CV" else decision
    return (
        f"<span style='display:inline-flex;border-radius:999px;padding:4px 10px;"
        f"font-size:12px;font-weight:800;background:{bg};color:{fg};'>{label}</span>"
    )

st.markdown(
    """
    <style>
    :root {
        --bg: #f7f8f5;
        --surface: #ffffff;
        --ink: #17211b;
        --muted: #6d756f;
        --line: #dfe5dc;
        --accent: #286f5a;
    }

    .stApp {
        background: linear-gradient(180deg, #fbfcf9 0%, var(--bg) 340px);
        color: var(--ink);
    }

    .block-container {
        max-width: 1180px;
        padding-top: 2.1rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3, h4 {
        color: var(--ink);
        letter-spacing: 0;
    }

    h1 {
        font-size: 2.15rem;
        line-height: 1.08;
        margin-bottom: 0.35rem;
    }

    .app-kicker {
        color: var(--accent);
        font-size: 0.77rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.45rem;
    }

    .app-subtitle {
        color: var(--muted);
        font-size: 0.98rem;
        max-width: 720px;
        margin-bottom: 1.15rem;
    }

    .flow-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1px;
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--line);
        margin: 1.25rem 0 1.1rem;
    }

    .flow-step {
        background: rgba(255,255,255,0.86);
        padding: 0.8rem 0.9rem;
    }

    .flow-step strong {
        display: block;
        font-size: 0.86rem;
    }

    .flow-step span {
        display: block;
        color: var(--muted);
        font-size: 0.78rem;
        margin-top: 0.16rem;
    }

    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.78);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
    }

    div[data-testid="stMetricLabel"] p {
        color: var(--muted);
        font-size: 0.78rem;
    }

    div[data-testid="stMetricValue"] {
        color: var(--ink);
        font-size: 1.35rem;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.25rem;
        border-bottom: 1px solid var(--line);
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        color: var(--muted);
        font-weight: 600;
        padding: 0.65rem 0.95rem;
    }

    .stTabs [aria-selected="true"] {
        color: var(--ink);
        background: var(--surface);
        border: 1px solid var(--line);
        border-bottom-color: var(--surface);
    }

    .stButton > button,
    .stDownloadButton > button,
    .stLinkButton > a {
        border-radius: 6px;
        border: 1px solid var(--line);
        box-shadow: none;
        font-weight: 650;
    }

    .stButton > button[kind="primary"] {
        background: var(--ink);
        border-color: var(--ink);
        color: white;
    }

    .stTextInput input,
    .stTextArea textarea,
    .stNumberInput input,
    div[data-baseweb="select"] > div {
        border-radius: 6px;
    }

    div[data-testid="stAlert"],
    div[data-testid="stExpander"],
    div[data-testid="stDataFrame"],
    div[data-testid="stDataEditor"] {
        border-radius: 8px;
    }

    pre {
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        background: #fbfcf9 !important;
    }

    hr {
        margin: 1.35rem 0;
        border-color: var(--line);
    }

    @media (max-width: 760px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }

        .flow-strip {
            grid-template-columns: 1fr;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="app-kicker">Local career ops</div>', unsafe_allow_html=True)
st.title("Job Orchestrator")
st.markdown(
    '<div class="app-subtitle">Un tablero compacto para escanear ofertas, preparar lotes con IA, consolidar ranking y mantener historial sin perder contexto.</div>',
    unsafe_allow_html=True,
)

_stats = db.stats_generales()
metric_cols = st.columns(3)
with metric_cols[0]:
    st.metric("Ofertas vistas", _stats["total_vistas"])
with metric_cols[1]:
    st.metric("Ya puntuadas", _stats["con_score"])
with metric_cols[2]:
    st.metric("Aplicadas", _stats["aplicadas"])

st.markdown(
    """
    <div class="flow-strip">
      <div class="flow-step"><strong>1. Captura</strong><span>Scraper o portal scanner</span></div>
      <div class="flow-step"><strong>2. Lotes</strong><span>Prompts listos para IA</span></div>
      <div class="flow-step"><strong>3. Ranking</strong><span>Scores y decision</span></div>
      <div class="flow-step"><strong>4. Historial</strong><span>Seguimiento continuo</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Scraping", "Lotes", "Ranking legacy", "Historial", "Opportunity Ranking", "Portal scanner"]
)
# ---------------------------------------------------------------------------
# TAB 1 â€” SCRAPING
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Lanzar el scraper")
    st.markdown(
        "Esto ejecuta el scraper de LinkedIn en un proceso aparte. "
        "Se abrirÃ¡ un navegador real donde tendrÃ¡s que loguearte a mano la primera vez "
        "(igual que corriÃ©ndolo directo por consola). **Esta pestaÃ±a solo lanza y muestra logs â€” "
        "no cambia nada de cÃ³mo scrapea.**"
    )

    if not LINKEDIN_SCRAPER.exists():
        st.error("No encuentro el scraper de LinkedIn dentro de `joborchestrator/scanning/`.")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            lanzar = st.button("â–¶ Iniciar scraping", type="primary")
        with col2:
            st.info("Alternativa: corre `python -m joborchestrator.scanning.linkedin` en tu terminal, "
                    "y usa solo las pestaÃ±as 2 y 3 de aquÃ­.")

        if lanzar:
            log_box = st.empty()
            logs = []
            proceso = subprocess.Popen(
                [sys.executable, str(LINKEDIN_SCRAPER)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with st.spinner("Scraping en curso... revisa el navegador que se abriÃ³."):
                for linea in proceso.stdout:
                    logs.append(linea.rstrip())
                    log_box.code("\n".join(logs[-40:]), language="text")
                proceso.wait()

            if proceso.returncode == 0:
                st.success("Scraping terminado. Ve a la pestaÃ±a 2 para preparar los lotes.")
            else:
                st.warning(f"El proceso terminÃ³ con cÃ³digo {proceso.returncode}. Revisa el log arriba.")

    st.divider()
    st.markdown("**Archivos de salida encontrados:**")
    if SALIDAS_DIR.exists():
        excels = sorted(SALIDAS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if excels:
            for p in excels[:5]:
                st.text(f"ðŸ“„ {p.name}")
        else:
            st.text("AÃºn no hay .xlsx en salidas_todas_posiciones_raw/")
    else:
        st.text("TodavÃ­a no existe la carpeta de salidas (corre el scraper primero).")

# ---------------------------------------------------------------------------
# TAB 2 â€” PREPARAR LOTES
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Cargar Excel y generar lotes")

    origen = st.radio(
        "Â¿De dÃ³nde saco el Excel?",
        ["Usar el mÃ¡s reciente de salidas_todas_posiciones_raw/", "Subir un archivo"],
        horizontal=False,
    )

    df_crudo = None
    if origen.startswith("Usar"):
        if SALIDAS_DIR.exists():
            excels = sorted(SALIDAS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if excels:
                st.text(f"Usando: {excels[0].name}")
                df_crudo = pd.read_excel(excels[0])
            else:
                st.warning("No hay ningÃºn .xlsx todavÃ­a. Sube uno manualmente.")
        else:
            st.warning("No existe la carpeta de salidas todavÃ­a. Sube un archivo manualmente.")
    else:
        subido = st.file_uploader("Sube tu Excel de ofertas", type=["xlsx"])
        if subido:
            df_crudo = pd.read_excel(subido)

    if df_crudo is not None:
        c1, c2 = st.columns(2)
        with c1:
            filas_por_lote = st.number_input(
                "Filas por lote", min_value=10, max_value=100,
                value=FILAS_POR_LOTE_DEFAULT, step=5,
            )
        with c2:
            min_desc_len = st.number_input(
                "Longitud mÃ­nima de descripciÃ³n (filtra basura)",
                min_value=0, max_value=2000, value=MIN_DESCRIPCION_LEN_DEFAULT, step=50,
            )

        perfil = st.text_area("Perfil del candidato (editable)", value=PERFIL_CANDIDATO_DEFAULT, height=180)

        ids_ya_vistos = db.get_ids_ya_vistos()
        forzar_incluir_vistas = st.checkbox(
            "Incluir de todas formas ofertas que ya vi en corridas anteriores",
            value=False,
            help="Por defecto se excluyen para no volver a mandarlas a la IA ni re-mostrarlas.",
        )

        if st.button("Generar lotes", type="primary"):
            df_filtrado, stats = filtrar_ofertas(df_crudo, min_descripcion_len=min_desc_len)

            n_antes_dedup = len(df_filtrado)
            if not forzar_incluir_vistas and "id" in df_filtrado.columns and ids_ya_vistos:
                df_filtrado = df_filtrado[~df_filtrado["id"].isin(ids_ya_vistos)].reset_index(drop=True)
            n_despues_dedup = len(df_filtrado)

            st.session_state.df_filtrado = df_filtrado

            st.write(
                f"Original: **{stats['original']}** â†’ tras duplicados: **{stats['tras_duplicados']}** "
                f"â†’ tras extracciÃ³n OK: **{stats['tras_extraccion_ok']}** "
                f"â†’ tras descripciÃ³n mÃ­nima: **{stats['tras_descripcion_minima']}** "
                f"â†’ tras excluir ya vistas antes: **{n_despues_dedup}** "
                f"({n_antes_dedup - n_despues_dedup} descartadas por repetidas)"
            )

            if df_filtrado.empty:
                st.warning("No quedÃ³ ninguna oferta nueva tras deduplicar. "
                           "Si querÃ©s reprocesarlas igual, marcÃ¡ la casilla de arriba.")
            else:
                lotes = generar_lotes(df_filtrado, filas_por_lote=filas_por_lote, perfil_candidato=perfil)
                st.session_state.lotes = lotes
                # Registra en el histÃ³rico apenas se generan lotes, asÃ­ una corrida
                # posterior en la misma semana ya no las vuelve a traer aunque no
                # llegues a consolidar el ranking.
                db.registrar_ofertas_vistas(df_filtrado)
                st.success(f"{len(lotes)} lotes generados. BajÃ¡ para copiarlos uno por uno.")

    if st.session_state.lotes:
        st.divider()
        st.markdown(f"### {len(st.session_state.lotes)} lotes listos")
        st.caption("AbrÃ­ una conversaciÃ³n NUEVA en Claude.ai o ChatGPT por cada lote, pega el contenido, "
                   "y guardÃ¡ la tabla de respuesta para la pestaÃ±a 3.")

        prompts_largos = [
            lote for lote in st.session_state.lotes
            if len(lote["prompt"]) > MAX_PREFILL_URL_CHARS
        ]
        render_chatgpt_tabs_launcher(st.session_state.lotes)
        if prompts_largos:
            st.warning(
                f"{len(prompts_largos)} prompt(s) son largos para precargar por URL. "
                "Si ChatGPT abre el chat sin texto, usa el bloque de prompt de cada lote para copiar y pegar."
            )
        st.caption(
            "El prellenado usa URLs de ChatGPT y puede depender del navegador/sesion. "
            "Si el navegador bloquea pestanas, permite popups para esta app o abre los lotes uno por uno."
        )

        for lote in st.session_state.lotes:
            with st.expander(f"Lote {lote['numero']:02d} â€” {lote['categoria']} ({lote['n_filas']} ofertas)"):
                st.link_button(
                    "Abrir este lote en ChatGPT",
                    build_chatgpt_url(lote["prompt"]),
                )
                st.code(lote["prompt"], language="text")

# ---------------------------------------------------------------------------
# TAB 3 â€” CONSOLIDAR
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Pegar respuestas de la IA y consolidar")

    if not st.session_state.lotes:
        st.info("Primero generÃ¡ los lotes en la pestaÃ±a 2.")
    else:
        nombres_lotes = [f"{l['numero']:02d} â€” {l['categoria']} ({l['n_filas']} ofertas)" for l in st.session_state.lotes]
        seleccion = st.selectbox("Â¿QuÃ© lote estÃ¡s pegando?", nombres_lotes)
        idx = nombres_lotes.index(seleccion)
        lote_actual = st.session_state.lotes[idx]

        respuesta_texto = st.text_area(
            "PegÃ¡ aquÃ­ la tabla que te devolviÃ³ Claude/ChatGPT para este lote",
            height=250,
            key=f"resp_{lote_actual['nombre']}",
        )

        if st.button("Guardar este lote"):
            df_parsed = parsear_tabla_respuesta(respuesta_texto)
            if df_parsed.empty:
                st.error("No pude parsear ninguna fila. RevisÃ¡ que hayas pegado la tabla completa con el separador '|'.")
            else:
                st.session_state.resultados[lote_actual["nombre"]] = df_parsed
                st.success(f"Guardado: {len(df_parsed)} filas parseadas.")
                st.dataframe(df_parsed, use_container_width=True)

        st.divider()
        guardados = list(st.session_state.resultados.keys())
        st.markdown(f"**Lotes guardados: {len(guardados)} / {len(st.session_state.lotes)}**")
        for nombre in guardados:
            st.text(f"âœ… {nombre}")

        if guardados:
            if st.button("ðŸ”— Consolidar ranking final", type="primary"):
                df_final = pd.concat(st.session_state.resultados.values(), ignore_index=True)

                # Enriquece con datos originales (empresa, url, modalidad, descripcion) si hay match por id
                if st.session_state.df_filtrado is not None and "id" in df_final.columns:
                    cols_extra = [c for c in ["id", "url", "modalidad", "ubicacion", "busqueda_keywords"]
                                  if c in st.session_state.df_filtrado.columns]
                    if cols_extra:
                        # Convertir 'id' a string en ambos para evitar mismatch str/int64
                        df_final["id"] = df_final["id"].astype(str)
                        df_temp = st.session_state.df_filtrado[cols_extra].copy()
                        df_temp["id"] = df_temp["id"].astype(str)
                        df_final = df_final.merge(
                            df_temp, on="id", how="left", suffixes=("", "_orig")
                        )

                if "SCORE_TOTAL" in df_final.columns:
                    df_final = df_final.sort_values("SCORE_TOTAL", ascending=False)

                # Persiste los scores en la base para no perderlos y para que
                # queden visibles en la pestaÃ±a de Historial.
                db.guardar_scores(df_final)

                st.session_state.df_final = df_final
                st.success(f"Ranking final: {len(df_final)} ofertas. Scores guardados en el histÃ³rico.")

        if "df_final" in st.session_state:
            st.markdown("### Ranking final â€” marcÃ¡ acÃ¡ directamente las que ya aplicaste")
            df_mostrar = st.session_state.df_final.copy()
            if "aplicado" not in df_mostrar.columns:
                df_mostrar["aplicado"] = False
            if "notas" not in df_mostrar.columns:
                df_mostrar["notas"] = ""

            columnas_visibles = [c for c in [
                "id", "titulo", "empresa", "SCORE_TOTAL", "url", "modalidad",
                "razon_breve", "aplicado", "notas",
            ] if c in df_mostrar.columns]

            df_editado = st.data_editor(
                df_mostrar[columnas_visibles],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "url": st.column_config.LinkColumn("Link oferta"),
                    "aplicado": st.column_config.CheckboxColumn("Â¿Aplicado?"),
                    "SCORE_TOTAL": st.column_config.NumberColumn("Score", format="%.0f"),
                },
                disabled=[c for c in columnas_visibles if c not in ("aplicado", "notas")],
                key="editor_ranking_final",
            )

            if st.button("ðŸ’¾ Guardar estado de 'aplicado' en el histÃ³rico"):
                db.actualizar_estado_bulk(df_editado)
                st.success("Estado guardado. Ya no hace falta que las vuelvas a ver la prÃ³xima semana.")

            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_editado.to_excel(writer, index=False, sheet_name="Ranking")
            st.download_button(
                "â¬‡ Descargar ranking final (.xlsx)",
                data=buffer.getvalue(),
                file_name="ranking_facilidad_entrada.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ---------------------------------------------------------------------------
# TAB 4 â€” HISTORIAL / APLICADAS
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Historial completo")
    st.caption(
        "Todas las ofertas que pasaron alguna vez por 'Preparar lotes', vengan de la corrida "
        "de hoy o de hace semanas. AcÃ¡ podÃ©s marcar aplicadas, agregar notas, o simplemente "
        "confirmar que algo ya fue procesado."
    )

    solo_aplicadas = st.checkbox("Mostrar solo las que ya marquÃ© como aplicadas", value=False)
    df_hist = db.get_historial(solo_aplicadas=solo_aplicadas)

    if df_hist.empty:
        st.info("TodavÃ­a no hay nada en el histÃ³rico. GenerÃ¡ lotes en la pestaÃ±a 2 primero.")
    else:
        busqueda = st.text_input("Buscar por tÃ­tulo o empresa")
        if busqueda:
            mask = (
                df_hist["titulo"].fillna("").str.contains(busqueda, case=False)
                | df_hist["empresa"].fillna("").str.contains(busqueda, case=False)
            )
            df_hist = df_hist[mask]

        df_hist_edit = df_hist.copy()
        df_hist_edit["aplicado"] = df_hist_edit["aplicado"].astype(bool)

        columnas_hist = [
            "id", "titulo", "empresa", "categoria", "score_total", "url",
            "fecha_primera_vista", "veces_vista", "aplicado", "fecha_aplicado", "notas",
        ]
        columnas_hist = [c for c in columnas_hist if c in df_hist_edit.columns]

        df_hist_editado = st.data_editor(
            df_hist_edit[columnas_hist],
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("Link oferta"),
                "aplicado": st.column_config.CheckboxColumn("Â¿Aplicado?"),
                "score_total": st.column_config.NumberColumn("Score", format="%.0f"),
            },
            disabled=[c for c in columnas_hist if c not in ("aplicado", "notas")],
            key="editor_historial",
        )

        if st.button("ðŸ’¾ Guardar cambios del historial"):
            db.actualizar_estado_bulk(df_hist_editado)
            st.success("Guardado.")
            st.rerun()

    st.divider()
    with st.expander("Mantenimiento del historial", expanded=False):
        st.caption(
            "Usa estas acciones cuando cambies el sistema de puntuacion o quieras reprocesar posiciones. "
            "Son acciones locales sobre `job_tracker.db`."
        )

        st.markdown("**Resetear puntuaciones**")
        st.caption(
            "Mantiene ofertas, aplicadas y notas, pero borra scores y razones. "
            "Para volver a generar lotes de ofertas ya vistas, marca en Lotes la opcion de incluir vistas anteriores."
        )
        confirm_reset = st.text_input(
            "Escribe RESET para borrar solo puntuaciones",
            key="confirm_reset_scores",
        )
        if st.button(
            "Resetear puntuaciones",
            disabled=confirm_reset != "RESET",
            type="secondary",
        ):
            filas = db.resetear_puntuaciones()
            st.session_state.resultados = {}
            st.session_state.df_final = None
            st.success(f"Puntuaciones reseteadas en {filas} ofertas.")
            st.rerun()

        st.divider()
        st.markdown("**Borrar historial completo**")
        st.caption(
            "Elimina todas las ofertas del historial. Despues de esto, las posiciones podran entrar como nuevas."
        )
        confirm_delete = st.text_input(
            "Escribe BORRAR HISTORIAL para eliminar todo",
            key="confirm_delete_history",
        )
        if st.button(
            "Borrar historial completo",
            disabled=confirm_delete != "BORRAR HISTORIAL",
        ):
            filas = db.borrar_historial()
            st.session_state.lotes = []
            st.session_state.resultados = {}
            st.session_state.df_filtrado = None
            st.session_state.df_final = None
            st.success(f"Historial eliminado: {filas} ofertas borradas.")
            st.rerun()
# ---------------------------------------------------------------------------
# TAB 5 â€” OPPORTUNITY RANKING
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("Opportunity Ranking")
    st.caption(
        "Structured, explainable ranking based on candidate profile, requirements, risk and application ROI. "
        f"Current version: `{RANKING_VERSION}`."
    )

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("Rank unranked jobs", type="primary", use_container_width=True):
            with st.spinner("Ranking unranked opportunities..."):
                summary = ranking_store.rank_unranked_jobs()
            st.success(" Â· ".join(f"{count} {decision}" for decision, count in summary.items()))
            st.rerun()
    with action_cols[1]:
        if st.button("Re-rank all jobs", use_container_width=True):
            with st.spinner("Re-ranking all stored opportunities..."):
                summary = ranking_store.rerank_all_jobs()
            st.success(" Â· ".join(f"{count} {decision}" for decision, count in summary.items()))
            st.rerun()
    with action_cols[2]:
        st.info("Rankings are stored in SQLite and versioned, so algorithm changes can be recalculated.")

    st.divider()
    filter_cols = st.columns([2, 1, 1, 1])
    with filter_cols[0]:
        decisions = st.multiselect(
            "Decision",
            ["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"],
            default=["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE"],
        )
    with filter_cols[1]:
        min_score = st.slider("Min score", 0, 100, 0, 5)
    with filter_cols[2]:
        sources_df = db.get_job_postings(limit=1000)
        available_sources = sorted(sources_df["source"].dropna().unique().tolist()) if not sources_df.empty else []
        sources = st.multiselect("Source", available_sources)
    with filter_cols[3]:
        flags_mode = st.selectbox("Red flags", ["Any", "With flags", "No flags"])

    with_red_flags = None
    if flags_mode == "With flags":
        with_red_flags = True
    elif flags_mode == "No flags":
        with_red_flags = False

    ranked = db.get_ranked_jobs(
        decisions=decisions or None,
        min_score=min_score,
        sources=sources or None,
        with_red_flags=with_red_flags,
    )

    if ranked.empty:
        unranked = db.get_unranked_jobs(limit=1)
        if unranked.empty:
            st.info("No scanner jobs found yet. Add ATS sources in Portal scanner and run a scan first.")
        else:
            st.info("Jobs exist but no ranking matches this view. Use Rank unranked jobs.")
    else:
        table = ranked[["job_id", "title", "company", "source", "location", "final_score", "decision", "confidence", "ranked_at"]].copy()
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "final_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
            },
        )

        st.markdown("### Ranking details")
        for _, row in ranked.iterrows():
            evidence = json.loads(row.get("evidence_json") or "{}")
            scores = json.loads(row.get("scores_json") or "{}")
            emphasize = json.loads(row.get("cv_keywords_to_emphasize_json") or "[]")
            avoid = json.loads(row.get("cv_keywords_to_avoid_overclaiming_json") or "[]")
            title = row.get("title") or "Untitled role"
            header = f"{int(row['final_score'])} Â· {row['company']} Â· {title}"
            with st.expander(header, expanded=False):
                st.markdown(render_decision_badge(row["decision"]), unsafe_allow_html=True)
                meta_cols = st.columns(4)
                with meta_cols[0]:
                    st.metric("Technical", scores.get("technical_fit", 0))
                with meta_cols[1]:
                    st.metric("Seniority", scores.get("seniority_fit", 0))
                with meta_cols[2]:
                    st.metric("Role", scores.get("role_fit", 0))
                with meta_cols[3]:
                    st.metric("Risk penalty", scores.get("risk_penalty", 0))

                st.markdown("**Why this score?**")
                st.write(row.get("reasoning_summary") or "No reasoning available.")
                st.markdown("**Recommended application angle**")
                st.write(row.get("recommended_application_angle") or "-")

                e_cols = st.columns(3)
                with e_cols[0]:
                    st.markdown("**Strong matches**")
                    st.write(evidence.get("strong_matches", []) or "-")
                    st.markdown("**Partial matches**")
                    st.write(evidence.get("partial_matches", []) or "-")
                with e_cols[1]:
                    st.markdown("**Missing requirements**")
                    st.write(evidence.get("missing_requirements", []) or "-")
                    st.markdown("**Dealbreakers**")
                    st.write(evidence.get("dealbreakers", []) or "-")
                with e_cols[2]:
                    st.markdown("**Red flags**")
                    st.write(evidence.get("red_flags", []) or "-")
                    st.markdown("**Nice-to-have matches**")
                    st.write(evidence.get("nice_to_have_matches", []) or "-")

                st.markdown("**CV keywords to emphasize**")
                st.write(emphasize or "-")
                st.markdown("**Do not overclaim**")
                st.write(avoid or "-")
                if row.get("url"):
                    st.link_button("Open posting", row["url"])
# ---------------------------------------------------------------------------
# TAB 6 â€” PORTAL SCANNER
# ---------------------------------------------------------------------------
with tab6:
    st.sidebar.markdown("### Scanner")
    scanner_view = st.sidebar.radio(
        "Workspace",
        ["Dashboard", "Sources", "Opportunity Inbox", "Job Detail"],
        label_visibility="collapsed",
        key="scanner_workspace",
    )

    st.subheader("Opportunity scanner")
    st.caption("Track official ATS sources, detect fresh roles, and keep a private local inbox of opportunities.")

    if scanner_view == "Dashboard":
        overview = db.get_scanner_overview()
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Tracked jobs", overview["total_jobs"])
        with c2:
            st.metric("New last scan", overview["last_scan_new"])
        with c3:
            st.metric("Updated last scan", overview["last_scan_updated"])
        with c4:
            st.metric("Enabled sources", overview["source_count"])

        scan_col, info_col = st.columns([1, 2])
        with scan_col:
            if st.button("Scan sources", type="primary", use_container_width=True):
                with st.spinner("Scanning enabled ATS sources..."):
                    results = asyncio.run(source_scanner.scan_enabled_sources())
                total_new = sum(len(result.new_jobs) for result in results)
                total_updated = sum(len(result.updated_jobs) for result in results)
                total_errors = sum(len(result.errors) for result in results)
                st.success(f"Scan complete: {total_new} new, {total_updated} updated, {total_errors} errors.")
                st.rerun()
        with info_col:
            last_scan = overview.get("last_scan") or "Never"
            st.info(f"Last scan: {last_scan}. Scans use public ATS APIs only; no login automation or auto-apply.")

        errors = db.get_recent_scan_errors(limit=5)
        if not errors.empty:
            st.markdown("### Recent errors")
            for _, row in errors.iterrows():
                st.markdown(
                    f"{render_badge('Error', 'error')} **{row['company_name']}** Â· {row['provider']} Â· {row['error']}",
                    unsafe_allow_html=True,
                )

        events = db.get_recent_scan_events(limit=10)
        if not events.empty:
            st.markdown("### Recent scans")
            st.dataframe(
                events[["company_name", "provider", "status", "found_count", "new_count", "updated_count", "finished_at"]],
                use_container_width=True,
                hide_index=True,
            )

    elif scanner_view == "Sources":
        st.markdown("### Sources")
        sources = db.list_company_sources()
        if sources.empty:
            st.info("No sources yet. Add your first Greenhouse, Lever, or Ashby board below.")
        else:
            display_sources = sources[[
                "id", "provider", "company_name", "company_ref", "enabled", "last_scan_at", "last_scan_status", "last_scan_error"
            ]].copy()
            display_sources["enabled"] = display_sources["enabled"].astype(bool)
            st.dataframe(display_sources, use_container_width=True, hide_index=True)

            scan_options = {
                f"{row['company_name']} Â· {row['provider']} Â· {row['company_ref']}": row
                for row in sources.to_dict("records")
            }
            selected_label = st.selectbox("Scan one source", list(scan_options.keys()))
            if st.button("Scan selected source", type="primary"):
                selected = scan_options[selected_label]
                with st.spinner(f"Scanning {selected['company_name']}..."):
                    result = asyncio.run(source_scanner.scan_source_row(selected))
                if result.errors:
                    st.error(result.errors[0])
                else:
                    st.success(
                        f"{result.company_name}: {len(result.new_jobs)} new, "
                        f"{len(result.updated_jobs)} updated, {len(result.unchanged_jobs)} unchanged."
                    )
                st.rerun()

        st.divider()
        st.markdown("### Add source")
        with st.form("add_company_source", clear_on_submit=True):
            provider = st.selectbox("Provider", sorted(PROVIDERS.keys()))
            company_name = st.text_input("Company name", placeholder="Anthropic")
            company_ref = st.text_input("Company ref", placeholder="anthropic")
            enabled = st.checkbox("Enabled", value=True)
            submitted = st.form_submit_button("Add source", type="primary")
            if submitted:
                if not company_name.strip() or not company_ref.strip():
                    st.error("Company name and company ref are required.")
                else:
                    db.add_company_source(provider, company_name.strip(), company_ref.strip(), enabled)
                    st.success("Source saved.")
                    st.rerun()

    elif scanner_view == "Opportunity Inbox":
        st.markdown("### Opportunity Inbox")
        status_filter = st.multiselect(
            "Show statuses",
            ["new", "updated", "seen", "shortlisted", "applied", "discarded"],
            default=["new", "updated"],
        )
        scan_statuses = [status for status in status_filter if status in {"new", "updated", "seen"}]
        jobs = db.get_job_postings(statuses=scan_statuses or None, limit=100)
        if not jobs.empty and any(status in {"shortlisted", "applied", "discarded"} for status in status_filter):
            jobs = jobs[
                jobs["pipeline_status"].isin([status for status in status_filter if status in {"shortlisted", "applied", "discarded"}])
                | jobs["status"].isin(scan_statuses)
            ]

        if jobs.empty:
            st.info("No opportunities match this view yet. Add sources and run a scan.")
        else:
            for _, row in jobs.iterrows():
                data = row.to_dict()
                render_job_card(data)
                action_cols = st.columns([1, 1, 1, 1, 3])
                with action_cols[0]:
                    if data.get("url"):
                        st.link_button("Open", data["url"], use_container_width=True)
                with action_cols[1]:
                    if st.button("Shortlist", key=f"shortlist_{data['id']}", use_container_width=True):
                        db.update_job_status(int(data["id"]), "shortlisted")
                        st.rerun()
                with action_cols[2]:
                    if st.button("Applied", key=f"applied_{data['id']}", use_container_width=True):
                        db.update_job_status(int(data["id"]), "applied")
                        st.rerun()
                with action_cols[3]:
                    if st.button("Discard", key=f"discard_{data['id']}", use_container_width=True):
                        db.update_job_status(int(data["id"]), "discarded")
                        st.rerun()
                with action_cols[4]:
                    if st.button("View detail", key=f"detail_{data['id']}", use_container_width=True):
                        st.session_state.selected_scanner_job_id = int(data["id"])
                        st.info("Open the Job Detail view from the scanner sidebar to inspect this opportunity.")

    elif scanner_view == "Job Detail":
        jobs = db.get_job_postings(limit=500)
        if jobs.empty:
            st.info("No jobs stored yet.")
        else:
            options = {
                f"{row['title'] or 'Untitled'} Â· {row['company']} Â· {row['source']} Â· #{row['id']}": int(row["id"])
                for _, row in jobs.iterrows()
            }
            default_id = st.session_state.get("selected_scanner_job_id")
            labels = list(options.keys())
            default_index = 0
            if default_id:
                for i, label in enumerate(labels):
                    if options[label] == default_id:
                        default_index = i
                        break
            selected = st.selectbox("Select opportunity", labels, index=default_index)
            job = db.get_job_posting(options[selected])
            if job:
                st.markdown(f"### {job.get('title') or 'Untitled role'}")
                st.markdown(
                    f"{render_badge((job.get('status') or 'seen').title(), job.get('status') or 'seen')} "
                    f"{render_badge((job.get('pipeline_status') or 'Untriaged').title(), job.get('pipeline_status') or 'neutral')}",
                    unsafe_allow_html=True,
                )
                meta_cols = st.columns(4)
                with meta_cols[0]:
                    st.metric("Company", job.get("company") or "-")
                with meta_cols[1]:
                    st.metric("Source", job.get("source") or "-")
                with meta_cols[2]:
                    st.metric("Seen", job.get("times_seen") or 0)
                with meta_cols[3]:
                    st.metric("Active", "Yes" if job.get("is_active") else "No")

                link_cols = st.columns(2)
                with link_cols[0]:
                    if job.get("url"):
                        st.link_button("Open posting", job["url"], use_container_width=True)
                with link_cols[1]:
                    if job.get("apply_url"):
                        st.link_button("Apply URL", job["apply_url"], use_container_width=True)

                st.markdown("### Description")
                st.write(job.get("description_text") or "No clean description available.")

                st.markdown("### Tracking")
                st.dataframe(
                    pd.DataFrame([
                        {
                            "external_id": job.get("external_id"),
                            "first_seen_at": job.get("first_seen_at"),
                            "last_seen_at": job.get("last_seen_at"),
                            "content_hash": job.get("content_hash"),
                        }
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("Debug: raw provider payload", expanded=False):
                    try:
                        st.json(json.loads(job.get("raw_payload") or "{}"))
                    except json.JSONDecodeError:
                        st.code(job.get("raw_payload") or "")

