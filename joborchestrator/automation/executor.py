from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from joborchestrator.automation.adapters import AdapterRegistry
from joborchestrator.automation.accounts import load_password, site_identity_from_url
from joborchestrator.automation import local_browser_agent
from joborchestrator.automation.journey import ApplicationJourneyEngine
from joborchestrator.automation.validation import validate_application_surface
from joborchestrator.intelligence.llm_application_materials import export_ats_cv_pdf_bytes
from joborchestrator.storage import persistence as db

Progress = Callable[[str], None]

CHALLENGE_MARKERS = (
    "checkpoint",
    "verify you are human",
    "security check",
    "human verification",
    "cloudflare challenge",
    "please complete the captcha",
    "captcha-delivery",
    "access is temporarily restricted",
    "you have been blocked",
    "detected unusual activity",
)
LOGIN_MARKERS = ("sign in", "log in", "login", "create account", "register to apply")
APPLY_TEXT_RE = re.compile(
    r"\b(apply|apply now|i'?m interested|start application|continue application|submit application|aplicar|solicitar|postular|postularme|enviar candidatura)\b",
    re.IGNORECASE,
)
FORBIDDEN_SUBMIT_TEXT_RE = re.compile(
    r"\b(submit application|send application|complete application|finish|submit|enviar candidatura|enviar solicitud|finalizar)\b",
    re.IGNORECASE,
)
SAFE_STEP_TEXT_RE = re.compile(
    r"\b(next|continue|save and continue|review|review application|siguiente|continuar|revisar)\b",
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
    handoff_timeout_seconds = int(os.getenv("APPLICATION_BROWSER_HANDOFF_TIMEOUT_SECONDS", "3600"))
    profile_dir = os.getenv("APPLICATION_BROWSER_PROFILE_DIR")
    existing_session = db.get_application_session(session_id) or {}
    browser_ref = str(existing_session.get("browser_session_ref") or "")
    resumed_session = await local_browser_agent.get_session(browser_ref)
    playwright_manager = None
    playwright_instance = None
    if resumed_session:
        live_page = resumed_session.page
        live_browser = resumed_session.browser
        live_context = resumed_session.context
        navigation = [{"action": "resumed_browser_session", "url": live_page.url}]
        html = await live_page.content()
        url = live_page.url
    else:
        playwright_manager = async_playwright()
        playwright_instance = await playwright_manager.start()
        p = playwright_instance
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            if profile_dir:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=headless,
                )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                browser = await p.chromium.launch(headless=headless)
                page = await browser.new_page()
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
            if (browser is not None or context is not None) and playwright_instance is not None:
                await playwright_instance.stop()

    access_issue = await _detect_page_access_issue(live_page, apply_url, html)
    if access_issue == "posting_unavailable":
        await _close_browser_or_context(live_browser, live_context)
        if playwright_instance is not None:
            await playwright_instance.stop()
        db.transition_application_session(
            session_id,
            "preflight",
            {"note": "Application posting appears to be closed or unavailable.", "last_error": "Posting unavailable."},
        )
        session = db.transition_application_session(
            session_id,
            "needs_user_input",
            {
                "note": "Application posting is closed, removed, or unavailable.",
                "last_error": "Posting unavailable.",
                "artifacts_json": {"url": apply_url, "provider_hint": provider_hint, "navigation": navigation},
            },
        )
        return {"session": session, "blocked": False, "reason": "posting_unavailable"}

    if access_issue == "challenge_detected":
        await _close_browser_or_context(live_browser, live_context)
        if playwright_instance is not None:
            await playwright_instance.stop()
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
                if playwright_instance is not None:
                    await playwright_instance.stop()
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
            if playwright_instance is not None:
                await playwright_instance.stop()
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
    capabilities = adapter.capabilities()
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
    resume_upload: dict[str, Any] = {"status": "not_attempted"}
    forbidden_submit_controls: list[dict[str, str]] = []
    handoff: dict[str, Any] = {"status": "disabled"}
    auto_submit_result: dict[str, Any] = {"status": "disabled"}
    journey_step: dict[str, Any] = {}
    validation_report: dict[str, Any] = {"status": "not_attempted"}
    repair_report: dict[str, Any] = {"status": "not_attempted"}
    automation_metrics: dict[str, Any] = {}
    try:
        journey_engine = ApplicationJourneyEngine()
        profile = db.get_candidate_profile_payload() or {}
        answer_bank = db.list_answer_definitions()
        current_step = await journey_engine.prepare_initial_step(
            page=live_page,
            adapter=adapter,
            capabilities=capabilities,
            html=html,
            profile=profile,
            answer_bank=answer_bank,
        )
        live_fill = {"dry_run": dry_run, "fields_autofilled": 0, "filled_fields": [], "skipped_fields": []}
        journey_steps: list[dict[str, Any]] = []
        step_transitions: list[dict[str, Any]] = []
        max_auto_steps = max(1, int(os.getenv("APPLICATION_MAX_AUTO_STEPS", "3")))
        for step_index in range(max_auto_steps):
            schema = current_step.schema
            mapping = current_step.mapping
            journey_step = current_step.to_dict()
            browser_surface = current_step.browser_surface
            if capabilities.can_fill_text_fields or capabilities.can_fill_selects or capabilities.can_fill_radios or capabilities.can_fill_checkboxes:
                _progress(
                    progress,
                    f"Filling safe {adapter.provider} fields in dry-run mode." if dry_run else f"Filling safe {adapter.provider} fields.",
                )
                step_fill = await fill_safe_fields_on_page(browser_surface, mapping, dry_run=dry_run)
                _merge_fill_result(live_fill, step_fill)
            if capabilities.can_upload_resume and resume_upload.get("status") != "uploaded":
                resume_upload = await upload_resume_on_page(
                    browser_surface,
                    schema,
                    resolve_resume_upload_file(job_id, job),
                )
                if resume_upload.get("status") == "uploaded":
                    live_fill["fields_autofilled"] = int(live_fill.get("fields_autofilled") or 0) + 1
                    live_fill.setdefault("filled_fields", []).append(str(resume_upload.get("field_name") or "resume"))
                    _remove_resolved_file_unknowns(mapping)
            if capabilities.can_detect_fields:
                validation = await validate_application_surface(browser_surface, journey_step.get("action_plan") or {})
                validation_report = validation.to_dict()
                if validation.status == "validation_failed":
                    mapping.setdefault("unknown_fields", []).append(
                        {
                            "name": "validation",
                            "label": "Validation errors or failed postconditions were detected after autofill.",
                            "type": "validation",
                            "required": True,
                            "sensitive": False,
                            "classification": "unknown",
                            "issues": validation_report.get("issues") or [],
                        }
                    )
                rescanned_step = await journey_engine.inspect_surface(
                    adapter=adapter,
                    capabilities=capabilities,
                    surface=current_step.surface,
                    browser_surface=browser_surface,
                    html=html,
                    profile=profile,
                    answer_bank=answer_bank,
                    surfaces=current_step.surfaces,
                )
                dynamic_required_fields = _append_dynamic_required_unknowns(
                    mapping,
                    previous_schema=schema,
                    rescanned_schema=rescanned_step.schema,
                )
                repair_report = _build_repair_report(
                    previous_action_plan=journey_step.get("action_plan") or {},
                    rescanned_action_plan=rescanned_step.to_dict().get("action_plan") or {},
                    dynamic_required_fields=dynamic_required_fields,
                )
                if dynamic_required_fields:
                    schema = rescanned_step.schema
                    journey_step = {
                        **journey_step,
                        "repair_rescan": rescanned_step.to_dict(),
                    }
                transition = await detect_safe_step_transition_controls(browser_surface)
                automation_metrics = _build_application_automation_metrics(
                    action_plan=journey_step.get("action_plan") or {},
                    validation_report=validation_report,
                    fill_result=live_fill,
                    resume_upload=resume_upload,
                    repair_report=repair_report,
                    mapping=mapping,
                    step_transitions=step_transitions,
                )
                journey_steps.append(
                    {
                        "index": step_index,
                        "surface": current_step.surface.to_dict(),
                        "action_plan": journey_step.get("action_plan") or {},
                        "validation": validation_report,
                        "repair": repair_report,
                        "transition": transition,
                    }
                )
                if mapping.get("unknown_fields") or validation.status != "validation_clean":
                    break
                if transition.get("status") != "available":
                    break
                click_result = await click_safe_step_transition(browser_surface, transition, timeout_ms=timeout_ms)
                step_transitions.append({"index": step_index, "transition": transition, "result": click_result})
                journey_steps[-1]["transition_result"] = click_result
                if click_result.get("status") != "advanced":
                    break
                html = await live_page.content()
                url = live_page.url
                current_step = await journey_engine.prepare_initial_step(
                    page=live_page,
                    adapter=adapter,
                    capabilities=capabilities,
                    html=html,
                    profile=profile,
                    answer_bank=answer_bank,
                )
                continue
            break
        journey_step = {**journey_step, "steps": journey_steps, "step_transitions": step_transitions}
        automation_metrics = _build_application_automation_metrics(
            action_plan=journey_step.get("action_plan") or {},
            validation_report=validation_report,
            fill_result=live_fill,
            resume_upload=resume_upload,
            repair_report=repair_report,
            mapping=mapping,
            step_transitions=step_transitions,
        )
        if capabilities.can_detect_fields:
            forbidden_submit_controls = await detect_forbidden_submit_controls(browser_surface)
            auto_submit_result = await maybe_auto_submit_application(
                live_page,
                session=existing_session,
                provider=adapter.provider,
                apply_url=apply_url,
                job=job,
                schema=schema,
                mapping=mapping,
                resume_upload=resume_upload,
                forbidden_submit_controls=forbidden_submit_controls,
                dry_run=dry_run,
                timeout_ms=timeout_ms,
                progress=progress,
            )
            try:
                html = await live_page.content()
                url = live_page.url
            except Exception:
                if auto_submit_result.get("status") != "submitted":
                    raise
    finally:
        cleanup_path = resume_upload.get("cleanup_path")
        if cleanup_path:
            _cleanup_resume_upload_file(str(cleanup_path))
        if local_browser_agent.enabled() and auto_submit_result.get("status") != "submitted":
            session = await local_browser_agent.get_session(browser_ref)
            if session is None:
                session = local_browser_agent.register_session(
                    page=live_page,
                    browser=live_browser,
                    context=live_context,
                    playwright=playwright_instance,
                    provider=adapter.provider,
                    session_id=session_id,
                    job_id=job_id,
                    timeout_seconds=handoff_timeout_seconds,
                )
            handoff = {"status": "started", **local_browser_agent.public_metadata(session)}
        else:
            await _close_browser_or_context(live_browser, live_context)
            if playwright_instance is not None:
                await playwright_instance.stop()
    fill = adapter.fill_fields_html(html, mapping, dry_run=dry_run)
    if live_fill is not None:
        fill.data["fields_autofilled"] = live_fill["fields_autofilled"]
        fill.data["filled_fields"] = live_fill["filled_fields"]
        fill.data["skipped_fields"] = live_fill["skipped_fields"]
    review = adapter.prepare_review(schema, mapping, fill)
    next_state = "needs_user_input" if mapping.get("unknown_fields") else "ready_for_review"
    if auto_submit_result.get("status") == "submitted":
        next_state = "submitted"

    _advance_to_ready_to_fill(
        session_id,
        {
            "note": f"Opened {adapter.provider} application page.",
            "current_step": "provider_detected",
            "browser_session_ref": handoff.get("ref") or browser_ref or url,
            "form_schema_json": schema,
            "mapped_answers_json": mapping,
            "artifacts_json": {
                "navigation": navigation,
                "opened_url": apply_url,
                "final_url": url,
                "resume_upload": _public_resume_upload_result(resume_upload),
                "forbidden_submit_controls": forbidden_submit_controls,
                "browser_handoff": handoff,
                "auto_submit": auto_submit_result,
                "journey": journey_step,
                "action_plan": journey_step.get("action_plan") or {},
                "validation": validation_report,
                "repair": repair_report,
                "automation_metrics": automation_metrics,
            },
        },
    )
    db.transition_application_session(
        session_id,
        "filling",
        {
            "note": "Ran browser dry-run fill." if dry_run else "Ran browser fill.",
            "current_step": "dry_run_fill" if dry_run else "fill",
            "fields_detected": review["fields_detected"],
            "fields_autofilled": review["fields_autofilled"],
            "unknown_fields_json": review["unknown_fields"],
            "requires_review": True,
        },
    )
    final_artifacts = {
        "review": review,
        "dry_run": dry_run,
        "final_url": url,
        "navigation": navigation,
        "resume_upload": _public_resume_upload_result(resume_upload),
        "forbidden_submit_controls": forbidden_submit_controls,
        "browser_handoff": handoff,
        "auto_submit": auto_submit_result,
        "journey": journey_step,
        "action_plan": journey_step.get("action_plan") or {},
        "validation": validation_report,
        "repair": repair_report,
        "automation_metrics": automation_metrics,
    }
    if next_state == "submitted":
        db.transition_application_session(
            session_id,
            "ready_for_review",
            {"note": "Auto-submit preconditions passed.", "current_step": "auto_submit_ready", "artifacts_json": final_artifacts},
        )
        db.transition_application_session(
            session_id,
            "approved",
            {"note": "Approved by auto_submit_approved mode.", "current_step": "auto_submit_approved"},
        )
        db.transition_application_session(
            session_id,
            "submitting",
            {"note": "Submitting approved application.", "current_step": "auto_submit"},
        )
        session = db.transition_application_session(
            session_id,
            "submitted",
            {"note": "Auto-submit completed.", "current_step": "submitted", "artifacts_json": final_artifacts},
        )
    else:
        session = db.transition_application_session(
            session_id,
            next_state,
            {
                "note": "Ready for review." if next_state == "ready_for_review" else "Missing fields require user input.",
                "current_step": "review",
                "artifacts_json": final_artifacts,
            },
        )
    return {
        "session": session,
        "provider": adapter.provider,
        "fields_detected": review["fields_detected"],
        "fields_autofilled": review["fields_autofilled"],
        "unknown_fields": len(review["unknown_fields"]),
        "resume_upload": _public_resume_upload_result(resume_upload),
        "forbidden_submit_controls": forbidden_submit_controls,
        "browser_handoff": handoff,
        "auto_submit": auto_submit_result,
        "navigation": navigation,
    }


def _looks_blocked(url: str, html: str) -> bool:
    text = f"{url}\n{html[:5000]}".lower()
    has_application_form = 'id="application_form"' in text or "id='application_form'" in text
    if has_application_form:
        return any(
            marker in text
            for marker in ("checkpoint", "verify you are human", "security check", "human verification", "cloudflare challenge")
        )
    return any(marker in text for marker in CHALLENGE_MARKERS)


async def _detect_page_access_issue(page: Page, url: str, html: str) -> str | None:
    if _looks_posting_unavailable(url, html):
        return "posting_unavailable"
    if _looks_blocked(url, html):
        return "challenge_detected"
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame_url = frame.url
            frame_html = await frame.content()
        except Exception:
            continue
        if _looks_blocked(frame_url, frame_html):
            return "challenge_detected"
    return None


def _looks_posting_unavailable(url: str, html: str) -> bool:
    text = f"{url}\n{html[:5000]}".lower()
    markers = (
        "404 error",
        "couldn't find anything here",
        "job posting you're looking for might have closed",
        "job posting you re looking for might have closed",
        "job posting has closed",
        "job has been closed",
        "job has been removed",
        "posting has been removed",
        "position has been filled",
        "no longer accepting applications",
    )
    return any(marker in text for marker in markers)


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
        "I'm interested",
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


def classify_browser_action(label: str) -> str:
    if FORBIDDEN_SUBMIT_TEXT_RE.search(label):
        return "forbidden"
    if APPLY_TEXT_RE.search(label):
        return "safe"
    return "review_required"


async def detect_forbidden_submit_controls(page: Page) -> list[dict[str, str]]:
    controls = await page.locator("button, input[type='submit'], input[type='button'], a").evaluate_all(
        """nodes => nodes.map(node => {
          const tag = node.tagName.toLowerCase();
          const text = (node.innerText || node.textContent || node.getAttribute('value') || node.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
          const type = node.getAttribute('type') || '';
          const name = node.getAttribute('name') || '';
          return { tag, text, type, name };
        }).filter(item => item.text || item.type === 'submit')"""
    )
    forbidden: list[dict[str, str]] = []
    for control in controls:
        label = str(control.get("text") or control.get("type") or "").strip()
        if classify_browser_action(label) == "forbidden":
            forbidden.append(
                {
                    "tag": str(control.get("tag") or ""),
                    "text": label[:120],
                    "action_policy": "forbidden",
                }
            )
    return forbidden


async def detect_safe_step_transition_controls(page: Page) -> dict[str, Any]:
    controls = await page.locator("button, input[type='submit'], input[type='button'], a").evaluate_all(
        """nodes => nodes.map((node, index) => {
          const tag = node.tagName.toLowerCase();
          const text = String(
            node.innerText
            || node.textContent
            || node.getAttribute('value')
            || node.getAttribute('aria-label')
            || ''
          ).replace(/\\s+/g, ' ').trim();
          const type = String(node.getAttribute('type') || '').toLowerCase();
          const disabled = Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true');
          const style = window.getComputedStyle(node);
          const visible = style.display !== 'none'
            && style.visibility !== 'hidden'
            && !node.hidden
            && Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
          return { index, tag, text, type, disabled, visible };
        }).filter(item => item.visible && !item.disabled && (item.text || item.type))"""
    )
    candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for control in controls:
        label = str(control.get("text") or control.get("type") or "").strip()
        if not label:
            continue
        if classify_browser_action(label) == "forbidden":
            blocked.append({"index": int(control.get("index") or 0), "text": label[:120], "reason": "final_submit"})
            continue
        if re.search(r"\bcontinue application\b", label, re.IGNORECASE):
            blocked.append({"index": int(control.get("index") or 0), "text": label[:120], "reason": "application_boundary"})
            continue
        if APPLY_TEXT_RE.search(label) and not SAFE_STEP_TEXT_RE.search(label):
            blocked.append({"index": int(control.get("index") or 0), "text": label[:120], "reason": "apply_or_submit_boundary"})
            continue
        if SAFE_STEP_TEXT_RE.search(label):
            candidates.append({"index": int(control.get("index") or 0), "text": label[:120], "tag": str(control.get("tag") or "")})
    if len(candidates) == 1:
        return {"status": "available", "control": candidates[0], "blocked_controls": blocked}
    return {
        "status": "not_available" if not candidates else "ambiguous",
        "candidates": candidates,
        "blocked_controls": blocked,
    }


async def click_safe_step_transition(page: Page, transition: dict[str, Any], *, timeout_ms: int) -> dict[str, Any]:
    if transition.get("status") != "available":
        return {"status": "not_clicked", "reason": transition.get("status") or "not_available"}
    control = transition.get("control") or {}
    try:
        await page.locator("button, input[type='submit'], input[type='button'], a").nth(int(control.get("index") or 0)).click(timeout=5000)
        await page.wait_for_timeout(1000)
        await _safe_network_idle(page, timeout_ms)
        return {"status": "advanced", "control_text": str(control.get("text") or ""), "url": page.url}
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "step_transition_click_failed",
            "control_text": str(control.get("text") or ""),
            "error": exc.__class__.__name__,
        }


async def maybe_auto_submit_application(
    page: Page,
    *,
    session: dict[str, Any],
    provider: str,
    apply_url: str,
    job: dict[str, Any],
    schema: dict[str, Any],
    mapping: dict[str, Any],
    resume_upload: dict[str, Any],
    forbidden_submit_controls: list[dict[str, str]],
    dry_run: bool,
    timeout_ms: int,
    progress: Progress | None = None,
) -> dict[str, Any]:
    blockers = auto_submit_blockers(
        session=session,
        provider=provider,
        apply_url=apply_url,
        job=job,
        schema=schema,
        mapping=mapping,
        resume_upload=resume_upload,
        forbidden_submit_controls=forbidden_submit_controls,
        dry_run=dry_run,
    )
    if os.getenv("ENABLE_AUTO_SUBMIT_APPROVED") != "1" or str(session.get("mode") or "") != "auto_submit_approved":
        return {"status": "disabled"}
    if blockers:
        return {"status": "blocked", "reasons": blockers}
    _progress(progress, "Auto-submit preconditions passed; clicking final submit.")
    return await click_approved_submit_control(page, timeout_ms=timeout_ms)


def auto_submit_blockers(
    *,
    session: dict[str, Any],
    provider: str,
    apply_url: str,
    job: dict[str, Any],
    schema: dict[str, Any],
    mapping: dict[str, Any],
    resume_upload: dict[str, Any],
    forbidden_submit_controls: list[dict[str, str]],
    dry_run: bool,
) -> list[str]:
    blockers: list[str] = []
    if os.getenv("ENABLE_AUTO_SUBMIT_APPROVED") != "1":
        blockers.append("auto_submit_disabled")
    if str(session.get("mode") or "") != "auto_submit_approved":
        blockers.append("session_mode_not_auto_submit")
    if provider != "greenhouse":
        blockers.append("provider_not_supported")
    if dry_run:
        blockers.append("dry_run_enabled")
    if _looks_placeholder_resume_for_real_url(apply_url, job):
        blockers.append("placeholder_resume_for_real_url")
    unknown_required = [
        field for field in mapping.get("unknown_fields") or []
        if field.get("required") or field.get("sensitive")
    ]
    if unknown_required:
        blockers.append("unknown_required_or_sensitive_fields")
    if _schema_requires_resume(schema) and resume_upload.get("status") != "uploaded":
        blockers.append("required_resume_not_uploaded")
    if len(forbidden_submit_controls) != 1:
        blockers.append("ambiguous_submit_control" if forbidden_submit_controls else "missing_submit_control")
    return blockers


def _looks_placeholder_resume_for_real_url(apply_url: str, job: dict[str, Any]) -> bool:
    if str(apply_url or "").lower().startswith("data:"):
        return False
    text = str(job.get("ats_cv_text") or "").lower()
    markers = (
        "synthetic",
        "rehearsal",
        "placeholder",
        "this should never be submitted",
        "automation rehearsal",
    )
    return any(marker in text for marker in markers)


async def click_approved_submit_control(page: Page, *, timeout_ms: int) -> dict[str, Any]:
    locator = page.locator("button, input[type='submit'], input[type='button']")
    matches: list[dict[str, Any]] = []
    try:
        count = await locator.count()
    except Exception as exc:
        return {"status": "failed", "reason": "submit_controls_unavailable", "error": exc.__class__.__name__}
    for index in range(count):
        item = locator.nth(index)
        try:
            label = await item.evaluate(
                """node => String(
                  node.innerText
                  || node.textContent
                  || node.getAttribute('value')
                  || node.getAttribute('aria-label')
                  || node.getAttribute('type')
                  || ''
                ).replace(/\\s+/g, ' ').trim()"""
            )
        except Exception:
            continue
        if classify_browser_action(str(label)) == "forbidden":
            matches.append({"index": index, "text": str(label)[:120]})
    if len(matches) != 1:
        return {
            "status": "blocked",
            "reasons": ["ambiguous_submit_control" if matches else "missing_submit_control"],
            "matched_controls": matches,
        }
    selected = matches[0]
    try:
        await locator.nth(int(selected["index"])).click(timeout=5000)
        await page.wait_for_timeout(1000)
        await _safe_network_idle(page, timeout_ms)
        return {"status": "submitted", "control_text": selected["text"], "final_url": page.url}
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "submit_click_failed",
            "control_text": selected["text"],
            "error": exc.__class__.__name__,
        }


def _schema_requires_resume(schema: dict[str, Any]) -> bool:
    return any(
        str(field.get("type") or "").lower() == "file" and bool(field.get("required"))
        for field in schema.get("fields") or []
        if isinstance(field, dict)
    )


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
        if answer.get("source") != "approved_answer" and canonical not in {
            "full_name",
            "email",
            "phone",
            "linkedin",
            "portfolio",
            "preferred_location",
            "talent_pool",
        }:
            continue
        field_type = str(answer.get("field_type") or "text")
        options = list(answer.get("options") or [])
        if field_type == "select":
            matched = _match_option(value, options)
            if matched is None:
                continue
            plan.append({"field_name": field_name, "value": matched["value"], "canonical_key": canonical, "action_type": "select_option"})
            continue
        if field_type == "radio":
            matched = _match_option(value, options)
            if matched is None:
                continue
            plan.append({"field_name": field_name, "value": matched["value"], "canonical_key": canonical, "action_type": "choose_radio"})
            continue
        if field_type == "checkbox":
            if _normalized(value) not in {"yes", "true", "checked", "1"}:
                continue
            plan.append({"field_name": field_name, "value": value, "canonical_key": canonical, "action_type": "check"})
            continue
        plan.append({"field_name": field_name, "value": value, "canonical_key": canonical, "action_type": "fill_text"})
    return plan


def _match_option(value: str, options: list[Any]) -> dict[str, str] | None:
    wanted = _normalized(value)
    matches: list[dict[str, str]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "")
        raw_value = str(option.get("value") or "")
        if wanted and wanted in {_normalized(label), _normalized(raw_value)}:
            matches.append({"label": label, "value": raw_value})
    return matches[0] if len(matches) == 1 else None


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", value.lower())).strip()


def _append_dynamic_required_unknowns(
    mapping: dict[str, Any],
    *,
    previous_schema: dict[str, Any],
    rescanned_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    previous_keys = {_field_identity(field) for field in previous_schema.get("fields") or [] if isinstance(field, dict)}
    answered_keys = {
        str(answer.get("field_name") or "").strip()
        for answer in mapping.get("answers") or []
        if isinstance(answer, dict) and str(answer.get("value") or "").strip()
    }
    unknown_keys = {
        str(field.get("name") or "").strip()
        for field in mapping.get("unknown_fields") or []
        if isinstance(field, dict)
    }
    dynamic: list[dict[str, Any]] = []
    for field in rescanned_schema.get("fields") or []:
        if not isinstance(field, dict) or not bool(field.get("required")):
            continue
        field_key = _field_identity(field)
        field_name = str(field.get("name") or field.get("id") or field.get("label") or "").strip()
        if not field_key or field_key in previous_keys or field_name in answered_keys or field_name in unknown_keys:
            continue
        unknown = {
            "name": field_name,
            "label": str(field.get("label") or field_name),
            "type": str(field.get("type") or "unknown"),
            "required": True,
            "sensitive": bool(field.get("sensitive")),
            "classification": str(field.get("classification") or "unknown"),
            "reason": "dynamic_required_after_autofill",
        }
        mapping.setdefault("unknown_fields", []).append(unknown)
        unknown_keys.add(field_name)
        dynamic.append(unknown)
    return dynamic


def _field_identity(field: dict[str, Any]) -> str:
    return str(field.get("name") or field.get("id") or field.get("label") or "").strip()


def _build_repair_report(
    *,
    previous_action_plan: dict[str, Any],
    rescanned_action_plan: dict[str, Any],
    dynamic_required_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    previous_fingerprint = str(previous_action_plan.get("form_fingerprint") or "")
    rescanned_fingerprint = str(rescanned_action_plan.get("form_fingerprint") or "")
    return {
        "status": "needs_user_input" if dynamic_required_fields else "no_repair_needed",
        "rescans": 1,
        "form_fingerprint_changed": bool(previous_fingerprint and rescanned_fingerprint and previous_fingerprint != rescanned_fingerprint),
        "dynamic_required_fields": dynamic_required_fields,
        "dynamic_required_count": len(dynamic_required_fields),
        "previous_form_fingerprint": previous_fingerprint,
        "rescanned_form_fingerprint": rescanned_fingerprint,
    }


def _build_application_automation_metrics(
    *,
    action_plan: dict[str, Any],
    validation_report: dict[str, Any],
    fill_result: dict[str, Any] | None,
    resume_upload: dict[str, Any],
    repair_report: dict[str, Any],
    mapping: dict[str, Any],
    step_transitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions = [action for action in action_plan.get("actions") or [] if isinstance(action, dict)]
    planned = len(actions)
    executed_fields = {
        str(field_name)
        for field_name in (fill_result or {}).get("filled_fields") or []
        if str(field_name).strip()
    }
    executed = len(executed_fields)
    upload_planned = any(str(action.get("action_type") or "") == "upload_file" for action in actions)
    upload_verified = upload_planned and resume_upload.get("status") == "uploaded"
    checked_postconditions = int(validation_report.get("checked_postconditions") or 0)
    satisfied_postconditions = int(validation_report.get("satisfied_postconditions") or 0)
    verifiable = checked_postconditions + (1 if upload_planned else 0)
    verified = satisfied_postconditions + (1 if upload_verified else 0)
    unresolved_count = len(mapping.get("unknown_fields") or [])
    transitions = step_transitions or []
    advanced_steps = [
        transition for transition in transitions
        if (transition.get("result") or {}).get("status") == "advanced"
    ]
    return {
        "planned_action_count": planned,
        "executed_action_count": executed,
        "verified_action_count": verified,
        "action_success_rate": _ratio(executed, planned),
        "verified_action_success_rate": _ratio(verified, verifiable),
        "validation_clean": validation_report.get("status") == "validation_clean",
        "validation_issue_count": int((validation_report.get("summary") or {}).get("issues") or len(validation_report.get("issues") or [])),
        "unresolved_required_count": unresolved_count,
        "dynamic_required_count": int(repair_report.get("dynamic_required_count") or 0),
        "repair_rescans": int(repair_report.get("rescans") or 0),
        "safe_step_transition_count": len(transitions),
        "steps_completed_without_human": len(advanced_steps),
        "step_advance_success_rate": _ratio(len(advanced_steps), len(transitions)),
        "submit_only_ready": (
            validation_report.get("status") == "validation_clean"
            and unresolved_count == 0
            and int(repair_report.get("dynamic_required_count") or 0) == 0
        ),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _merge_fill_result(target: dict[str, Any], update: dict[str, Any]) -> None:
    target["fields_autofilled"] = int(target.get("fields_autofilled") or 0) + int(update.get("fields_autofilled") or 0)
    target.setdefault("filled_fields", []).extend(list(update.get("filled_fields") or []))
    target.setdefault("skipped_fields", []).extend(list(update.get("skipped_fields") or []))


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
        action_type = item.get("action_type") or "fill_text"
        if action_type == "select_option":
            locator = page.locator(f'select[name="{field_name}"], select[id="{field_name}"]').first
            try:
                if await locator.count() > 0:
                    await locator.select_option(value=value, timeout=3000)
                    filled.append(field_name)
                else:
                    skipped.append(field_name)
            except Exception:
                skipped.append(field_name)
            continue
        if action_type == "choose_radio":
            locator = page.locator(f'input[type="radio"][name="{field_name}"][value="{value}"]').first
            try:
                if await locator.count() > 0:
                    await locator.check(timeout=3000)
                    filled.append(field_name)
                else:
                    skipped.append(field_name)
            except Exception:
                skipped.append(field_name)
            continue
        if action_type == "check":
            locator = page.locator(f'input[type="checkbox"][name="{field_name}"], input[type="checkbox"][id="{field_name}"]').first
            try:
                if await locator.count() > 0:
                    await locator.check(timeout=3000)
                    filled.append(field_name)
                else:
                    skipped.append(field_name)
            except Exception:
                skipped.append(field_name)
            continue
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


def resolve_resume_upload_file(job_id: int, job: dict[str, Any], *, max_bytes: int = 5_000_000) -> dict[str, Any]:
    ats_cv_text = str(job.get("ats_cv_text") or "").strip()
    if not ats_cv_text:
        return {"status": "unresolved", "reason": "missing_ats_cv_text"}
    try:
        content = export_ats_cv_pdf_bytes(job, ats_cv_text)
    except Exception as exc:
        return {"status": "unresolved", "reason": "export_failed", "error": exc.__class__.__name__}
    if not content:
        return {"status": "unresolved", "reason": "empty_export"}
    if len(content) > max_bytes:
        return {"status": "unresolved", "reason": "file_too_large", "max_bytes": max_bytes}
    filename = _safe_resume_filename(job, "pdf")
    temp_dir = Path(tempfile.mkdtemp(prefix="joborchestrator-resume-"))
    path = temp_dir / filename
    path.write_bytes(content)
    session = None
    resume_variant_id = None
    try:
        latest_session = db.get_latest_application_session_for_job(job_id)
        session = latest_session if latest_session and int(latest_session.get("job_id") or 0) == int(job_id) else None
        if session and session.get("application_id"):
            application = db.get_application(int(session["application_id"]))
            resume_variant_id = application.get("resume_variant_id") if application else None
        if not resume_variant_id:
            resume_variant = db.register_generated_resume_variant(
                job_id,
                f"{job.get('company') or 'Company'} - {job.get('title') or 'Role'} ATS CV",
                ats_cv_text,
            )
            resume_variant_id = resume_variant.get("id")
    except Exception:
        resume_variant_id = None
    return {
        "status": "resolved",
        "path": str(path),
        "cleanup_path": str(temp_dir),
        "filename": filename,
        "extension": ".pdf",
        "size_bytes": len(content),
        "resume_variant_id": resume_variant_id,
    }


async def upload_resume_on_page(page: Page, schema: dict[str, Any], resume_file: dict[str, Any]) -> dict[str, Any]:
    file_fields = [
        field for field in schema.get("fields") or []
        if str(field.get("type") or "").lower() == "file"
    ]
    if not file_fields:
        return {"status": "not_applicable", "cleanup_path": resume_file.get("cleanup_path")}
    field = file_fields[0]
    field_name = str(field.get("name") or field.get("id") or "resume")
    if resume_file.get("status") != "resolved":
        return {"status": "unresolved", "field_name": field_name, "reason": resume_file.get("reason") or "missing_resume_file"}
    path = Path(str(resume_file.get("path") or ""))
    extension = path.suffix.lower()
    if extension not in {".pdf", ".docx"}:
        return {"status": "unresolved", "field_name": field_name, "reason": "unsupported_extension", "cleanup_path": resume_file.get("cleanup_path")}
    if not path.exists() or not path.is_file():
        return {"status": "unresolved", "field_name": field_name, "reason": "missing_local_file", "cleanup_path": resume_file.get("cleanup_path")}
    if path.stat().st_size > 5_000_000:
        return {"status": "unresolved", "field_name": field_name, "reason": "file_too_large", "cleanup_path": resume_file.get("cleanup_path")}
    selectors = [
        f'input[type="file"][name="{field_name}"]',
        f'input[type="file"][id="{field_name}"]',
        'input[type="file"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0:
                await locator.set_input_files(str(path), timeout=3000)
                return {
                    "status": "uploaded",
                    "field_name": field_name,
                    "filename": path.name,
                    "extension": extension,
                    "size_bytes": path.stat().st_size,
                    "resume_variant_id": resume_file.get("resume_variant_id"),
                    "cleanup_path": resume_file.get("cleanup_path"),
                }
        except Exception:
            continue
    return {"status": "unresolved", "field_name": field_name, "reason": "file_input_not_found", "cleanup_path": resume_file.get("cleanup_path")}


def _remove_resolved_file_unknowns(mapping: dict[str, Any]) -> None:
    mapping["unknown_fields"] = [
        field for field in mapping.get("unknown_fields") or []
        if str(field.get("type") or "").lower() != "file"
    ]


def _public_resume_upload_result(result: dict[str, Any]) -> dict[str, Any]:
    redacted = {
        key: value
        for key, value in result.items()
        if key not in {"path", "cleanup_path"}
    }
    return redacted or {"status": "not_attempted"}


def _cleanup_resume_upload_file(path: str) -> None:
    target = Path(path)
    if not target.exists():
        return
    try:
        if target.is_dir():
            for child in target.iterdir():
                child.unlink(missing_ok=True)
            target.rmdir()
        else:
            target.unlink(missing_ok=True)
    except OSError:
        return


def _safe_resume_filename(job: dict[str, Any], extension: str) -> str:
    raw = f"{job.get('company') or 'company'}-{job.get('title') or 'role'}-ats-cv"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return f"{(slug or 'ats-cv')[:80]}.{extension}"


async def _first_visible_locator(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None
