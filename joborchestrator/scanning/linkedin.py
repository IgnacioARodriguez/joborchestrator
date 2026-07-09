"""
LinkedIn Job Scraper - Backend Python RAW
=========================================
- Login manual persistente
- Reutiliza sesiÃ³n local de navegador
- No automatiza credenciales
- No intenta saltarse captchas, checkpoints ni verificaciones
- Recorre mÃºltiples bÃºsquedas
- Extrae jobs del listado izquierdo acumulando IDs mientras scrollea
- Clickea cada card visible/acumulada
- Lee el panel derecho del job seleccionado
- Exporta datos crudos a Excel y JSON
- Guarda checkpoint incremental en JSONL

IMPORTANTE:
Este script NO hace scoring ni filtra ofertas por relevancia.
La idea es exportar raw data para analizar despuÃ©s con IA.
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from joborchestrator.intelligence.cv_profile_extractor import profile_payload_to_candidate_profile
from joborchestrator.ranking.role_catalog import role_catalog_from_profile
from joborchestrator.ranking.schemas import CandidateProfile
from joborchestrator.storage import persistence as db


FRESHNESS_WINDOW_SECONDS = 30 * 24 * 60 * 60
TARGET_ROLE_FRESHNESS_WINDOW_SECONDS = 2 * 24 * 60 * 60
SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS = FRESHNESS_WINDOW_SECONDS


def build_busquedas_from_profile(profile: CandidateProfile, max_terms: int = 40) -> list[dict[str, str | int]]:
    entries = role_catalog_from_profile(profile)
    role_terms: list[tuple[str, str, int]] = []
    for entry in entries:
        # Adjust these constants to change the LinkedIn cadence by role priority:
        # target roles stay very fresh; secondary roles keep a wider discovery window.
        window_seconds = (
            TARGET_ROLE_FRESHNESS_WINDOW_SECONDS
            if entry.priority == "target"
            else SECONDARY_ROLE_FRESHNESS_WINDOW_SECONDS
        )
        for term in entry.search_terms:
            role_terms.append((term, entry.priority, window_seconds))
    role_terms = role_terms[:max_terms]
    locations = profile.preferred_locations or ["Spain"]
    if any(str(mode).lower() == "remote" for mode in profile.preferred_work_modes):
        locations = [*locations, "European Union"]
    searches = []
    seen = set()
    for term, priority, window_seconds in role_terms:
        for location in locations:
            key = (term.lower(), str(location).lower())
            if key in seen:
                continue
            seen.add(key)
            searches.append(
                {
                    "keywords": term,
                    "ubicacion": str(location),
                    "categoria": _category_from_role(term),
                    "role_priority": priority,
                    "freshness_window_seconds": window_seconds,
                }
            )
    return searches


def load_profile_busquedas() -> list[dict[str, str | int]]:
    profile_payload = db.get_candidate_profile_payload()
    if not profile_payload:
        raise RuntimeError("No candidate profile configured. Upload a CV and define target roles before running LinkedIn scraping.")
    profile = CandidateProfile(**profile_payload_to_candidate_profile(profile_payload))
    searches = build_busquedas_from_profile(profile)
    if not searches:
        raise RuntimeError("No target roles configured in profile. Add roles or aliases before running LinkedIn scraping.")
    return searches


def _category_from_role(role: str) -> str:
    category = re.sub(r"[^a-zA-Z0-9]+", "_", role.lower()).strip("_")
    return category or "profile_role"


# ============================================================
# CONFIGURACIÃ“N GENERAL
# ============================================================


# No pongas 100000. LinkedIn no se comporta como una API paginada perfecta.
# SubÃ­ MAX_PAGINAS si querÃ©s explorar mÃ¡s profundidad por bÃºsqueda.
LIMITE_RESULTADOS = 100000
MAX_PAGINAS = 200
PAGINAS_CONSECUTIVAS_SIN_NUEVOS = 3

def resolve_output_dir() -> Path:
    configured = os.getenv("LINKEDIN_OUTPUT_DIR")
    if configured:
        return Path(configured)
    if os.getenv("VERCEL"):
        return Path("/tmp/salidas_todas_posiciones_raw")
    return Path("salidas_todas_posiciones_raw")


OUTPUT_DIR = resolve_output_dir()

ARCHIVO_SALIDA = str(
    OUTPUT_DIR / f"ofertas_todas_posiciones_RAW_{datetime.now().strftime('%Y%m%d_%H%M')}"
)

LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/search/"

# Ponelo en True una sola ejecuciÃ³n si querÃ©s ver logs de scroll.
DEBUG = False

# Perfil persistente local de LinkedIn.
# Primera ejecuciÃ³n: login manual.
# Siguientes ejecuciones: reutiliza cookies/sesiÃ³n.
LINKEDIN_PROFILE_SETTING_KEY = "linkedin_profile_name"
DEFAULT_LINKEDIN_PROFILE_NAME = "test"
DISABLED_LINKEDIN_PROFILE_NAMES = {"main"}
LINKEDIN_PROFILE_PREFIX = "linkedin_user_profile"
PERFIL_LINKEDIN = Path(LINKEDIN_PROFILE_PREFIX).resolve()


def linkedin_profile_dir(profile_name: str | None = None) -> Path:
    name = sanitize_linkedin_profile_name(
        profile_name
        or str(db.get_app_setting(LINKEDIN_PROFILE_SETTING_KEY, DEFAULT_LINKEDIN_PROFILE_NAME) or DEFAULT_LINKEDIN_PROFILE_NAME)
    )
    if name in DISABLED_LINKEDIN_PROFILE_NAMES:
        name = DEFAULT_LINKEDIN_PROFILE_NAME
    dirname = LINKEDIN_PROFILE_PREFIX if name == "main" else f"{LINKEDIN_PROFILE_PREFIX}_{name}"
    return Path(dirname).resolve()


def sanitize_linkedin_profile_name(value: str | None) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip()).strip("_").lower()
    return text or DEFAULT_LINKEDIN_PROFILE_NAME


def get_linkedin_profile_setting() -> dict[str, object]:
    current = sanitize_linkedin_profile_name(
        str(db.get_app_setting(LINKEDIN_PROFILE_SETTING_KEY, DEFAULT_LINKEDIN_PROFILE_NAME) or DEFAULT_LINKEDIN_PROFILE_NAME)
    )
    if current in DISABLED_LINKEDIN_PROFILE_NAMES:
        current = DEFAULT_LINKEDIN_PROFILE_NAME
        db.set_app_setting(LINKEDIN_PROFILE_SETTING_KEY, current)
    profiles = {DEFAULT_LINKEDIN_PROFILE_NAME}
    for path in Path.cwd().glob(f"{LINKEDIN_PROFILE_PREFIX}*"):
        if not path.is_dir():
            continue
        if path.name == LINKEDIN_PROFILE_PREFIX:
            continue
        elif path.name.startswith(f"{LINKEDIN_PROFILE_PREFIX}_"):
            profile = sanitize_linkedin_profile_name(path.name.removeprefix(f"{LINKEDIN_PROFILE_PREFIX}_"))
            if profile not in DISABLED_LINKEDIN_PROFILE_NAMES:
                profiles.add(profile)
    profiles.add(current)
    return {
        "current": current,
        "profiles": sorted(profiles),
        "profile_dir": str(linkedin_profile_dir(current)),
    }


def set_linkedin_profile_setting(profile_name: str) -> dict[str, object]:
    name = sanitize_linkedin_profile_name(profile_name)
    if name in DISABLED_LINKEDIN_PROFILE_NAMES:
        raise ValueError("The main LinkedIn profile is disabled. Use a separate test profile.")
    db.set_app_setting(LINKEDIN_PROFILE_SETTING_KEY, name)
    return get_linkedin_profile_setting()

GUARDAR_CHECKPOINT = True
REANUDAR_DESDE_CHECKPOINT = True
EXPORTAR_SNAPSHOT_CADA_PAGINA = True

CHECKPOINT_JSONL = OUTPUT_DIR / "checkpoint_ofertas_todas_posiciones_raw.jsonl"
CHECKPOINT_STATE = OUTPUT_DIR / "checkpoint_estado_todas_posiciones_raw.json"
CHECKPOINT_SNAPSHOT_BASE = str(OUTPUT_DIR / "snapshot_actual_todas_posiciones_raw")


def jitter_ms(base_ms: int, spread: float = 0.25) -> int:
    low = max(0, base_ms * (1 - spread))
    high = base_ms * (1 + spread)
    return int(random.uniform(low, high))


def jitter_seconds(base_seconds: float, spread: float = 0.25) -> float:
    low = max(0.0, base_seconds * (1 - spread))
    high = base_seconds * (1 + spread)
    return random.uniform(low, high)


# ============================================================
# CHECKPOINT Y EXPORTACIÃ“N
# ============================================================

def deduplicar_ofertas(ofertas: list[dict]) -> list[dict]:
    por_id = {}

    for oferta in ofertas:
        job_id = str(oferta.get("id", "")).strip()
        if job_id:
            por_id[job_id] = oferta

    return list(por_id.values())


def cargar_checkpoint(freshness_window_seconds: int = FRESHNESS_WINDOW_SECONDS) -> tuple[list[dict], set[str]]:
    db_seen_ids = db.get_recent_external_ids_for_source(
        "linkedin_scraper",
        freshness_window_seconds=freshness_window_seconds,
    )
    if not REANUDAR_DESDE_CHECKPOINT or not CHECKPOINT_JSONL.exists():
        if db_seen_ids:
            print(f"DB freshness cargada: {len(db_seen_ids)} IDs recientes de LinkedIn.")
        return [], db_seen_ids

    ofertas = []
    lineas_invalidas = 0

    with open(CHECKPOINT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            try:
                oferta = json.loads(line)
                if oferta.get("id"):
                    ofertas.append(oferta)
            except json.JSONDecodeError:
                lineas_invalidas += 1

    ofertas = deduplicar_ofertas(ofertas)
    seen_ids = {str(o["id"]) for o in ofertas if o.get("id")} | db_seen_ids

    print(
        f"â™» Checkpoint cargado: {len(ofertas)} ofertas Ãºnicas "
        f"desde {CHECKPOINT_JSONL}; DB recientes={len(db_seen_ids)}"
    )

    if lineas_invalidas:
        print(f"âš  LÃ­neas invÃ¡lidas ignoradas en checkpoint: {lineas_invalidas}")

    return ofertas, seen_ids


def guardar_oferta_checkpoint(oferta: dict):
    if not GUARDAR_CHECKPOINT:
        return

    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(CHECKPOINT_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(oferta, ensure_ascii=False) + "\n")


def guardar_estado_checkpoint(busqueda: dict, start_value: int, total_ofertas: int):
    if not GUARDAR_CHECKPOINT:
        return

    estado = {
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
        "busqueda_actual": busqueda,
        "pagina_start_actual": start_value,
        "total_ofertas_checkpoint": total_ofertas,
        "checkpoint_jsonl": str(CHECKPOINT_JSONL),
    }

    temp_path = CHECKPOINT_STATE.with_suffix(".tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

    temp_path.replace(CHECKPOINT_STATE)


def exportar_snapshot_resultados(ofertas: list[dict]):
    if not GUARDAR_CHECKPOINT or not ofertas:
        return

    exportar_resultados(ofertas, CHECKPOINT_SNAPSHOT_BASE)


def build_linkedin_search_params(busqueda: dict, start: int) -> dict[str, str | int]:
    freshness_window_seconds = int(busqueda.get("freshness_window_seconds") or FRESHNESS_WINDOW_SECONDS)
    params: dict[str, str | int] = {
        "keywords": busqueda["keywords"],
        "location": busqueda["ubicacion"],
        "start": start,
        "sortBy": "DD",
        "f_TPR": f"r{freshness_window_seconds}",
    }
    params.update(busqueda.get("filtros", {}))
    return params


# ============================================================
# LIMPIEZA DE TEXTO Y EXCEL
# ============================================================

def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\r", "\n", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()


EXCEL_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]")
EXCEL_MAX_CELL_LENGTH = 32767


def limpiar_para_excel(valor):
    if valor is None:
        return ""

    if isinstance(valor, str):
        valor = EXCEL_ILLEGAL_CHARS_RE.sub("", valor)
        return valor[:EXCEL_MAX_CELL_LENGTH]

    return valor


def sanitizar_dataframe_para_excel(df: pd.DataFrame) -> pd.DataFrame:
    df_excel = df.copy()

    for col in df_excel.columns:
        df_excel[col] = df_excel[col].map(limpiar_para_excel)

    return df_excel


def limpiar_descripcion(texto: str) -> str:
    texto = limpiar_texto(texto)

    if not texto:
        return ""

    texto = re.sub(r"\s*â€¦\s*mÃ¡s\s*$", "", texto, flags=re.IGNORECASE).strip()
    texto = re.sub(r"\s*â€¦\s*more\s*$", "", texto, flags=re.IGNORECASE).strip()

    basura_final = [
        r"mostrar mÃ¡s\s*$",
        r"show more\s*$",
        r"me interesa\s*$",
        r"solicitar\s*$",
        r"guardar\s*$",
    ]

    for patron in basura_final:
        texto = re.sub(patron, "", texto, flags=re.IGNORECASE).strip()

    return texto


# ============================================================
# EXTRACCIÃ“N DE METADATA
# ============================================================

def extraer_modalidad_desde_texto(texto: str) -> str:
    if not texto:
        return ""

    t = texto.lower()

    patrones = [
        ("remote", [r"\ben remoto\b", r"\bremote\b", r"\bremoto\b"]),
        ("hybrid", [r"\bhÃ­brido\b", r"\bhybrid\b"]),
        ("onsite", [r"\bpresencial\b", r"\bon-?site\b", r"\bin office\b"]),
    ]

    encontrados = []

    for etiqueta, regs in patrones:
        if any(re.search(reg, t, re.IGNORECASE) for reg in regs):
            encontrados.append(etiqueta)

    return ", ".join(encontrados)


def extraer_fecha_desde_texto(texto: str) -> str:
    if not texto:
        return ""

    patrones = [
        r"hace \d+ (hora|horas|dÃ­a|dÃ­as|semana|semanas|mes|meses)",
        r"publicado de nuevo hace \d+ (hora|horas|dÃ­a|dÃ­as|semana|semanas|mes|meses)",
        r"posted \d+ (hour|hours|day|days|week|weeks|month|months) ago",
        r"reposted \d+ (hour|hours|day|days|week|weeks|month|months) ago",
        r"en las Ãºltimas 24 horas",
        r"in the past 24 hours",
    ]

    for patron in patrones:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            return m.group(0)

    return ""


# ============================================================
# LOGIN PERSISTENTE / SESIÃ“N
# ============================================================

async def crear_contexto_linkedin(p):
    """
    Crea un contexto persistente.
    No automatiza el login; reutiliza sesiÃ³n local si ya existe.
    """

    context = await p.chromium.launch_persistent_context(
        user_data_dir=str(linkedin_profile_dir()),
        headless=False,
        viewport={"width": 1440, "height": 1000},
        locale="es-ES",
        args=["--start-maximized"],
        slow_mo=50,
    )

    page = context.pages[0] if context.pages else await context.new_page()

    return context, page


async def linkedin_pide_verificacion(page) -> bool:
    """
    Detecta captcha, checkpoint o verificaciÃ³n.
    Si aparece, el script debe detenerse.
    """

    url = page.url.lower()

    indicadores_url = [
        "checkpoint",
        "challenge",
        "captcha",
    ]

    if any(x in url for x in indicadores_url):
        return True

    try:
        body = (await page.locator("body").inner_text(timeout=3000)).lower()
    except Exception:
        return False

    indicadores_texto = [
        "security verification",
        "verificaciÃ³n de seguridad",
        "captcha",
        "checkpoint",
        "we need to verify",
        "tenemos que verificar",
        "verify your identity",
        "verifica tu identidad",
        "unusual activity",
        "actividad inusual",
    ]

    return any(t in body for t in indicadores_texto)


async def asegurar_sesion_manual(page):
    """
    Comprueba sesiÃ³n activa.
    Si no hay sesiÃ³n, pide login manual una sola vez.
    """

    await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    await page.wait_for_timeout(jitter_ms(2500))

    if await linkedin_pide_verificacion(page):
        raise RuntimeError(
            "LinkedIn estÃ¡ pidiendo verificaciÃ³n. "
            "No continÃºo automÃ¡ticamente."
        )

    if "/login" in page.url:
        print("\n" + "=" * 60)
        print("Inicia sesiÃ³n manualmente en la ventana abierta.")
        print("No cierres el navegador.")
        print("Cuando termines, vuelve a la terminal y pulsa ENTER.")
        print("=" * 60)

        input("â†’ ENTER cuando hayas terminado el login manual: ")

        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        await page.wait_for_timeout(jitter_ms(2500))

        if "/login" in page.url:
            raise RuntimeError("No se detectÃ³ sesiÃ³n activa despuÃ©s del login manual.")

        if await linkedin_pide_verificacion(page):
            raise RuntimeError(
                "LinkedIn pidiÃ³ verificaciÃ³n despuÃ©s del login. "
                "No continÃºo automÃ¡ticamente."
            )

    print("âœ… SesiÃ³n de LinkedIn activa.")


# ============================================================
# NAVEGACIÃ“N
# ============================================================

async def navegar_estable(page, url: str, timeout: int = 30000):
    try:
        await page.goto(url, wait_until="networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(jitter_ms(5000))


async def dump_debug_info(page, etiqueta: str = "debug"):
    print(f"\n[DEBUG:{etiqueta}] URL real: {page.url}")
    print(f"[DEBUG:{etiqueta}] Title: {await page.title()}")

    jobs_view_count = await page.locator('a[href*="/jobs/view/"]').count()
    apply_count = await page.locator('a[href*="/jobs/view/"][href*="/apply/"]').count()

    print(f"[DEBUG:{etiqueta}] links /jobs/view/: {jobs_view_count}")
    print(f"[DEBUG:{etiqueta}] links /apply/: {apply_count}")

    await page.screenshot(path=f"{etiqueta}.png", full_page=True)

    print(f"[DEBUG:{etiqueta}] screenshot: {etiqueta}.png")


async def pagina_sin_resultados_reales(page) -> bool:
    textos_posibles = [
        "No matching jobs found",
        "No results found",
        "No hay resultados",
        "No hemos encontrado coincidencias",
        "No encontramos empleos",
        "No jobs found",
    ]

    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
        body_text = (body_text or "").strip().lower()

        return any(t.lower() in body_text for t in textos_posibles)
    except Exception:
        return False


# ============================================================
# EXTRACCIÃ“N DE RESULTADOS DEL LISTADO
# ============================================================

async def resetear_scroll_listado(page):
    await page.evaluate(
        """
        () => {
            const findScrollableParent = (el) => {
                let node = el;

                while (node && node !== document.body) {
                    const style = window.getComputedStyle(node);
                    const overflowY = style.overflowY;
                    const canScroll =
                        (overflowY === 'auto' || overflowY === 'scroll') &&
                        node.scrollHeight > node.clientHeight + 20;

                    if (canScroll) return node;
                    node = node.parentElement;
                }

                return document.scrollingElement || document.documentElement;
            };

            const firstCard =
                document.querySelector('li[data-occludable-job-id]') ||
                document.querySelector('.jobs-search-results__list-item') ||
                document.querySelector('.job-card-container') ||
                document.querySelector('a[href*="/jobs/view/"]');

            const scroller = firstCard
                ? findScrollableParent(firstCard)
                : (document.scrollingElement || document.documentElement);

            scroller.scrollTop = 0;
        }
        """
    )


async def extraer_resultados_dom_actual(page) -> list[dict]:
    return await page.evaluate(
        """
        () => {
            const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();

            const absoluteUrl = (href) => {
                try {
                    return new URL(href, window.location.origin).toString();
                } catch {
                    return href || '';
                }
            };

            const cleanTitle = (text) => {
                const lines = (text || '')
                    .split('\\n')
                    .map(normalize)
                    .filter(Boolean);

                if (lines.length >= 2 && lines[0] === lines[1]) return lines[0];

                const candidate = lines.find(l =>
                    l.length >= 3 &&
                    l.length <= 160 &&
                    !/^(Promocionado|Promoted|Hace \\d+|Publicado|Reposted|Viewed|Visto)/i.test(l)
                );

                return candidate || normalize(text);
            };

            const out = [];

            const listRoot =
                document.querySelector('.jobs-search-results-list') ||
                document.querySelector('.jobs-search-results__list') ||
                document.querySelector('.scaffold-layout__list') ||
                document;

            const cardSelectors = [
                'li[data-occludable-job-id]',
                '.jobs-search-results__list-item',
                '.scaffold-layout__list-item',
                '.job-card-container',
                'div[data-job-id]'
            ];

            let cards = Array.from(listRoot.querySelectorAll(cardSelectors.join(',')));

            if (!cards.length) {
                cards = Array.from(listRoot.querySelectorAll('a[href*="/jobs/view/"]'));
            }

            for (const card of cards) {
                const link = card.matches && card.matches('a[href*="/jobs/view/"]')
                    ? card
                    : card.querySelector('a[href*="/jobs/view/"]:not([href*="/apply/"])');

                if (!link) continue;

                const href = absoluteUrl(link.getAttribute('href') || '');

                if (!href.includes('/jobs/view/')) continue;
                if (href.includes('/apply/')) continue;

                const m = href.match(/\\/jobs\\/view\\/(\\d+)/);

                if (!m) continue;

                const jobId = m[1];

                const titleNode =
                    card.querySelector('.job-card-list__title') ||
                    card.querySelector('.job-card-container__link') ||
                    card.querySelector('strong') ||
                    link;

                const titulo = cleanTitle(titleNode.innerText || link.innerText);

                if (!titulo || titulo.length < 3 || titulo.length > 180) continue;

                out.push({
                    id: jobId,
                    titulo,
                    url: `https://www.linkedin.com/jobs/view/${jobId}/`
                });
            }

            return out;
        }
        """
    )


async def scroll_listado_jobs(page) -> dict:
    """
    Hace scroll sobre el contenedor realmente scrollable del listado.
    Si el selector principal no es scrollable, busca el ancestro scrollable.
    """

    return await page.evaluate(
        """
        () => {
            const findScrollableParent = (el) => {
                let node = el;

                while (node && node !== document.body) {
                    const style = window.getComputedStyle(node);
                    const overflowY = style.overflowY;
                    const canScroll =
                        (overflowY === 'auto' || overflowY === 'scroll') &&
                        node.scrollHeight > node.clientHeight + 20;

                    if (canScroll) return node;
                    node = node.parentElement;
                }

                return document.scrollingElement || document.documentElement;
            };

            const firstCard =
                document.querySelector('li[data-occludable-job-id]') ||
                document.querySelector('.jobs-search-results__list-item') ||
                document.querySelector('.job-card-container') ||
                document.querySelector('a[href*="/jobs/view/"]');

            const scroller = firstCard
                ? findScrollableParent(firstCard)
                : (document.scrollingElement || document.documentElement);

            const before = scroller.scrollTop;
            scroller.scrollBy(0, Math.max(700, scroller.clientHeight * 0.85));
            const after = scroller.scrollTop;

            return {
                before,
                after,
                changed: after !== before,
                scrollHeight: scroller.scrollHeight,
                clientHeight: scroller.clientHeight,
                tagName: scroller.tagName,
                className: String(scroller.className || "")
            };
        }
        """
    )


async def extraer_resultados_visibles(page) -> list[dict]:
    """
    Extrae jobs del listado izquierdo acumulando IDs mientras scrollea.
    LinkedIn virtualiza el listado, asÃ­ que una sola lectura del DOM suele traer solo 7-8 cards.
    """

    await page.wait_for_timeout(jitter_ms(1000))

    try:
        await page.wait_for_selector('a[href*="/jobs/view/"]', timeout=8000)
    except Exception:
        return []

    await resetear_scroll_listado(page)
    await page.wait_for_timeout(jitter_ms(600))

    acumulados = {}
    sin_cambios = 0
    ultimo_total = 0
    ultimo_scroll_top = -1

    for intento in range(20):
        actuales = await extraer_resultados_dom_actual(page)

        for job in actuales:
            acumulados[job["id"]] = job

        scroll_info = await scroll_listado_jobs(page)
        await page.wait_for_timeout(jitter_ms(900))

        total_actual = len(acumulados)
        scroll_top = int(scroll_info.get("after") or 0)

        if DEBUG:
            print(
                f"  [SCROLL] intento={intento + 1} "
                f"total={total_actual} "
                f"changed={scroll_info.get('changed')} "
                f"scroll={scroll_info}"
            )

        if total_actual == ultimo_total and scroll_top == ultimo_scroll_top:
            sin_cambios += 1
        else:
            sin_cambios = 0

        ultimo_total = total_actual
        ultimo_scroll_top = scroll_top

        if sin_cambios >= 3:
            break

    # Captura final despuÃ©s del Ãºltimo scroll.
    actuales = await extraer_resultados_dom_actual(page)

    for job in actuales:
        acumulados[job["id"]] = job

    return list(acumulados.values())


# ============================================================
# EXTRACCIÃ“N DEL PANEL DERECHO
# ============================================================

async def abrir_job_visible_en_panel(page, job_id: str, titulo: str = "") -> bool:
    selectores = [
        f'li[data-occludable-job-id="{job_id}"]',
        f'div[data-job-id="{job_id}"]',
        f'a[href*="/jobs/view/{job_id}"]:not([href*="/apply/"])',
    ]

    clicked = False

    for sel in selectores:
        try:
            loc = page.locator(sel).first

            if await loc.count() == 0:
                continue

            await loc.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(jitter_ms(250))
            await loc.click(force=True, timeout=3000)

            clicked = True
            break

        except Exception:
            continue

    if not clicked:
        return False

    for _ in range(25):
        try:
            url_ok = (
                f"currentJobId={job_id}" in page.url or
                f"/jobs/view/{job_id}" in page.url
            )

            panel = await obtener_panel_detalles(page)
            descripcion = await extraer_descripcion_directa(page, panel)

            if descripcion and len(descripcion) >= 80:
                await page.wait_for_timeout(jitter_ms(300))
                return True

            if url_ok and panel is not None:
                await page.wait_for_timeout(jitter_ms(500))
                return True

        except Exception:
            pass

        await page.wait_for_timeout(jitter_ms(300))

    return False


async def expandir_descripcion_si_hace_falta(page):
    selectores = [
        'section.jobs-description button.jobs-description__footer-button',
        'section.jobs-description button[aria-label*="Ver mÃ¡s"]',
        'section.jobs-description button[aria-label*="See more"]',
        'section.jobs-description button[aria-label*="mÃ¡s"]',
        'section.jobs-description button[aria-label*="more"]',
        '.jobs-description button:has-text("Ver mÃ¡s")',
        '.jobs-description button:has-text("Mostrar mÃ¡s")',
        '.jobs-description button:has-text("Show more")',
        '[data-testid="expandable-text-button"]',
    ]

    for sel in selectores:
        try:
            btn = page.locator(sel).first

            if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                await btn.click(force=True, timeout=1500)
                await page.wait_for_timeout(jitter_ms(600))
                return True

        except Exception:
            pass

    return False


async def obtener_panel_detalles(page):
    candidatos = [
        '.jobs-search__job-details--container',
        '.scaffold-layout__detail',
        '.jobs-details__main-content',
        '.jobs-details',
    ]

    for sel in candidatos:
        try:
            loc = page.locator(sel).first

            if await loc.count() == 0:
                continue

            txt = limpiar_texto(await loc.inner_text(timeout=2500))

            if not txt or len(txt) < 80:
                continue

            ruido_listado = [
                "crear alerta",
                "ir al resultado de bÃºsqueda",
                "Â¿estos resultados son Ãºtiles?",
                "siguiente",
            ]

            ruido = sum(1 for s in ruido_listado if s in txt.lower())

            if ruido >= 2:
                continue

            return loc

        except Exception:
            continue

    return None


async def extraer_texto_locator(locator, timeout: int = 1800) -> str:
    try:
        if await locator.count() == 0:
            return ""

        txt = await locator.first.inner_text(timeout=timeout)

        return limpiar_texto(txt)

    except Exception:
        return ""


def recortar_descripcion_desde_panel(panel_texto: str) -> str:
    if not panel_texto:
        return ""

    texto = limpiar_texto(panel_texto)

    patrones_inicio = [
        r"\bAcerca del empleo\b",
        r"\bAbout the job\b",
    ]

    inicio = None

    for patron in patrones_inicio:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            inicio = m.end()
            break

    if inicio is not None:
        texto = texto[inicio:].strip()

    patrones_corte = [
        r"\bAcerca de la empresa\b",
        r"\bAbout the company\b",
        r"\bMeet the hiring team\b",
        r"\bConoce al equipo de contrataciÃ³n\b",
        r"\bMe interesa\b",
        r"\bSolicitar\b",
        r"\bGuardar\b",
        r"\bSet alert\b",
        r"\bCrear alerta\b",
    ]

    fin = len(texto)

    for patron in patrones_corte:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            fin = min(fin, m.start())

    texto = limpiar_descripcion(texto[:fin])

    senales_ruido = [
        "Crear alerta",
        "Ir al resultado de bÃºsqueda",
        "Â¿Estos resultados son Ãºtiles?",
        "Siguiente",
        "Jobs you may be interested in",
    ]

    ruido = sum(1 for s in senales_ruido if s.lower() in texto.lower())

    if ruido >= 2:
        return ""

    if len(texto) < 80:
        return ""

    return texto


async def extraer_descripcion_directa(page, panel=None) -> str:
    await expandir_descripcion_si_hace_falta(page)

    selectores_desc = [
        '#job-details',
        '.jobs-description__content',
        '.jobs-box__html-content',
        '.jobs-description-content__text',
        'article.jobs-description__container',
        'section.jobs-description',
        'div.jobs-description',
    ]

    roots = []

    if panel is not None:
        roots.append(panel)

    roots.append(page)

    for root in roots:
        for sel in selectores_desc:
            try:
                loc = root.locator(sel).first
                txt = await extraer_texto_locator(loc)
                desc = recortar_descripcion_desde_panel(txt)

                if desc and len(desc) >= 80:
                    return desc

            except Exception:
                continue

    if panel is not None:
        try:
            panel_txt = limpiar_texto(await panel.inner_text(timeout=2500))

            if re.search(
                r"\b(Acerca del empleo|About the job)\b",
                panel_txt,
                flags=re.IGNORECASE,
            ):
                desc = recortar_descripcion_desde_panel(panel_txt)

                if desc and len(desc) >= 80:
                    return desc

        except Exception:
            pass

    return ""


async def extraer_header_desde_panel(panel) -> dict:
    data = {
        "empresa": "",
        "ubicacion": "",
        "fecha_publicacion": "",
        "modalidad": "",
        "panel_texto": "",
    }

    try:
        panel_texto = limpiar_texto(await panel.inner_text(timeout=3000))
        data["panel_texto"] = panel_texto
    except Exception:
        return data

    selectores_empresa = [
        '.job-details-jobs-unified-top-card__company-name a',
        '.jobs-unified-top-card__company-name a',
        'a[href*="/company/"]',
    ]

    for sel in selectores_empresa:
        try:
            loc = panel.locator(sel).first

            if await loc.count() > 0:
                empresa = limpiar_texto(await loc.inner_text(timeout=1500))

                if empresa and len(empresa) < 120:
                    data["empresa"] = empresa
                    break

        except Exception:
            continue

    lineas = [x.strip() for x in data["panel_texto"].splitlines() if x.strip()]

    data["fecha_publicacion"] = extraer_fecha_desde_texto(data["panel_texto"])
    data["modalidad"] = extraer_modalidad_desde_texto(data["panel_texto"])

    for linea in lineas[:25]:
        if re.search(
            r"\b(en remoto|remote|remoto|hÃ­brido|hybrid|presencial|on-?site)\b",
            linea,
            re.IGNORECASE,
        ):
            data["ubicacion"] = linea
            break

    if not data["ubicacion"]:
        for linea in lineas[:25]:
            if "Â·" in linea and not re.search(
                r"hace \d+|posted|reposted|solicitantes|applicants",
                linea,
                re.IGNORECASE,
            ):
                if len(linea) < 160:
                    data["ubicacion"] = linea
                    break

    return data


async def extraer_datos_job_desde_panel(page) -> dict:
    panel = await obtener_panel_detalles(page)

    if panel is None:
        return {
            "empresa": "",
            "ubicacion": "",
            "fecha_publicacion": "",
            "modalidad": "",
            "descripcion": "",
            "descripcion_len": 0,
            "extraccion_ok": False,
        }

    header = await extraer_header_desde_panel(panel)
    descripcion = await extraer_descripcion_directa(page, panel)

    return {
        "empresa": header["empresa"],
        "ubicacion": header["ubicacion"],
        "fecha_publicacion": header["fecha_publicacion"],
        "modalidad": header["modalidad"],
        "descripcion": descripcion,
        "descripcion_len": len(descripcion or ""),
        "extraccion_ok": bool(descripcion and len(descripcion) >= 80),
    }


# ============================================================
# PROCESAMIENTO
# ============================================================

async def procesar_pagina_actual(
    page,
    visibles: list[dict],
    start_value: int,
    todas: list[dict],
    seen_ids: set[str],
    busqueda: dict,
) -> int:
    ids = [x["id"] for x in visibles]
    nuevos_visibles = [x for x in visibles if x["id"] not in seen_ids]
    duplicados_visibles = [x for x in visibles if x["id"] in seen_ids]

    print(
        f"\n[PÃGINA start={start_value}] "
        f"visibles={len(visibles)} "
        f"nuevos={len(nuevos_visibles)} "
        f"duplicados={len(duplicados_visibles)} "
        f"ids={ids}"
    )

    nuevos_agregados = 0

    for idx, job in enumerate(visibles, start=1):
        if job["id"] in seen_ids:
            continue

        print(f"[JOB {idx}/{len(visibles)}] {job['titulo'][:90]}")

        empresa = ""
        ubicacion = ""
        fecha_publicacion = ""
        modalidad = ""
        descripcion = ""
        descripcion_len = 0
        extraccion_ok = False

        abierto = await abrir_job_visible_en_panel(
            page,
            job["id"],
            job.get("titulo", ""),
        )

        print(f"  panel abierto: {abierto} url: {page.url}")

        if await linkedin_pide_verificacion(page):
            raise RuntimeError(
                "LinkedIn pidiÃ³ verificaciÃ³n durante la extracciÃ³n. "
                "Detengo el script."
            )

        if abierto:
            datos = await extraer_datos_job_desde_panel(page)

            empresa = datos["empresa"]
            ubicacion = datos["ubicacion"]
            fecha_publicacion = datos["fecha_publicacion"]
            modalidad = datos["modalidad"]
            descripcion = datos["descripcion"]
            descripcion_len = datos.get("descripcion_len", len(descripcion or ""))
            extraccion_ok = datos.get("extraccion_ok", bool(descripcion))

        if not descripcion and DEBUG:
            debug_name = f"sin_descripcion_{job['id']}"
            await page.screenshot(path=f"{debug_name}.png", full_page=True)
            print(f"  [DEBUG] screenshot sin descripciÃ³n: {debug_name}.png")

        oferta = {
            "id": job["id"],
            "titulo": job["titulo"],
            "empresa": empresa,
            "ubicacion": ubicacion,
            "modalidad": modalidad,
            "fecha_publicacion": fecha_publicacion,
            "url": job["url"],
            "busqueda_keywords": busqueda["keywords"],
            "busqueda_ubicacion": busqueda["ubicacion"],
            "categoria": busqueda.get("categoria", ""),
            "pagina_start": start_value,
            "descripcion_len": descripcion_len,
            "extraccion_ok": extraccion_ok,
            "descripcion": descripcion,
        }

        todas.append(oferta)
        guardar_oferta_checkpoint(oferta)
        seen_ids.add(job["id"])

        print(
            f"  empresa={empresa[:40]} | "
            f"ubicacion={ubicacion[:50]} | "
            f"fecha={fecha_publicacion} | "
            f"modalidad={modalidad} | "
            f"desc_len={descripcion_len} | "
            f"ok={extraccion_ok}"
        )
        print(f"  descripcion_inicio={descripcion[:120]!r}")

        nuevos_agregados += 1

        if len(todas) >= LIMITE_RESULTADOS:
            print(f"âœ… Alcanzado lÃ­mite de {LIMITE_RESULTADOS} ofertas Ãºnicas.")
            return nuevos_agregados

        await asyncio.sleep(jitter_seconds(1.2))

    return nuevos_agregados


def exportar_resultados(ofertas: list[dict], nombre_archivo: str):
    if not ofertas:
        print("âš  No hay ofertas para exportar.")
        return

    df = pd.DataFrame(ofertas).drop_duplicates(subset=["id"])

    columnas_orden = [
        c for c in ["categoria", "busqueda_keywords", "pagina_start", "titulo"]
        if c in df.columns
    ]

    if columnas_orden:
        df = df.sort_values(columnas_orden)

    df_excel = sanitizar_dataframe_para_excel(df)

    excel_path = Path(nombre_archivo + ".xlsx")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_excel.to_excel(writer, index=False, sheet_name="Ofertas")
        ws = writer.sheets["Ofertas"]

        widths = {
            "A": 14,    # id
            "B": 55,    # titulo
            "C": 28,    # empresa
            "D": 35,    # ubicacion
            "E": 16,    # modalidad
            "F": 22,    # fecha_publicacion
            "G": 55,    # url
            "H": 32,    # busqueda_keywords
            "I": 22,    # busqueda_ubicacion
            "J": 24,    # categoria
            "K": 12,    # pagina_start
            "L": 16,    # descripcion_len
            "M": 14,    # extraccion_ok
            "N": 100,   # descripcion
        }

        for col, ancho in widths.items():
            ws.column_dimensions[col].width = ancho

        from openpyxl.styles import Font

        for cell in ws[1]:
            cell.font = Font(bold=True)

    json_path = Path(nombre_archivo + ".json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ofertas, f, ensure_ascii=False, indent=2)

    print(f"\nâœ… Excel RAW: {excel_path}")
    print(f"âœ… JSON RAW:  {json_path}")
    print(f"âœ… Total exportado: {len(df)}")


# ============================================================
# MAIN
# ============================================================

async def run_linkedin_scrape() -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("LinkedIn Job Scraper â€” Backend Python RAW")
    print("=" * 60)

    print(f"ARCHIVO EJECUTADO: {Path(__file__).resolve()}")
    busquedas = load_profile_busquedas()
    random.shuffle(busquedas)
    print("BUSQUEDAS ACTIVAS:")
    for b in busquedas:
        print(
            f" - {b['keywords']} â€” {b['ubicacion']} "
            f"(freshness={b.get('freshness_window_seconds', FRESHNESS_WINDOW_SECONDS)}s)"
        )

    async with async_playwright() as p:
        context, page = await crear_contexto_linkedin(p)

        try:
            await asegurar_sesion_manual(page)

            todas, seen_ids = cargar_checkpoint()

            for busqueda in busquedas:
                print("\n" + "=" * 70)
                print(f"INICIANDO BÃšSQUEDA: {busqueda['keywords']} â€” {busqueda['ubicacion']}")
                print("=" * 70)

                paginas_sin_nuevos = 0

                for pagina in range(MAX_PAGINAS):
                    start = pagina * 25
                    params = build_linkedin_search_params(busqueda, start)

                    url = f"{LINKEDIN_JOBS_URL}?{urlencode(params)}"

                    print(
                        f"\nðŸ” Buscando: "
                        f"{busqueda['keywords']} â€” "
                        f"{busqueda['ubicacion']} â€” "
                        f"start={start}"
                    )

                    await navegar_estable(page, url)
                    await page.wait_for_timeout(jitter_ms(2500))

                    if await linkedin_pide_verificacion(page):
                        raise RuntimeError(
                            "LinkedIn pidiÃ³ verificaciÃ³n durante la navegaciÃ³n. "
                            "Detengo el script."
                        )

                    sin_resultados_reales = await pagina_sin_resultados_reales(page)

                    if DEBUG:
                        safe_kw = re.sub(
                            r"[^a-zA-Z0-9_-]+",
                            "_",
                            busqueda["keywords"],
                        )
                        await dump_debug_info(page, f"debug_{safe_kw}_{start}")

                    if sin_resultados_reales:
                        print("â›” LinkedIn indica que no hay mÃ¡s resultados para esta bÃºsqueda.")
                        break

                    visibles = await extraer_resultados_visibles(page)

                    if not visibles:
                        print("â›” No hay jobs visibles en esta pÃ¡gina. Cambio de bÃºsqueda.")
                        break

                    nuevos = await procesar_pagina_actual(
                        page=page,
                        visibles=visibles,
                        start_value=start,
                        todas=todas,
                        seen_ids=seen_ids,
                        busqueda=busqueda,
                    )

                    guardar_estado_checkpoint(busqueda, start, len(todas))

                    if EXPORTAR_SNAPSHOT_CADA_PAGINA and nuevos > 0:
                        exportar_snapshot_resultados(todas)

                    if nuevos == 0:
                        paginas_sin_nuevos += 1
                        print(
                            f"âš  PÃ¡gina sin resultados nuevos. "
                            f"consecutivas={paginas_sin_nuevos}"
                        )
                    else:
                        paginas_sin_nuevos = 0

                    if paginas_sin_nuevos >= PAGINAS_CONSECUTIVAS_SIN_NUEVOS:
                        print("â›” BÃºsqueda agotada: pÃ¡ginas consecutivas sin ofertas nuevas.")
                        break

                    if len(todas) >= LIMITE_RESULTADOS:
                        break

                if len(todas) >= LIMITE_RESULTADOS:
                    break

            print("\nANTES DE EXPORTAR")
            exportar_resultados(todas, ARCHIVO_SALIDA)
            return pd.DataFrame(deduplicar_ofertas(todas))

        finally:
            await context.close()


async def main():
    await run_linkedin_scrape()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\nâ›” EjecuciÃ³n interrumpida manualmente.")
        print(f"âœ… Lo procesado hasta ahora quedÃ³ en: {CHECKPOINT_JSONL}")
        print(f"âœ… Ãšltimo estado guardado en: {CHECKPOINT_STATE}")

    except RuntimeError as e:
        print("\nâ›” EjecuciÃ³n detenida.")
        print(str(e))
        print(f"âœ… Lo procesado hasta ahora quedÃ³ en: {CHECKPOINT_JSONL}")
        print(f"âœ… Ãšltimo estado guardado en: {CHECKPOINT_STATE}")

    except Exception as e:
        print("\nâŒ Error inesperado.")
        print(repr(e))
        print(f"âœ… Lo procesado hasta ahora quedÃ³ en: {CHECKPOINT_JSONL}")
        print(f"âœ… Ãšltimo estado guardado en: {CHECKPOINT_STATE}")
