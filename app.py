"""
Job Orchestrator — UI local para tu pipeline de búsqueda de empleo.

Corre con:
    streamlit run app.py

IMPORTANTE: el scraping SIGUE corriendo en local, con tu sesión real de LinkedIn
y un navegador visible. Esta UI solo lo orquesta como subproceso; no automatiza
aplicar a ofertas ni enviar mensajes (eso sigue fuera de alcance a propósito).
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
from joborchestrator.scanning import portals as scan_portals
from joborchestrator.intelligence import trust_validator
from joborchestrator.intelligence import archetype_detector
from joborchestrator.intelligence import repost_detector
from joborchestrator.intelligence import evaluation_framework
from joborchestrator.intelligence import cover_letter_generator
from joborchestrator.intelligence import ats_autofill

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
            background:#ff4b4b;color:white;cursor:pointer">
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
                status.textContent = `Abiertas ${{opened}}/${{lots.length}} pestañas. Si falta alguna, permite popups.`;
              }}, index * 250);
            }});
          }});
        </script>
        """,
        height=46,
    )

st.title("🎯 Job Orchestrator")
st.caption("Scraping → lotes para IA → consolidación de ranking. Todo corre en tu máquina.")

_stats = db.stats_generales()
st.caption(
    f"📊 Histórico: {_stats['total_vistas']} ofertas vistas alguna vez · "
    f"{_stats['con_score']} ya puntuadas · {_stats['aplicadas']} marcadas como aplicadas"
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["1️⃣ Scraping", "2️⃣ Preparar lotes", "3️⃣ Consolidar ranking", "4️⃣ Historial / Aplicadas", "5️⃣ Portal Scanner"]
)

# ---------------------------------------------------------------------------
# TAB 1 — SCRAPING
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Lanzar el scraper")
    st.markdown(
        "Esto ejecuta el scraper de LinkedIn en un proceso aparte. "
        "Se abrirá un navegador real donde tendrás que loguearte a mano la primera vez "
        "(igual que corriéndolo directo por consola). **Esta pestaña solo lanza y muestra logs — "
        "no cambia nada de cómo scrapea.**"
    )

    if not LINKEDIN_SCRAPER.exists():
        st.error("No encuentro el scraper de LinkedIn dentro de `joborchestrator/scanning/`.")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            lanzar = st.button("▶ Iniciar scraping", type="primary")
        with col2:
            st.info("Alternativa: corre `python -m joborchestrator.scanning.linkedin` en tu terminal, "
                    "y usa solo las pestañas 2 y 3 de aquí.")

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
            with st.spinner("Scraping en curso... revisa el navegador que se abrió."):
                for linea in proceso.stdout:
                    logs.append(linea.rstrip())
                    log_box.code("\n".join(logs[-40:]), language="text")
                proceso.wait()

            if proceso.returncode == 0:
                st.success("Scraping terminado. Ve a la pestaña 2 para preparar los lotes.")
            else:
                st.warning(f"El proceso terminó con código {proceso.returncode}. Revisa el log arriba.")

    st.divider()
    st.markdown("**Archivos de salida encontrados:**")
    if SALIDAS_DIR.exists():
        excels = sorted(SALIDAS_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if excels:
            for p in excels[:5]:
                st.text(f"📄 {p.name}")
        else:
            st.text("Aún no hay .xlsx en salidas_todas_posiciones_raw/")
    else:
        st.text("Todavía no existe la carpeta de salidas (corre el scraper primero).")

# ---------------------------------------------------------------------------
# TAB 2 — PREPARAR LOTES
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Cargar Excel y generar lotes")

    origen = st.radio(
        "¿De dónde saco el Excel?",
        ["Usar el más reciente de salidas_todas_posiciones_raw/", "Subir un archivo"],
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
                st.warning("No hay ningún .xlsx todavía. Sube uno manualmente.")
        else:
            st.warning("No existe la carpeta de salidas todavía. Sube un archivo manualmente.")
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
                "Longitud mínima de descripción (filtra basura)",
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
                f"Original: **{stats['original']}** → tras duplicados: **{stats['tras_duplicados']}** "
                f"→ tras extracción OK: **{stats['tras_extraccion_ok']}** "
                f"→ tras descripción mínima: **{stats['tras_descripcion_minima']}** "
                f"→ tras excluir ya vistas antes: **{n_despues_dedup}** "
                f"({n_antes_dedup - n_despues_dedup} descartadas por repetidas)"
            )

            if df_filtrado.empty:
                st.warning("No quedó ninguna oferta nueva tras deduplicar. "
                           "Si querés reprocesarlas igual, marcá la casilla de arriba.")
            else:
                lotes = generar_lotes(df_filtrado, filas_por_lote=filas_por_lote, perfil_candidato=perfil)
                st.session_state.lotes = lotes
                # Registra en el histórico apenas se generan lotes, así una corrida
                # posterior en la misma semana ya no las vuelve a traer aunque no
                # llegues a consolidar el ranking.
                db.registrar_ofertas_vistas(df_filtrado)
                st.success(f"{len(lotes)} lotes generados. Bajá para copiarlos uno por uno.")

    if st.session_state.lotes:
        st.divider()
        st.markdown(f"### {len(st.session_state.lotes)} lotes listos")
        st.caption("Abrí una conversación NUEVA en Claude.ai o ChatGPT por cada lote, pega el contenido, "
                   "y guardá la tabla de respuesta para la pestaña 3.")

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
            with st.expander(f"Lote {lote['numero']:02d} — {lote['categoria']} ({lote['n_filas']} ofertas)"):
                st.link_button(
                    "Abrir este lote en ChatGPT",
                    build_chatgpt_url(lote["prompt"]),
                )
                st.code(lote["prompt"], language="text")

# ---------------------------------------------------------------------------
# TAB 3 — CONSOLIDAR
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Pegar respuestas de la IA y consolidar")

    if not st.session_state.lotes:
        st.info("Primero generá los lotes en la pestaña 2.")
    else:
        nombres_lotes = [f"{l['numero']:02d} — {l['categoria']} ({l['n_filas']} ofertas)" for l in st.session_state.lotes]
        seleccion = st.selectbox("¿Qué lote estás pegando?", nombres_lotes)
        idx = nombres_lotes.index(seleccion)
        lote_actual = st.session_state.lotes[idx]

        respuesta_texto = st.text_area(
            "Pegá aquí la tabla que te devolvió Claude/ChatGPT para este lote",
            height=250,
            key=f"resp_{lote_actual['nombre']}",
        )

        if st.button("Guardar este lote"):
            df_parsed = parsear_tabla_respuesta(respuesta_texto)
            if df_parsed.empty:
                st.error("No pude parsear ninguna fila. Revisá que hayas pegado la tabla completa con el separador '|'.")
            else:
                st.session_state.resultados[lote_actual["nombre"]] = df_parsed
                st.success(f"Guardado: {len(df_parsed)} filas parseadas.")
                st.dataframe(df_parsed, use_container_width=True)

        st.divider()
        guardados = list(st.session_state.resultados.keys())
        st.markdown(f"**Lotes guardados: {len(guardados)} / {len(st.session_state.lotes)}**")
        for nombre in guardados:
            st.text(f"✅ {nombre}")

        if guardados:
            if st.button("🔗 Consolidar ranking final", type="primary"):
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
                # queden visibles en la pestaña de Historial.
                db.guardar_scores(df_final)

                st.session_state.df_final = df_final
                st.success(f"Ranking final: {len(df_final)} ofertas. Scores guardados en el histórico.")

        if "df_final" in st.session_state:
            st.markdown("### Ranking final — marcá acá directamente las que ya aplicaste")
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
                    "aplicado": st.column_config.CheckboxColumn("¿Aplicado?"),
                    "SCORE_TOTAL": st.column_config.NumberColumn("Score", format="%.0f"),
                },
                disabled=[c for c in columnas_visibles if c not in ("aplicado", "notas")],
                key="editor_ranking_final",
            )

            if st.button("💾 Guardar estado de 'aplicado' en el histórico"):
                db.actualizar_estado_bulk(df_editado)
                st.success("Estado guardado. Ya no hace falta que las vuelvas a ver la próxima semana.")

            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_editado.to_excel(writer, index=False, sheet_name="Ranking")
            st.download_button(
                "⬇ Descargar ranking final (.xlsx)",
                data=buffer.getvalue(),
                file_name="ranking_facilidad_entrada.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ---------------------------------------------------------------------------
# TAB 4 — HISTORIAL / APLICADAS
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Historial completo")
    st.caption(
        "Todas las ofertas que pasaron alguna vez por 'Preparar lotes', vengan de la corrida "
        "de hoy o de hace semanas. Acá podés marcar aplicadas, agregar notas, o simplemente "
        "confirmar que algo ya fue procesado."
    )

    solo_aplicadas = st.checkbox("Mostrar solo las que ya marqué como aplicadas", value=False)
    df_hist = db.get_historial(solo_aplicadas=solo_aplicadas)

    if df_hist.empty:
        st.info("Todavía no hay nada en el histórico. Generá lotes en la pestaña 2 primero.")
    else:
        busqueda = st.text_input("Buscar por título o empresa")
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
                "aplicado": st.column_config.CheckboxColumn("¿Aplicado?"),
                "score_total": st.column_config.NumberColumn("Score", format="%.0f"),
            },
            disabled=[c for c in columnas_hist if c not in ("aplicado", "notas")],
            key="editor_historial",
        )

        if st.button("💾 Guardar cambios del historial"):
            db.actualizar_estado_bulk(df_hist_editado)
            st.success("Guardado.")
            st.rerun()

# ---------------------------------------------------------------------------
# TAB 5 — PORTAL SCANNER
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("🔍 Portal Scanner — Búsqueda Automatizada de Ofertas")
    st.markdown(
        "Escanea múltiples plataformas (Greenhouse, Ashby, Lever, etc.) automáticamente. "
        "Career-Ops inspired multi-level discovery."
    )

    st.markdown("### 🧠 Evaluación A-F y ayuda de candidatura")
    st.caption("Ahora puedes evaluar una oferta, preparar un cover letter más estructurado y generar un plan de autofill para ATS compatibles.")

    with st.expander("1) Evaluación A-F estructurada", expanded=False):
        af_job_title = st.text_input("Título de la oferta", value="Senior Python Backend Engineer")
        af_company = st.text_input("Empresa", value="Anthropic")
        af_desc = st.text_area("Descripción / JD", height=120, value="Build scalable APIs with Python, FastAPI, PostgreSQL and AWS. Lead backend architecture and mentor engineers.")
        af_profile = st.text_area("Perfil del candidato", height=100, value="Backend engineer with Python, FastAPI, PostgreSQL, AWS, and mentoring experience.")
        if st.button("Generar evaluación A-F"):
            af_result = evaluation_framework.build_af_evaluation(
                {"title": af_job_title, "company": af_company, "description": af_desc},
                af_profile,
            )
            st.json(af_result)

    with st.expander("2) Cover Letter Generator avanzado", expanded=False):
        cl_title = st.text_input("Título para cover letter", value="Senior Backend Engineer")
        cl_company = st.text_input("Empresa", value="Acme Labs")
        cl_desc = st.text_area("Descripción de la oferta", height=100, value="Build reliable APIs, optimize performance, work with Python and distributed systems.")
        cl_profile = st.text_area("Perfil para el cover", height=100, value="I am a backend engineer with Python, system design and mentoring experience.")
        cl_tone = st.selectbox("Tono", ["confident", "warm"], index=0)
        if st.button("Preparar cover letter"):
            payload = cover_letter_generator.build_cover_letter_payload(
                {"title": cl_title, "company": cl_company, "description": cl_desc},
                cl_profile,
            )
            draft = cover_letter_generator.build_professional_cover_letter(
                {"title": cl_title, "company": cl_company, "description": cl_desc},
                cl_profile,
                tone=cl_tone,
            )
            st.session_state.cover_draft = draft
            st.text_area("Draft editable", value=draft, height=220, key="cover_draft_editor")
            st.json(payload)
            if st.button("Exportar PDF", key="export_cover_pdf"):
                out_path = BASE_DIR / "salida_cover_letter.pdf"
                ok = cover_letter_generator.export_cover_letter_pdf(st.session_state.cover_draft, out_path)
                if ok:
                    st.success(f"PDF generado en {out_path}")
                    with open(out_path, "rb") as f:
                        st.download_button("Descargar PDF", f.read(), file_name="cover_letter.pdf", mime="application/pdf")
            if st.button("Guardar plantilla por empresa", key="save_company_template"):
                st.session_state.saved_templates = st.session_state.get("saved_templates", {})
                st.session_state.saved_templates[cl_company] = {
                    "title": cl_title,
                    "company": cl_company,
                    "draft": st.session_state.cover_draft,
                }
                st.success(f"Plantilla guardada para {cl_company}")

        saved_templates = st.session_state.get("saved_templates", {})
        if saved_templates:
            st.caption("Plantillas guardadas")
            for company, data in saved_templates.items():
                with st.expander(company):
                    st.text(data["draft"])

    with st.expander("3) Application Auto-Fill", expanded=False):
        autofill_title = st.text_input("Título de la oferta para autofill", value="Product Engineer")
        autofill_company = st.text_input("Empresa para autofill", value="GreenTech")
        autofill_desc = st.text_area("Descripción breve del puesto", height=100, value="Build internal tools, collaborate with product, scale frontend and backend systems.")
        autofill_ats = st.selectbox("ATS compatible", ["greenhouse", "ashby", "lever"], index=0)
        autofill_variant = st.radio("Versión de respuestas", ["corta", "larga"], horizontal=True)
        if st.button("Generar plan de autofill"):
            plan = ats_autofill.build_autofill_plan(
                {"title": autofill_title, "company": autofill_company, "description": autofill_desc},
                ats_type=autofill_ats,
            )
            if autofill_variant == "corta":
                plan["form_responses"] = [
                    {k: v for k, v in item.items() if k != "answer"}
                    | {"answer": item["answer"][:220]}
                    for item in plan["form_responses"]
                ]
            st.json(plan)
    
    # Load config
    config = scan_portals.load_portals_config()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Empresas configuradas", len(config.get("tracked_companies", [])))
    with col2:
        st.metric("Queries de búsqueda", len(config.get("search_queries", [])))
    
    st.divider()
    st.markdown("### 🚀 Ejecutar Scan")
    
    # Selector de validaciones
    col_val1, col_val2, col_val3 = st.columns(3)
    with col_val1:
        enable_trust = st.checkbox("✅ Trust Validator", value=True, help="Detecta scams y ghost jobs")
    with col_val2:
        enable_archetype = st.checkbox("🏷️ Archetype Detection", value=True, help="Clasifica tipo de rol")
    with col_val3:
        enable_repost = st.checkbox("🔁 Repost Detection", value=True, help="Detecta ofertas republicadas")
    
    if st.button("▶ Iniciar escaneo de portales", type="primary", key="scan_button"):
        with st.spinner("Escaneando portales... esto puede tomar 1-2 minutos..."):
            try:
                result = asyncio.run(scan_portals.run_full_scan(config))
                
                st.success("✅ Escaneo completado")
                
                # Show report
                st.code(result["report"])
                
                # Show new jobs
                if result["new_jobs"]:
                    jobs_to_process = result["new_jobs"]
                    
                    # Apply Trust Validator
                    if enable_trust:
                        st.markdown("#### 🛡️ Trust Validation")
                        trust_result = scan_portals.apply_trust_validation(jobs_to_process)
                        
                        trust_cols = st.columns(3)
                        with trust_cols[0]:
                            st.metric("✅ Safe", trust_result["stats"]["safe_count"], help="Score ≥ 70")
                        with trust_cols[1]:
                            st.metric("⚠️ Warning", trust_result["stats"]["warning_count"], help="40-70")
                        with trust_cols[2]:
                            st.metric("🚨 Danger", trust_result["stats"]["danger_count"], help="Score < 40")
                        
                        # Filter to only safe/warning jobs
                        jobs_to_process = trust_result["safe"] + trust_result["warning"]
                        
                        if trust_result["danger"]:
                            with st.expander(f"🚨 {len(trust_result['danger'])} Ofertas peligrosas (filtradas)"):
                                for job in trust_result["danger"]:
                                    trust_info = job["trust_validation"]
                                    st.warning(f"**{job.get('title')}** @ {job.get('company')}")
                                    st.caption(trust_info["recommendation"])
                    
                    # Apply Archetype Detection
                    if enable_archetype:
                        st.markdown("#### 🏷️ Role Classification")
                        arch_result = scan_portals.apply_archetype_detection(jobs_to_process)
                        
                        # Show distribution
                        dist = arch_result["stats"]["distribution"]
                        if dist:
                            dist_cols = st.columns(min(3, len(dist)))
                            for i, (arch, count) in enumerate(sorted(dist.items())):
                                with dist_cols[i % len(dist_cols)]:
                                    st.metric(arch.title(), count)
                        
                        # Add archetype info to jobs
                        for job in jobs_to_process:
                            job["archetype_info"] = job.get("archetype_detection", {})
                    
                    # Apply Repost Detection
                    if enable_repost:
                        st.markdown("#### 🔁 Repost Detection")
                        repost_result = scan_portals.apply_repost_detection(jobs_to_process)
                        
                        repost_cols = st.columns(3)
                        with repost_cols[0]:
                            st.metric("🆕 Unique", repost_result["stats"]["unique_count"])
                        with repost_cols[1]:
                            st.metric("👑 Master", repost_result["stats"]["master_count"])
                        with repost_cols[2]:
                            st.metric("🔁 Duplicates (filtered)", repost_result["stats"]["repost_count"])
                        
                        # Filter to only unique + master
                        jobs_final = repost_result["unique"] + repost_result["masters"]
                    else:
                        jobs_final = jobs_to_process
                    
                    st.markdown(f"### 📋 {len(jobs_final)} ofertas después de validaciones")
                    
                    df_preview = pd.DataFrame([
                        {
                            "Empresa": j.get("company", ""),
                            "Título": j.get("title", ""),
                            "Ubicación": j.get("location", ""),
                            "Archetype": j.get("archetype_info", {}).get("primary_archetype", "-"),
                            "Trust": f"{j.get('trust_validation', {}).get('trust_score', '-')}" if enable_trust else "-",
                            "URL": j.get("url", ""),
                        }
                        for j in jobs_final
                    ])
                    
                    st.dataframe(
                        df_preview,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "URL": st.column_config.LinkColumn("Link"),
                        }
                    )
                    
                    if st.button("📥 Importar a 'Preparar lotes'"):
                        # Convert to DataFrame format similar to Excel import
                        df_import = pd.DataFrame([
                            {
                                "id": j.get("job_id", ""),
                                "titulo": j.get("title", ""),
                                "empresa": j.get("company", ""),
                                "ubicacion": j.get("location", ""),
                                "url": j.get("url", ""),
                                "descripcion": "",  # Would need to fetch full JD
                                "modalidad": "Remoto" if "remote" in j.get("title", "").lower() else "Presencial",
                                "categoria": "imported_from_scan",
                                "extraccion_ok": True,
                            }
                            for j in jobs_final
                        ])
                        
                        st.session_state.df_import_scan = df_import
                        st.success(f"✅ {len(df_import)} ofertas preparadas para lotes")
                else:
                    st.info("No se encontraron nuevas ofertas (todos duplicados o filtrados)")
                    
            except Exception as e:
                st.error(f"❌ Error durante el escaneo: {e}")
                import traceback
                st.code(traceback.format_exc())
    
    st.divider()
    st.markdown("### ⚙️ Configuración")
    
    if st.checkbox("Mostrar portals.yml", value=False):
        st.code(open("portals.yml").read(), language="yaml")
    
    if st.button("🔄 Recargar configuración"):
        st.rerun()
    
    st.divider()
    st.markdown("### 📊 Historial de Scans")
    
    scan_history = scan_portals.get_scan_history_df()
    if not scan_history.empty:
        # Show last 50 scans
        scan_history_recent = scan_history.tail(50)
        st.dataframe(
            scan_history_recent,
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("URL"),
                "first_seen": st.column_config.TextColumn("Fecha"),
            }
        )
        
        # Statistics
        stats_cols = st.columns(4)
        with stats_cols[0]:
            st.metric("Total vistas", len(scan_history))
        with stats_cols[1]:
            added = len(scan_history[scan_history["status"] == "added"])
            st.metric("Agregadas", added)
        with stats_cols[2]:
            duplicates = len(scan_history[scan_history["status"] == "skipped_dup"])
            st.metric("Duplicadas", duplicates)
        with stats_cols[3]:
            expired = len(scan_history[scan_history["status"] == "skipped_expired"])
            st.metric("Expiradas", expired)
    else:
        st.info("Aún sin historial de scans.")
