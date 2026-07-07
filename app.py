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
import asyncio
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from joborchestrator.batching import (
    filtrar_ofertas,
    MIN_DESCRIPCION_LEN_DEFAULT,
)
from joborchestrator.intelligence.llm_application_materials import (
    DEFAULT_MATERIALS_MODEL,
    LLMMaterialsError,
    build_application_kit_with_llm,
    estimate_materials_cost,
    export_ats_cv_docx_bytes,
)
from joborchestrator.paths import LINKEDIN_SCRAPER, PROJECT_ROOT, SALIDAS_DIR
from joborchestrator.storage import persistence as db
from joborchestrator.intelligence.application_materials import build_application_kit
from joborchestrator.scanning import scanner as source_scanner
from joborchestrator.scanning.linkedin_importer import import_linkedin_dataframe_to_job_postings
from joborchestrator.scanning.providers import PROVIDERS
from joborchestrator.scanning import search_scanner
from joborchestrator.scanning.search_providers import SEARCH_PROVIDERS, provider_requires_configuration
from joborchestrator.ranking.manual_llm_review import (
    ranking_from_storage_row,
)
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MODEL,
    NvidiaRankingError,
    nvidia_api_key,
    rank_jobs_with_nvidia,
)
from joborchestrator.ranking.speed_ranker import SPEED_RANKING_VERSION

db.init_db()

BASE_DIR = PROJECT_ROOT

st.set_page_config(page_title="Job Orchestrator", layout="wide")

if "df_filtrado" not in st.session_state:
    st.session_state.df_filtrado = None


def open_tracked_job_link(label: str, url: str, job_id: int, key: str, use_container_width: bool = True) -> None:
    if st.button(label, key=key, use_container_width=use_container_width):
        db.registrar_job_posting_abierta(job_id)
        safe_url = json.dumps(url)
        components.html(
            f"""
            <script>
              window.open({safe_url}, "_blank", "noopener,noreferrer");
            </script>
            <a href={safe_url} target="_blank" rel="noopener noreferrer">Open link</a>
            """,
            height=24,
        )
        st.caption("Added to Historial.")


def parse_json_cell(value, default):
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def copy_text_button(text: str, key: str, label: str) -> None:
    button_id = f"copy_{key}".replace("-", "_").replace(" ", "_")
    safe_text = json.dumps(text or "")
    components.html(
        f"""
        <button id="{button_id}" style="
            width:100%;
            border:1px solid #e5e7eb;
            border-radius:8px;
            padding:9px 12px;
            background:#ffffff;
            color:#111827;
            font-weight:650;
            cursor:pointer;
        ">{label}</button>
        <script>
          const btn = document.getElementById("{button_id}");
          btn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText({safe_text});
              btn.textContent = "Copied";
            }} catch (err) {{
              btn.textContent = "Copy failed";
            }}
          }});
        </script>
        """,
        height=44,
    )


RANKING_ACTIONS = [
    "Generate application kit",
    "Edit application kit",
    "Inspect ranking evidence",
    "Open posting",
    "Open apply page",
    "Prep apply pack",
    "Mark shortlisted",
    "Mark discarded",
    "Mark applied",
]


def render_ranking_action_toolbar(job_id: int, default_action: str) -> str:
    state_key = f"ranking_selected_action_{job_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = default_action

    st.markdown("**Actions**")
    first_row = st.columns(3)
    second_row = st.columns(5)
    action_slots = [
        (first_row[0], "Generate application kit", "Kit"),
        (first_row[1], "Edit application kit", "Edit/copy kit"),
        (first_row[2], "Prep apply pack", "Local draft"),
        (second_row[0], "Open apply page", "Apply page"),
        (second_row[1], "Open posting", "Posting"),
        (second_row[2], "Mark applied", "Applied"),
        (second_row[3], "Mark discarded", "Discard"),
        (second_row[4], "Inspect ranking evidence", "Evidence"),
    ]
    for column, action, label in action_slots:
        with column:
            button_type = "primary" if st.session_state[state_key] == action else "secondary"
            if st.button(label, key=f"action_{job_id}_{action}", type=button_type, use_container_width=True):
                st.session_state[state_key] = action
                st.rerun()
    return st.session_state[state_key]


def render_saved_application_shortcuts(row, job_id: int, prefix: str) -> None:
    has_materials = any(
        str(row.get(field) or "").strip()
        for field in ["recruiter_message", "cover_letter", "ats_cv_text", "autofill_notes"]
    )
    if not has_materials:
        return

    st.markdown("**Saved kit shortcuts**")
    copy_cols = st.columns(4)
    with copy_cols[0]:
        copy_text_button(row.get("recruiter_message") or "", f"{prefix}_recruiter_{job_id}", "Copy recruiter msg")
    with copy_cols[1]:
        copy_text_button(row.get("cover_letter") or "", f"{prefix}_cover_{job_id}", "Copy cover letter")
    with copy_cols[2]:
        copy_text_button(row.get("ats_cv_text") or "", f"{prefix}_ats_{job_id}", "Copy ATS notes")
    with copy_cols[3]:
        copy_text_button(row.get("autofill_notes") or "", f"{prefix}_autofill_{job_id}", "Copy autofill")

    link_cols = st.columns(2)
    with link_cols[0]:
        if row.get("apply_url"):
            open_tracked_job_link("Open apply page", row["apply_url"], job_id, key=f"{prefix}_open_apply_{job_id}")
    with link_cols[1]:
        if row.get("url"):
            open_tracked_job_link("Open posting", row["url"], job_id, key=f"{prefix}_open_posting_{job_id}")


def render_ranking_action_panel(row, selected_action: str) -> None:
    evidence = parse_json_cell(row.get("evidence_json"), {})
    scores = parse_json_cell(row.get("scores_json"), {})
    emphasize = parse_json_cell(row.get("cv_keywords_to_emphasize_json"), [])
    avoid = parse_json_cell(row.get("cv_keywords_to_avoid_overclaiming_json"), [])
    job_id = int(row["job_id"])
    title = row.get("title") or "Untitled role"
    company = row.get("company") or "Unknown"
    baseline_ranking = ranking_from_storage_row(row.to_dict() if hasattr(row, "to_dict") else dict(row))

    st.markdown(f"### {company} · {title}")
    badges = render_decision_badge(row["decision"])
    st.markdown(badges, unsafe_allow_html=True)

    meta_cols = st.columns(5)
    with meta_cols[0]:
        st.metric("Score", int(row["final_score"]))
    with meta_cols[1]:
        st.metric("Technical", scores.get("technical_fit", 0))
    with meta_cols[2]:
        st.metric("Role", scores.get("role_fit", 0))
    with meta_cols[3]:
        st.metric("Confidence", f"{float(row.get('confidence') or 0):.2f}")
    with meta_cols[4]:
        st.metric("Risk", scores.get("risk_penalty", 0))

    if selected_action == "Prep apply pack":
        st.markdown("**Prep apply pack**")
        st.caption("One click creates local draft materials, marks the job as shortlisted, and gives you copy/open actions.")
        existing_has_kit = any(
            str(row.get(field) or "").strip()
            for field in ["recruiter_message", "cover_letter", "ats_cv_text", "autofill_notes"]
        )
        if st.button(
            "Prepare pack and shortlist",
            key=f"prep_pack_{job_id}",
            type="primary",
            use_container_width=True,
        ):
            kit = build_application_kit(row.to_dict() if hasattr(row, "to_dict") else dict(row), emphasize)
            db.update_job_application_materials(
                job_id,
                pipeline_status="shortlisted",
                recruiter_message=kit["recruiter_message"],
                cover_letter=kit["cover_letter"],
                ats_cv_text=kit["ats_cv_text"],
                autofill_notes=kit["autofill_notes"],
            )
            st.success("Apply pack prepared and job shortlisted.")
            st.rerun()

        if existing_has_kit:
            st.info("This job already has saved materials. Use the copy buttons below or open Edit kit.")
            render_saved_application_shortcuts(row, job_id, "prep")

    elif selected_action == "Generate application kit":
        st.markdown("**Application kit**")
        st.caption("Generate materials with API and save them locally. Nothing is submitted automatically.")
        render_saved_application_shortcuts(row, job_id, "gptkit_saved")
        api_key_configured = bool(os.getenv("OPENAI_API_KEY"))
        api_cols = st.columns([1, 1, 2])
        with api_cols[0]:
            materials_model = st.text_input(
                "Materials model",
                value=DEFAULT_MATERIALS_MODEL,
                key=f"materials_model_{job_id}",
                disabled=not api_key_configured,
            )
        with api_cols[1]:
            estimated_materials_cost = estimate_materials_cost(1, model=materials_model)
            st.metric("Est. API cost", f"${estimated_materials_cost:.3f}")
        with api_cols[2]:
            if not api_key_configured:
                st.warning("Set `OPENAI_API_KEY` to generate the application kit automatically.")
            else:
                st.info("Generates recruiter message, cover letter, ATS CV and autofill notes. Nothing is submitted.")

        if st.button(
            "Generate kit with OpenAI API",
            key=f"api_kit_review_{job_id}",
            type="primary",
            use_container_width=True,
            disabled=not api_key_configured,
        ):
            try:
                kit = build_application_kit_with_llm(
                    row.to_dict() if hasattr(row, "to_dict") else dict(row),
                    baseline_ranking,
                    model=materials_model,
                )
                db.update_job_application_materials(job_id, pipeline_status="shortlisted", **kit)
                st.success("Application kit generated with API and saved.")
                st.session_state[f"ranking_selected_action_{job_id}"] = "Edit application kit"
                st.rerun()
            except LLMMaterialsError as exc:
                st.error(str(exc))

    elif selected_action == "Edit application kit":
        st.markdown("**Application kit**")
        default_status = row.get("pipeline_status") or "unreviewed"
        status_options = ["unreviewed", "shortlisted", "discarded", "applied"]
        if default_status not in status_options:
            status_options.insert(0, default_status)
        kit_key = f"kit_{job_id}"
        if st.button("Generate local draft kit", key=f"generate_{kit_key}"):
            kit = build_application_kit(row.to_dict() if hasattr(row, "to_dict") else dict(row), emphasize)
            st.session_state[f"{kit_key}_recruiter_message"] = kit["recruiter_message"]
            st.session_state[f"{kit_key}_cover_letter"] = kit["cover_letter"]
            st.session_state[f"{kit_key}_ats_cv_text"] = kit["ats_cv_text"]
            st.session_state[f"{kit_key}_autofill_notes"] = kit["autofill_notes"]

        selected_status = st.selectbox(
            "Pipeline status",
            status_options,
            index=status_options.index(default_status),
            key=f"{kit_key}_status",
        )
        recruiter_message = st.text_area(
            "Recruiter message",
            value=st.session_state.get(f"{kit_key}_recruiter_message", row.get("recruiter_message") or ""),
            height=110,
            key=f"{kit_key}_recruiter_message",
        )
        cover_letter = st.text_area(
            "Cover letter",
            value=st.session_state.get(f"{kit_key}_cover_letter", row.get("cover_letter") or ""),
            height=180,
            key=f"{kit_key}_cover_letter",
        )
        ats_cv_text = st.text_area(
            "ATS-optimized CV notes",
            value=st.session_state.get(f"{kit_key}_ats_cv_text", row.get("ats_cv_text") or ""),
            height=180,
            key=f"{kit_key}_ats_cv_text",
        )
        autofill_notes = st.text_area(
            "Autofill / portal answers",
            value=st.session_state.get(f"{kit_key}_autofill_notes", row.get("autofill_notes") or ""),
            height=180,
            key=f"{kit_key}_autofill_notes",
        )
        if st.button("Save application kit", key=f"save_{kit_key}"):
            db.update_job_application_materials(
                job_id,
                pipeline_status=selected_status,
                recruiter_message=recruiter_message,
                cover_letter=cover_letter,
                ats_cv_text=ats_cv_text,
                autofill_notes=autofill_notes,
            )
            st.success("Application kit saved.")

        st.markdown("**Quick copy**")
        copy_cols = st.columns(4)
        with copy_cols[0]:
            copy_text_button(recruiter_message, f"edit_recruiter_{job_id}", "Copy recruiter msg")
        with copy_cols[1]:
            copy_text_button(cover_letter, f"edit_cover_{job_id}", "Copy cover letter")
        with copy_cols[2]:
            copy_text_button(ats_cv_text, f"edit_ats_{job_id}", "Copy ATS notes")
        with copy_cols[3]:
            copy_text_button(autofill_notes, f"edit_autofill_{job_id}", "Copy autofill")

        if ats_cv_text.strip():
            try:
                docx_bytes = export_ats_cv_docx_bytes(
                    row.to_dict() if hasattr(row, "to_dict") else dict(row),
                    ats_cv_text,
                )
                st.download_button(
                    "Download ATS CV .docx",
                    data=docx_bytes,
                    file_name=f"ats_cv_{job_id}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"download_ats_cv_{job_id}",
                    use_container_width=True,
                )
            except LLMMaterialsError as exc:
                st.warning(str(exc))

    elif selected_action == "Inspect ranking evidence":
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

    elif selected_action == "Open posting":
        if row.get("url"):
            open_tracked_job_link("Open posting", row["url"], job_id, key=f"open_posting_ranked_{job_id}")
        else:
            st.warning("This job does not have a posting URL.")

    elif selected_action == "Open apply page":
        if row.get("apply_url"):
            open_tracked_job_link("Open apply page", row["apply_url"], job_id, key=f"open_apply_ranked_{job_id}")
        else:
            st.warning("This job does not have an apply URL.")

    elif selected_action in {"Mark shortlisted", "Mark discarded", "Mark applied"}:
        status = {
            "Mark shortlisted": "shortlisted",
            "Mark discarded": "discarded",
            "Mark applied": "applied",
        }[selected_action]
        if st.button(f"Confirm {status}", key=f"status_{status}_{job_id}"):
            db.update_job_status(job_id, status)
            st.success(f"Marked as {status}.")
            st.rerun()


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
        --bg: #f7f8fb;
        --surface: #ffffff;
        --ink: #111827;
        --muted: #6b7280;
        --line: #e5e7eb;
        --accent: #335cff;
        --success: #15803d;
        --warning: #b45309;
        --danger: #b91c1c;
    }

    .stApp {
        background: var(--bg);
        color: var(--ink);
    }

    .block-container {
        max-width: 1240px;
        padding-top: 1.35rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3, h4 {
        color: var(--ink);
        letter-spacing: 0;
    }

    h1 {
        font-size: 2rem;
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
        background: var(--surface);
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
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
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
        background: transparent;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        color: var(--muted);
        font-weight: 600;
        padding: 0.58rem 0.85rem;
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
        border-radius: 8px;
        border: 1px solid var(--line);
        box-shadow: none;
        font-weight: 650;
        min-height: 38px;
    }

    .stButton > button[kind="primary"] {
        background: var(--accent);
        border-color: var(--accent);
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

    div[data-testid="stDataFrame"],
    div[data-testid="stDataEditor"] {
        border: 1px solid var(--line);
        background: var(--surface);
        box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
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
    '<div class="app-subtitle">Un workspace privado para importar oportunidades, priorizar dónde aplicar y preparar materiales sin perder trazabilidad.</div>',
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
      <div class="flow-step"><strong>Import</strong><span>Excel y APIs a una tabla única</span></div>
      <div class="flow-step"><strong>Rank</strong><span>NVIDIA LLM sobre texto crudo</span></div>
      <div class="flow-step"><strong>Reset</strong><span>Borrar rankings y recalcular limpio</span></div>
      <div class="flow-step"><strong>Apply</strong><span>Kit, pipeline e historial</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_dashboard, tab2, tab5, tab_search, tab6, tab4 = st.tabs(
    ["Dashboard", "Import", "Ranking", "Search APIs", "Portal Scanner", "Pipeline"]
)

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
with tab_dashboard:
    st.subheader("Today")
    st.caption("Una vista rápida de volumen, backlog de revisión y pipeline para decidir dónde poner energía.")

    dashboard_jobs = db.get_job_postings(limit=10000)
    ranking_versions = db.get_ranking_versions()
    dashboard_version = SPEED_RANKING_VERSION if SPEED_RANKING_VERSION in ranking_versions else (ranking_versions[0] if ranking_versions else SPEED_RANKING_VERSION)
    dashboard_ranked = db.get_ranked_jobs(ranking_version=dashboard_version) if ranking_versions else pd.DataFrame()
    dashboard_history = db.get_historial()

    total_jobs = int(len(dashboard_jobs))
    ranked_count = int(len(dashboard_ranked))
    apply_candidates = int(
        dashboard_ranked["decision"].isin(["APPLY_NOW", "APPLY_WITH_TAILORED_CV"]).sum()
    ) if not dashboard_ranked.empty else 0
    maybe_count = int((dashboard_ranked["decision"] == "MAYBE").sum()) if not dashboard_ranked.empty else 0
    applied_count = int((dashboard_jobs.get("pipeline_status") == "applied").sum()) if not dashboard_jobs.empty and "pipeline_status" in dashboard_jobs else 0
    shortlisted_count = int((dashboard_jobs.get("pipeline_status") == "shortlisted").sum()) if not dashboard_jobs.empty and "pipeline_status" in dashboard_jobs else 0
    avg_score = float(dashboard_ranked["final_score"].mean()) if not dashboard_ranked.empty else 0

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.metric("Opportunities", total_jobs)
    with k2:
        st.metric("Ranked", ranked_count)
    with k3:
        st.metric("Apply candidates", apply_candidates)
    with k4:
        st.metric("Maybe", maybe_count)
    with k5:
        st.metric("Shortlisted", shortlisted_count)
    with k6:
        st.metric("Avg score", f"{avg_score:.0f}")

    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.markdown("**Decision distribution**")
        if dashboard_ranked.empty:
            st.info("Rank jobs to populate this chart.")
        else:
            decision_order = ["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE", "SKIP", "AVOID"]
            decision_counts = (
                dashboard_ranked["decision"]
                .value_counts()
                .reindex(decision_order, fill_value=0)
                .rename_axis("decision")
                .reset_index(name="jobs")
            )
            st.bar_chart(decision_counts, x="decision", y="jobs", height=260)

    with chart_cols[1]:
        st.markdown("**Opportunities by source**")
        if dashboard_jobs.empty:
            st.info("Import jobs to populate this chart.")
        else:
            source_counts = (
                dashboard_jobs["source"]
                .fillna("unknown")
                .value_counts()
                .head(8)
                .rename_axis("source")
                .reset_index(name="jobs")
            )
            st.bar_chart(source_counts, x="source", y="jobs", height=260)

    chart_cols_2 = st.columns(2)
    with chart_cols_2[0]:
        st.markdown("**Pipeline funnel**")
        if dashboard_jobs.empty:
            st.info("No pipeline data yet.")
        else:
            pipeline_counts = (
                dashboard_jobs["pipeline_status"]
                .fillna("unreviewed")
                .replace("", "unreviewed")
                .value_counts()
                .rename_axis("status")
                .reset_index(name="jobs")
            )
            st.bar_chart(pipeline_counts, x="status", y="jobs", height=240)

    with chart_cols_2[1]:
        st.markdown("**Score bands**")
        if dashboard_ranked.empty:
            st.info("Rank jobs to populate score bands.")
        else:
            score_bins = pd.cut(
                dashboard_ranked["final_score"],
                bins=[-1, 29, 49, 64, 79, 100],
                labels=["0-29", "30-49", "50-64", "65-79", "80-100"],
            )
            score_counts = score_bins.value_counts().sort_index().rename_axis("score_band").reset_index(name="jobs")
            st.bar_chart(score_counts, x="score_band", y="jobs", height=240)

    today_cols = st.columns(2)
    with today_cols[0]:
        st.markdown("**Top opportunities**")
        if dashboard_ranked.empty:
            st.info("No ranked jobs yet.")
        else:
            top_jobs = dashboard_ranked[
                dashboard_ranked["decision"].isin(["APPLY_NOW", "APPLY_WITH_TAILORED_CV", "MAYBE"])
            ].head(6)
            st.dataframe(
                top_jobs[["job_id", "title", "company", "final_score", "decision", "source"]],
                use_container_width=True,
                hide_index=True,
                column_config={"final_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100)},
            )

    with today_cols[1]:
        st.markdown("**Maybe queue**")
        if dashboard_ranked.empty or maybe_count == 0:
            st.info("No MAYBE jobs.")
        else:
            maybe_jobs = dashboard_ranked[dashboard_ranked["decision"] == "MAYBE"].head(6)
            st.dataframe(
                maybe_jobs[["job_id", "title", "company", "final_score", "source"]],
                use_container_width=True,
                hide_index=True,
                column_config={"final_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100)},
            )

    if not dashboard_history.empty:
        st.markdown("**Recently opened**")
        recent_cols = [c for c in ["titulo", "empresa", "score_total", "fecha_ultima_vista", "aplicado"] if c in dashboard_history.columns]
        st.dataframe(dashboard_history[recent_cols].head(8), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# TAB 2 â€” IMPORT LINKEDIN
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Import LinkedIn Excel")
    st.caption("Carga el Excel del scraper propio y normaliza las ofertas en `job_postings` para rankearlas.")

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
        min_desc_len = st.number_input(
            "Longitud mÃ­nima de descripciÃ³n (filtra basura)",
            min_value=0,
            max_value=2000,
            value=MIN_DESCRIPCION_LEN_DEFAULT,
            step=50,
        )

        if st.button("Import LinkedIn jobs", type="primary"):
            df_filtrado, stats = filtrar_ofertas(df_crudo, min_descripcion_len=min_desc_len)
            st.session_state.df_filtrado = df_filtrado

            st.write(
                f"Original: **{stats['original']}** â†’ tras duplicados: **{stats['tras_duplicados']}** "
                f"â†’ tras extracciÃ³n OK: **{stats['tras_extraccion_ok']}** "
                f"â†’ tras descripciÃ³n mÃ­nima: **{stats['tras_descripcion_minima']}**"
            )

            if df_filtrado.empty:
                st.warning("No quedÃ³ ninguna oferta tras deduplicar y filtrar.")
            else:
                import_stats = import_linkedin_dataframe_to_job_postings(df_filtrado)
                st.success(
                    "Ranking store actualizado desde LinkedIn scraper: "
                    f"{import_stats['new']} nuevas, {import_stats['updated']} actualizadas, "
                    f"{import_stats['seen']} sin cambios."
                )

# ---------------------------------------------------------------------------
# TAB 3 — SEARCH APIS
# ---------------------------------------------------------------------------
with tab_search:
    st.subheader("Search APIs")
    st.caption(
        "Busca oportunidades por keyword/location en agregadores públicos y guarda todo en `job_postings`."
    )

    default_queries = "\n".join(
        [
            "software developer",
            "software engineer",
            "backend developer",
            "python developer",
            "technical consultant",
            "solutions engineer",
        ]
    )
    query_text = st.text_area("Keywords", value=default_queries, height=150)
    search_cols = st.columns([2, 1, 1, 1])
    with search_cols[0]:
        location = st.text_input("Location", value="Spain")
    with search_cols[1]:
        remote = st.checkbox("Include remote/EU", value=True)
    with search_cols[2]:
        max_pages = st.number_input("Pages/provider", min_value=1, max_value=5, value=1, step=1)
    with search_cols[3]:
        search_concurrency = st.number_input("Concurrency", min_value=1, max_value=8, value=4, step=1)

    provider_options = sorted(SEARCH_PROVIDERS.keys())
    default_providers = [provider for provider in ["arbeitnow", "remotive", "adzuna"] if provider in provider_options]
    selected_search_providers = st.multiselect(
        "Providers",
        provider_options,
        default=default_providers,
    )
    missing_config = [provider for provider in selected_search_providers if provider_requires_configuration(provider)]
    if missing_config:
        st.warning(
            "Providers requiring env vars will be skipped/fail until configured: "
            + ", ".join(missing_config)
            + ". Adzuna needs ADZUNA_APP_ID and ADZUNA_APP_KEY."
        )

    if st.button("Search job APIs", type="primary"):
        queries = [line.strip() for line in query_text.splitlines() if line.strip()]
        if not queries:
            st.error("Add at least one keyword.")
        elif not selected_search_providers:
            st.error("Select at least one provider.")
        else:
            with st.spinner("Searching aggregators..."):
                results = asyncio.run(
                    search_scanner.search_jobs_concurrently(
                        selected_search_providers,
                        queries,
                        location=location.strip() or None,
                        remote=remote,
                        max_pages=int(max_pages),
                        max_concurrency=int(search_concurrency),
                    )
                )
            if not results:
                st.info("No search tasks were run.")
            else:
                summary_rows = [
                    {
                        "provider": result.source_type,
                        "query": result.company_name,
                        "found": result.found_count,
                        "new": len(result.new_jobs),
                        "updated": len(result.updated_jobs),
                        "seen": len(result.unchanged_jobs),
                        "errors": "; ".join(result.errors),
                        "seconds": result.duration_seconds,
                    }
                    for result in results
                ]
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
                st.success(
                    f"Search complete: {sum(row['new'] for row in summary_rows)} nuevas, "
                    f"{sum(row['updated'] for row in summary_rows)} actualizadas, "
                    f"{sum(row['seen'] for row in summary_rows)} sin cambios."
                )

# ---------------------------------------------------------------------------
# TAB 4 â€” HISTORIAL / APLICADAS
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Historial completo")
    st.caption(
        "Ofertas que abriste desde Opportunity Ranking o Portal scanner. AcÃ¡ podÃ©s marcar aplicadas, "
        "agregar notas y mantener trazabilidad de lo que realmente revisaste."
    )

    solo_aplicadas = st.checkbox("Mostrar solo las que ya marquÃ© como aplicadas", value=False)
    df_hist = db.get_historial(solo_aplicadas=solo_aplicadas)

    if df_hist.empty:
        st.info("TodavÃ­a no hay nada en el histÃ³rico. AbrÃ­ una oferta desde Opportunity Ranking para registrarla.")
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
            "Los scores se volverÃ¡n a copiar desde Opportunity Ranking cuando abras una oferta rankeada."
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
            st.session_state.df_filtrado = None
            st.success(f"Historial eliminado: {filas} ofertas borradas.")
            st.rerun()
# ---------------------------------------------------------------------------
# TAB 5 â€” OPPORTUNITY RANKING
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("Opportunity Ranking")
    st.caption(
        "LLM ranking sobre texto crudo. Usa NVIDIA primero para evitar mezclar resultados heurísticos. "
        f"Current version: `{SPEED_RANKING_VERSION}`."
    )

    target_ranking_version = SPEED_RANKING_VERSION

    all_jobs_for_estimate = db.get_job_postings(limit=10000)
    total_jobs_for_estimate = len(all_jobs_for_estimate)
    planning_cols = st.columns(4)
    with planning_cols[0]:
        st.metric("Jobs loaded", total_jobs_for_estimate)
    with planning_cols[1]:
        st.metric("Ranking version", target_ranking_version)
    with planning_cols[2]:
        st.metric("NVIDIA mode", "free/credits")
    with planning_cols[3]:
        st.metric("Kit / selected job", f"${estimate_materials_cost(1, DEFAULT_MATERIALS_MODEL):.3f}")

    with st.expander("Reset rankings before reranking", expanded=False):
        st.warning(
            "Use this when you want a clean rerank. It deletes stored rankings for the current version so the table "
            "cannot mix old heuristic scores with NVIDIA rankings."
        )
        reset_scope = st.radio(
            "Delete scope",
            ["Current ranking version only", "All ranking versions"],
            horizontal=True,
            key="delete_ranking_scope",
        )
        confirm_delete_rankings = st.text_input(
            "Type DELETE RANKINGS to confirm",
            key="confirm_delete_rankings",
        )
        if st.button(
            "Delete stored rankings",
            disabled=confirm_delete_rankings != "DELETE RANKINGS",
            use_container_width=True,
        ):
            deleted = db.delete_job_rankings(
                target_ranking_version if reset_scope == "Current ranking version only" else None
            )
            st.success(f"Deleted {deleted} ranking rows. Run NVIDIA ranking next.")
            st.rerun()

    with st.expander("Free/credits-first ranking via NVIDIA", expanded=True):
        st.caption(
            "Use this first for personal use. It sends local chunks to NVIDIA's OpenAI-compatible chat API, "
            "saves every successful ranking to SQLite, and can be resumed."
        )
        nvidia_ready = bool(nvidia_api_key())
        nvidia_cols = st.columns([1, 1, 1, 1, 1, 2])
        with nvidia_cols[0]:
            nvidia_model = st.text_input("NVIDIA model", value=DEFAULT_NVIDIA_MODEL, key="nvidia_model")
        with nvidia_cols[1]:
            nvidia_request_batch_size = st.number_input(
                "Jobs/request",
                min_value=1,
                max_value=10,
                value=5,
                step=1,
                key="nvidia_request_batch_size",
                help="Smaller is more reliable. 5 is a good default for JSON quality.",
            )
        with nvidia_cols[2]:
            nvidia_concurrency = st.number_input(
                "Concurrent requests",
                min_value=1,
                max_value=8,
                value=3,
                step=1,
                key="nvidia_concurrency",
                help="Start with 3. Increase if NVIDIA does not rate-limit; decrease on 429/503 errors.",
            )
        with nvidia_cols[3]:
            nvidia_jobs_per_click = st.number_input(
                "Jobs/click",
                min_value=1,
                max_value=250,
                value=50,
                step=25,
                key="nvidia_jobs_per_click",
                help="How many jobs to process before the UI returns control.",
            )
        with nvidia_cols[4]:
            nvidia_offset = st.number_input(
                "Offset",
                min_value=0,
                max_value=max(0, total_jobs_for_estimate - 1),
                value=0,
                step=int(nvidia_jobs_per_click),
                key="nvidia_offset",
            )
        with nvidia_cols[5]:
            if nvidia_ready:
                st.success("NVIDIA_API_KEY/NIM_API_KEY detected. Use this before paid OpenAI.")
            else:
                st.warning("Set NVIDIA_API_KEY or NIM_API_KEY to use NVIDIA free/credits ranking.")

        nvidia_overwrite = st.checkbox(
            "Overwrite current ranking version",
            value=True,
            key="nvidia_overwrite_rankings",
            help="Turn this on to replace the bad heuristic rankings. Turn it off to rank only missing rows.",
        )
        nvidia_confirm = st.text_input(
            "Type NVIDIA to run this chunk",
            key="confirm_nvidia_ranking",
        )
        if st.button(
            "Rank chunk with NVIDIA",
            type="primary",
            use_container_width=True,
            disabled=not nvidia_ready or nvidia_confirm != "NVIDIA",
        ):
            try:
                if nvidia_overwrite:
                    jobs_for_nvidia = db.get_job_postings(limit=int(nvidia_offset) + int(nvidia_jobs_per_click))
                    jobs_for_nvidia = jobs_for_nvidia.iloc[int(nvidia_offset) : int(nvidia_offset) + int(nvidia_jobs_per_click)]
                else:
                    jobs_for_nvidia = db.get_unranked_jobs(
                        ranking_version=target_ranking_version,
                        limit=int(nvidia_jobs_per_click),
                    )
                if jobs_for_nvidia.empty:
                    st.info("No jobs to rank in this NVIDIA chunk.")
                else:
                    with st.spinner("Ranking chunk with NVIDIA..."):
                        summary = rank_jobs_with_nvidia(
                            jobs_for_nvidia,
                            model=nvidia_model,
                            request_batch_size=int(nvidia_request_batch_size),
                            max_concurrency=int(nvidia_concurrency),
                            ranking_version=target_ranking_version,
                        )
                    st.success(
                        "NVIDIA ranking saved: "
                        + " · ".join(f"{key}={value}" for key, value in summary.items())
                    )
                    st.rerun()
            except NvidiaRankingError as exc:
                st.error(str(exc))

    st.divider()
    versions = db.get_ranking_versions()
    if target_ranking_version not in versions:
        versions = [target_ranking_version, *versions]
    selected_ranking_version = st.selectbox("Ranking version", versions)

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
        ranking_version=selected_ranking_version,
    )

    if not ranked.empty:
        ranked = ranked.copy()

    if ranked.empty:
        unranked = db.get_unranked_jobs(limit=1)
        if unranked.empty:
            st.info("No scanner jobs found yet. Import or scan jobs first.")
        else:
            st.info("Jobs exist but no ranking matches this view. Run NVIDIA ranking or adjust filters.")
    else:
        table = ranked[
            [
                "job_id",
                "title",
                "company",
                "source",
                "workplace_type",
                "location",
                "final_score",
                "decision",
                "pipeline_status",
                "url",
                "apply_url",
                "confidence",
                "ranked_at",
            ]
        ].copy()
        table["where"] = (
            table["workplace_type"].fillna("").astype(str).str.strip()
            + " "
            + table["location"].fillna("").astype(str).str.strip()
        ).str.strip()
        table = table.drop(columns=["workplace_type", "location"])
        ordered_cols = [
            "job_id",
            "title",
            "company",
            "source",
            "where",
            "final_score",
            "decision",
            "pipeline_status",
            "url",
            "apply_url",
            "confidence",
            "ranked_at",
        ]
        table = table[ordered_cols]
        table.insert(0, "select", False)
        edited_table = st.data_editor(
            table,
            use_container_width=True,
            hide_index=True,
            disabled=[
                column
                for column in table.columns
                if column != "select"
            ],
            column_config={
                "select": st.column_config.CheckboxColumn("Select"),
                "final_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "where": st.column_config.TextColumn("Location / mode"),
                "url": st.column_config.LinkColumn("Posting"),
                "apply_url": st.column_config.LinkColumn("Apply"),
            },
            key="ranking_action_table",
        )
        selected_rows = edited_table[edited_table["select"]]
        if selected_rows.empty:
            st.info("Select one job in the table to show all available actions.")
        else:
            selected = selected_rows.iloc[0]
            selected_job_id = int(selected["job_id"])
            default_action = "Generate application kit"
            source_row = ranked[ranked["job_id"].astype(int) == selected_job_id].iloc[0].copy()
            selected_action = render_ranking_action_toolbar(selected_job_id, default_action)
            source_row["action"] = selected_action
            st.markdown("### Selected action")
            render_ranking_action_panel(source_row, selected_action)

# ---------------------------------------------------------------------------
# TAB 6 â€” PORTAL SCANNER
# ---------------------------------------------------------------------------
with tab6:
    scanner_view = st.radio(
        "Workspace",
        ["Dashboard", "Sources", "Opportunity Inbox", "Job Detail"],
        horizontal=True,
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
            scan_concurrency = st.slider(
                "Parallel scans",
                min_value=1,
                max_value=12,
                value=6,
                help="How many ATS sources to scan at the same time.",
            )
            if st.button("Scan sources", type="primary", use_container_width=True):
                with st.spinner("Scanning enabled ATS sources..."):
                    results = asyncio.run(
                        source_scanner.scan_enabled_sources(max_concurrency=scan_concurrency)
                    )
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
                        open_tracked_job_link(
                            "Open",
                            data["url"],
                            int(data["id"]),
                            key=f"open_inbox_{int(data['id'])}",
                        )
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
                        open_tracked_job_link(
                            "Open posting",
                            job["url"],
                            int(job["id"]),
                            key=f"open_posting_detail_{int(job['id'])}",
                        )
                with link_cols[1]:
                    if job.get("apply_url"):
                        open_tracked_job_link(
                            "Apply URL",
                            job["apply_url"],
                            int(job["id"]),
                            key=f"open_apply_detail_{int(job['id'])}",
                        )

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

