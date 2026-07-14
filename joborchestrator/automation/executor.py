from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urljoin

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from joborchestrator.automation.adapters import AdapterRegistry
from joborchestrator.automation.accounts import load_password, site_identity_from_url
from joborchestrator.storage import persistence as db

Progress = Callable[[str], None]

CHALLENGE_MARKERS = ("captcha", "challenge", "checkpoint", "verify you are human", "security check")
LOGIN_MARKERS = ("sign in", "log in", "login", "create account", "register to apply")
APPLY_TEXT_RE = re.compile(
    r"\b(apply|apply now|start application|continue application|submit application|aplicar|solicitar|postular|postularme|enviar candidatura)\b",
    re.IGNORECASE,
)
FORM_MARKERS_RE = re.compile(r"<(form|input|textarea|select)\b", re.IGNORECASE)


async def run_application_execution(
    *,
    session_id: int,
    job_id: int,
    apply_url: str,
    provider_hint: str = "generic",
    dry_run: bool = True,
    progress: Progress | None = None,
) -> dict[str, Any]:
    if not apply_url:
        raise RuntimeError("application_execution requires an apply_url.")
    _progress(progress, "Opening external application URL.")
    headless = os.getenv("APPLICATION_BROWSER_HEADLESS", "1") != "0"
    timeout_ms = int(os.getenv("APPLICATION_BROWSER_TIMEOUT_MS", "30000"))
    profile_dir = os.getenv("APPLICATION_BROWSER_PROFILE_DIR")
    async with async_playwright() as p:
        browser: Browser | None = None
        context: BrowserContext | None = None
        if profile_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await _safe_network_idle(page, timeout_ms)
            navigation = await _follow_apply_hops(page, timeout_ms=timeout_ms, max_hops=2, progress=progress)
            html = await page.content()
            url = page.url
            live_page = page
            live_browser = browser
            live_context = context
            browser = None
            context = None
        finally:
            if browser is not None:
                await browser.close()
            if context is not None:
                await context.close()

    if _looks_blocked(apply_url, html):
        await _close_browser_or_context(live_browser, live_context)
        identity = site_identity_from_url(url, provider_hint)
        db.upsert_automation_site_account(
            {"provider": identity.provider, "domain": identity.domain, "status": "blocked", "notes": "Challenge or CAPTCHA detected."}
        )
        db.transition_application_session(
            session_id,
            "preflight",
            {"note": "Application page opened but requires human verification.", "last_error": "Challenge or CAPTCHA detected."},
        )
        session = db.transition_application_session(
            session_id,
            "needs_user_input",
            {
                "note": "Human verification required.",
                "last_error": "Challenge or CAPTCHA detected.",
                "artifacts_json": {"url": apply_url, "provider_hint": provider_hint, "navigation": navigation},
            },
        )
        return {"session": session, "blocked": True, "reason": "challenge_detected"}

    if _looks_login_required(html):
        identity = site_identity_from_url(url, provider_hint)
        login_result = await try_saved_login(live_page, identity.provider, identity.domain, timeout_ms=timeout_ms, progress=progress)
        if login_result["ok"]:
            navigation.append({"action": "auto_login", "url": live_page.url, "text": str(login_result["username"])})
            await _safe_network_idle(live_page, timeout_ms)
            navigation.extend(await _follow_apply_hops(live_page, timeout_ms=timeout_ms, max_hops=2, progress=progress))
            html = await live_page.content()
            url = live_page.url
            if _looks_login_required(html):
                await _close_browser_or_context(live_browser, live_context)
                db.upsert_automation_site_account(
                    {
                        "provider": identity.provider,
                        "domain": identity.domain,
                        "status": "needs_login",
                        "browser_profile_ref": os.getenv("APPLICATION_BROWSER_PROFILE_DIR"),
                        "notes": "Saved credentials did not clear login.",
                    }
                )
                db.transition_application_session(
                    session_id,
                    "preflight",
                    {"note": "Saved credentials did not clear login.", "last_error": "Login required."},
                )
                session = db.transition_application_session(
                    session_id,
                    "needs_user_input",
                    {
                        "note": "Login still required after saved credential attempt.",
                        "last_error": "Login required.",
                        "artifacts_json": {"url": url, "provider_hint": provider_hint, "navigation": navigation},
                    },
                )
                return {"session": session, "blocked": True, "reason": "login_required"}
        else:
            await _close_browser_or_context(live_browser, live_context)
            db.upsert_automation_site_account(
                {
                    "provider": identity.provider,
                    "domain": identity.domain,
                    "status": "needs_login",
                    "browser_profile_ref": os.getenv("APPLICATION_BROWSER_PROFILE_DIR"),
                    "notes": str(login_result["reason"]),
                }
            )
            db.transition_application_session(
                session_id,
                "preflight",
                {"note": "Application page requires login/account creation.", "last_error": "Login required."},
            )
            session = db.transition_application_session(
                session_id,
                "needs_user_input",
                {
                    "note": "Login or account creation required before automation can continue.",
                    "last_error": "Login required.",
                    "artifacts_json": {"url": url, "provider_hint": provider_hint, "navigation": navigation, "login_attempt": login_result},
                },
            )
            return {"session": session, "blocked": True, "reason": "login_required"}

    job = db.get_job_posting(job_id) or {}
    registry = AdapterRegistry()
    adapter = registry.detect(html, {**job, "apply_url": apply_url, "url": apply_url, "source": provider_hint})
    _progress(progress, f"Detected provider: {adapter.provider}.")
    identity = site_identity_from_url(url, adapter.provider)
    db.upsert_automation_site_account(
        {
            "provider": identity.provider,
            "domain": identity.domain,
            "status": "ready",
            "browser_profile_ref": os.getenv("APPLICATION_BROWSER_PROFILE_DIR"),
        }
    )
    live_fill = None
    try:
        schema = adapter.extract_form_schema_html(html)
        mapping = adapter.map_answers(schema, db.get_candidate_profile_payload() or {}, db.list_answer_definitions())
        if adapter.provider == "greenhouse":
            _progress(progress, "Filling safe Greenhouse fields in dry-run mode.")
            live_fill = await fill_safe_fields_on_page(live_page, mapping, dry_run=dry_run)
            html = await live_page.content()
    finally:
        await _close_browser_or_context(live_browser, live_context)
    fill = adapter.fill_fields_html(html, mapping, dry_run=dry_run)
    if live_fill is not None:
        fill.data["fields_autofilled"] = live_fill["fields_autofilled"]
        fill.data["filled_fields"] = live_fill["filled_fields"]
        fill.data["skipped_fields"] = live_fill["skipped_fields"]
    review = adapter.prepare_review(schema, mapping, fill)
    next_state = "needs_user_input" if mapping.get("unknown_fields") else "ready_for_review"

    _advance_to_ready_to_fill(
        session_id,
        {
            "note": f"Opened {adapter.provider} application page.",
            "current_step": "provider_detected",
            "browser_session_ref": url,
            "form_schema_json": schema,
            "mapped_answers_json": mapping,
            "artifacts_json": {"navigation": navigation, "opened_url": apply_url, "final_url": url},
        },
    )
    db.transition_application_session(
        session_id,
        "filling",
        {
            "note": "Ran browser dry-run fill.",
            "current_step": "dry_run_fill",
            "fields_detected": review["fields_detected"],
            "fields_autofilled": review["fields_autofilled"],
            "unknown_fields_json": review["unknown_fields"],
            "requires_review": True,
        },
    )
    session = db.transition_application_session(
        session_id,
        next_state,
        {
            "note": "Ready for review." if next_state == "ready_for_review" else "Missing fields require user input.",
            "current_step": "review",
            "artifacts_json": {"review": review, "dry_run": dry_run, "final_url": url, "navigation": navigation},
        },
    )
    return {
        "session": session,
        "provider": adapter.provider,
        "fields_detected": review["fields_detected"],
        "fields_autofilled": review["fields_autofilled"],
        "unknown_fields": len(review["unknown_fields"]),
        "navigation": navigation,
    }


def _looks_blocked(url: str, html: str) -> bool:
    text = f"{url}\n{html[:5000]}".lower()
    return any(marker in text for marker in CHALLENGE_MARKERS)


def _looks_login_required(html: str) -> bool:
    text = html[:5000].lower()
    return any(marker in text for marker in LOGIN_MARKERS)


def find_apply_links(html: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", html, re.IGNORECASE | re.DOTALL):
        attrs = match.group("attrs")
        body = _clean_text(match.group("body"))
        aria = _attr(attrs, "aria-label") or ""
        title = _attr(attrs, "title") or ""
        href = _attr(attrs, "href")
        text = " ".join(part for part in [body, aria, title] if part).strip()
        if not href or not APPLY_TEXT_RE.search(text):
            continue
        url = urljoin(base_url, href)
        if url not in seen:
            seen.add(url)
            links.append({"url": url, "text": text[:120]})
    return links


async def _follow_apply_hops(
    page: Page,
    *,
    timeout_ms: int,
    max_hops: int,
    progress: Progress | None,
) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = [{"action": "opened", "url": page.url}]
    for hop in range(max_hops):
        html = await page.content()
        if _looks_blocked(page.url, html) or _looks_login_required(html):
            steps.append({"action": "blocked", "url": page.url})
            break
        if _has_form(html):
            steps.append({"action": "form_detected", "url": page.url})
            break
        link = _best_apply_link(html, page.url)
        if link:
            _progress(progress, f"Following intermediate apply link: {link['text']}.")
            await page.goto(link["url"], wait_until="domcontentloaded", timeout=timeout_ms)
            await _safe_network_idle(page, timeout_ms)
            steps.append({"action": "followed_link", "url": page.url, "text": link["text"]})
            continue
        clicked = await _click_apply_control(page, timeout_ms=timeout_ms)
        if clicked:
            _progress(progress, f"Clicked intermediate apply control: {clicked}.")
            await _safe_network_idle(page, timeout_ms)
            steps.append({"action": "clicked_control", "url": page.url, "text": clicked})
            continue
        steps.append({"action": "no_apply_control", "url": page.url})
        break
    return steps


async def _click_apply_control(page: Page, *, timeout_ms: int) -> str | None:
    labels = [
        "Apply now",
        "Apply",
        "Start application",
        "Continue application",
        "Aplicar",
        "Solicitar",
        "Postularme",
        "Postular",
    ]
    for label in labels:
        locator = page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE)).first
        try:
            if await locator.count() > 0:
                await locator.click(timeout=min(timeout_ms, 5000))
                return label
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None


async def _safe_network_idle(page: Page, timeout_ms: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return


async def _close_browser_or_context(browser: Browser | None, context: BrowserContext | None) -> None:
    if context is not None:
        await context.close()
    elif browser is not None:
        await browser.close()


def _advance_to_ready_to_fill(session_id: int, payload: dict[str, Any]) -> None:
    session = db.get_application_session(session_id)
    state = str((session or {}).get("state") or "created")
    if state == "created":
        db.transition_application_session(session_id, "preflight", payload)
        db.transition_application_session(
            session_id,
            "ready_to_fill",
            {**payload, "note": "Preflight complete. Ready to fill safe fields."},
        )
        return
    if state == "preflight":
        db.transition_application_session(session_id, "ready_to_fill", payload)
        return
    if state == "needs_user_input":
        db.transition_application_session(
            session_id,
            "ready_to_fill",
            {**payload, "note": "Continuing after manual input."},
        )
        return
    if state == "failed":
        db.transition_application_session(session_id, "preflight", payload)
        db.transition_application_session(session_id, "ready_to_fill", payload)


def _best_apply_link(html: str, base_url: str) -> dict[str, str] | None:
    links = find_apply_links(html, base_url)
    if not links:
        return None
    ats_priority = ("greenhouse", "grnh.se", "lever.co", "ashbyhq", "workday")
    return sorted(
        links,
        key=lambda item: (
            not any(marker in item["url"].lower() for marker in ats_priority),
            len(item["url"]),
        ),
    )[0]


def _has_form(html: str) -> bool:
    return bool(FORM_MARKERS_RE.search(html))


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
    return match.group(1) if match else None


def _clean_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _progress(progress: Progress | None, message: str) -> None:
    if progress:
        progress(message)


def safe_fill_plan(mapping: dict[str, Any]) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for answer in mapping.get("answers") or []:
        if answer.get("requires_confirmation"):
            continue
        value = str(answer.get("value") or "").strip()
        field_name = str(answer.get("field_name") or "").strip()
        canonical = str(answer.get("canonical_key") or "").strip()
        if not value or not field_name:
            continue
        if canonical not in {"full_name", "email", "phone", "linkedin", "portfolio"}:
            continue
        plan.append({"field_name": field_name, "value": value, "canonical_key": canonical})
    return plan


async def try_saved_login(
    page: Page,
    provider: str,
    domain: str,
    *,
    timeout_ms: int,
    progress: Progress | None = None,
) -> dict[str, Any]:
    account = db.get_automation_site_account(provider, domain) or db.get_automation_site_account("generic", domain)
    if not account or not account.get("username"):
        return {"ok": False, "reason": "No saved username for this domain."}
    username = str(account["username"])
    password = load_password(account.get("password_ref"), username)
    if not password:
        return {"ok": False, "reason": "No saved password available for this domain.", "username": username}
    _progress(progress, f"Trying saved login for {domain}.")
    username_locator = await _first_visible_locator(
        page,
        [
            'input[type="email"]',
            'input[name*="email" i]',
            'input[id*="email" i]',
            'input[name*="user" i]',
            'input[id*="user" i]',
            'input[autocomplete="username"]',
        ],
    )
    password_locator = await _first_visible_locator(
        page,
        [
            'input[type="password"]',
            'input[name*="password" i]',
            'input[id*="password" i]',
            'input[autocomplete="current-password"]',
        ],
    )
    if username_locator is None or password_locator is None:
        return {"ok": False, "reason": "Could not find login fields.", "username": username}
    try:
        await username_locator.fill(username, timeout=3000)
        await password_locator.fill(password, timeout=3000)
        submit = await _first_visible_locator(
            page,
            [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Sign in")',
                'button:has-text("Log in")',
                'button:has-text("Login")',
                'button:has-text("Continue")',
                'button:has-text("Ingresar")',
            ],
        )
        if submit is not None:
            await submit.click(timeout=5000)
        else:
            await password_locator.press("Enter", timeout=3000)
        await page.wait_for_timeout(1500)
        await _safe_network_idle(page, timeout_ms)
        db.upsert_automation_site_account(
            {
                "provider": provider,
                "domain": domain,
                "status": "ready",
                "username": username,
                "last_login_at": datetime.now().isoformat(timespec="seconds"),
                "browser_profile_ref": os.getenv("APPLICATION_BROWSER_PROFILE_DIR"),
            }
        )
        return {"ok": True, "username": username}
    except Exception as exc:
        return {"ok": False, "reason": f"Saved login failed: {exc}", "username": username}


async def fill_safe_fields_on_page(page: Page, mapping: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    filled: list[str] = []
    skipped: list[str] = []
    for item in safe_fill_plan(mapping):
        field_name = item["field_name"]
        value = item["value"]
        selectors = [
            f'input[name="{field_name}"]',
            f'textarea[name="{field_name}"]',
            f'input[id="{field_name}"]',
            f'textarea[id="{field_name}"]',
        ]
        locator = None
        for selector in selectors:
            candidate = page.locator(selector).first
            try:
                if await candidate.count() > 0:
                    locator = candidate
                    break
            except Exception:
                continue
        if locator is None:
            skipped.append(field_name)
            continue
        try:
            await locator.fill(value, timeout=3000)
            if dry_run:
                await locator.evaluate(
                    """element => {
                        element.setAttribute('data-joborchestrator-dry-run', 'filled');
                    }"""
                )
            filled.append(field_name)
        except Exception:
            skipped.append(field_name)
    return {
        "dry_run": dry_run,
        "fields_autofilled": len(filled),
        "filled_fields": filled,
        "skipped_fields": skipped,
    }


async def _first_visible_locator(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None
