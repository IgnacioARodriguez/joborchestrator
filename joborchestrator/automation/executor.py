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
from joborchestrator.automation.intervention import policy_intervention_items
from joborchestrator.automation.ledger import build_obligation_ledger
from joborchestrator.automation.metrics import compute_outcome_metrics
from joborchestrator.automation.policy import evaluate_answer_action, evaluate_browser_action
from joborchestrator.automation.journey import ApplicationJourneyEngine
from joborchestrator.automation.surfaces import reconcile_surface_lifecycle, rebind_control, surface_nodes_from_step
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


async def _handoff_or_close_browser(
    *,
    browser_ref: str,
    page: Page,
    browser: Browser | None,
    context: BrowserContext | None,
    playwright: Any | None,
    provider: str,
    session_id: int,
    job_id: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Keep the exact browser session open when the user must intervene."""
    if local_browser_agent.enabled():
        session = await local_browser_agent.get_session(browser_ref)
        if session is None:
            session = local_browser_agent.register_session(
                page=page,
                browser=browser,
                context=context,
                playwright=playwright,
                provider=provider,
                session_id=session_id,
                job_id=job_id,
                timeout_seconds=timeout_seconds,
            )
        return {"status": "started", **local_browser_agent.public_metadata(session)}

    await _close_browser_or_context(browser, context)
    if playwright is not None:
        await playwright.stop()
    return {"status": "disabled"}


async def run_application_execution(
    *,
    session_id: int,
    job_id: int,
    apply_url: str,
    provider_hint: str = "generic",
    provider_override: str | None = None,
    dry_run: bool = True,
    progress: Progress | None = None,
) -> dict[str, Any]:
    if not apply_url:
        raise RuntimeError("application_execution requires an apply_url.")
    _progress(progress, "Opening external application URL.")
    headless_default = "0" if local_browser_agent.enabled() else "1"
    headless = os.getenv("APPLICATION_BROWSER_HEADLESS", headless_default) != "0"
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
            await _wait_for_interactive_stability(page, timeout_ms)
            hop_result = await _follow_apply_hops(page, timeout_ms=timeout_ms, max_hops=2, progress=progress)
            navigation = hop_result["steps"]
            page = hop_result["page"]
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
        identity = site_identity_from_url(url, provider_hint)
        handoff = await _handoff_or_close_browser(
            browser_ref=browser_ref,
            page=live_page,
            browser=live_browser,
            context=live_context,
            playwright=playwright_instance,
            provider=identity.provider,
            session_id=session_id,
            job_id=job_id,
            timeout_seconds=handoff_timeout_seconds,
        )
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
                "browser_session_ref": handoff.get("ref") or browser_ref or url,
                "artifacts_json": {
                    "url": apply_url, "provider_hint": provider_hint, "navigation": navigation, "browser_handoff": handoff
                },
            },
        )
        return {"session": session, "blocked": True, "reason": "challenge_detected", "browser_handoff": handoff}

    if _looks_login_required(html):
        identity = site_identity_from_url(url, provider_hint)
        login_result = await try_saved_login(live_page, identity.provider, identity.domain, timeout_ms=timeout_ms, progress=progress)
        if login_result["ok"]:
            navigation.append({"action": "auto_login", "url": live_page.url, "text": str(login_result["username"])})
            await _safe_network_idle(live_page, timeout_ms)
            await _wait_for_interactive_stability(live_page, timeout_ms)
            hop_result = await _follow_apply_hops(live_page, timeout_ms=timeout_ms, max_hops=2, progress=progress)
            navigation.extend(hop_result["steps"][1:])
            live_page = hop_result["page"]
            html = await live_page.content()
            url = live_page.url
            if _looks_login_required(html):
                handoff = await _handoff_or_close_browser(
                    browser_ref=browser_ref,
                    page=live_page,
                    browser=live_browser,
                    context=live_context,
                    playwright=playwright_instance,
                    provider=identity.provider,
                    session_id=session_id,
                    job_id=job_id,
                    timeout_seconds=handoff_timeout_seconds,
                )
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
                        "browser_session_ref": handoff.get("ref") or browser_ref or url,
                        "artifacts_json": {
                            "url": url, "provider_hint": provider_hint, "navigation": navigation, "browser_handoff": handoff
                        },
                    },
                )
                return {"session": session, "blocked": True, "reason": "login_required", "browser_handoff": handoff}
        else:
            handoff = await _handoff_or_close_browser(
                browser_ref=browser_ref,
                page=live_page,
                browser=live_browser,
                context=live_context,
                playwright=playwright_instance,
                provider=identity.provider,
                session_id=session_id,
                job_id=job_id,
                timeout_seconds=handoff_timeout_seconds,
            )
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
                    "browser_session_ref": handoff.get("ref") or browser_ref or url,
                    "artifacts_json": {
                        "url": url,
                        "provider_hint": provider_hint,
                        "navigation": navigation,
                        "login_attempt": login_result,
                        "browser_handoff": handoff,
                    },
                },
            )
            return {"session": session, "blocked": True, "reason": "login_required", "browser_handoff": handoff}

    job = db.get_job_posting(job_id) or {}
    registry = AdapterRegistry()
    adapter = (
        registry.get(provider_override)
        if provider_override
        else registry.detect(html, {**job, "apply_url": apply_url, "url": apply_url, "source": provider_hint})
    )
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
    obligation_ledger: dict[str, Any] = {}
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
            root_surface_kind=_root_surface_kind_from_navigation(navigation),
        )
        live_fill = {"dry_run": dry_run, "fields_autofilled": 0, "filled_fields": [], "skipped_fields": []}
        journey_steps: list[dict[str, Any]] = []
        step_transitions: list[dict[str, Any]] = []
        action_states: dict[str, dict[str, Any]] = {}
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
                step_fill = await fill_safe_fields_on_page(
                    browser_surface,
                    mapping,
                    dry_run=dry_run,
                    action_plan=journey_step.get("action_plan") or {},
                    action_states=action_states,
                )
                _merge_fill_result(live_fill, step_fill)
                fill_stability = await _wait_for_interactive_stability(browser_surface, timeout_ms)
            else:
                fill_stability = {"status": "not_applicable"}
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
                _update_action_states_from_validation(
                    action_states,
                    action_plan=journey_step.get("action_plan") or {},
                    validation_report=validation_report,
                    fill_result=step_fill,
                )
                repair_result = await run_bounded_repair_loop(
                    page=browser_surface,
                    journey_engine=journey_engine,
                    adapter=adapter,
                    capabilities=capabilities,
                    current_step=current_step,
                    html=html,
                    profile=profile,
                    answer_bank=answer_bank,
                    previous_validation_report=validation_report,
                    fill_stability=fill_stability,
                    fill_result=live_fill,
                    resume_upload=resume_upload,
                    dry_run=dry_run,
                    timeout_ms=timeout_ms,
                    action_states=action_states,
                    progress=progress,
                )
                current_step = repair_result["step"]
                schema = current_step.schema
                mapping = current_step.mapping
                browser_surface = current_step.browser_surface
                journey_step = {
                    **current_step.to_dict(),
                    "repair_rescan": repair_result.get("rescanned_step"),
                }
                validation_report = repair_result["validation_report"]
                repair_report = repair_result["repair_report"]
                transition = await detect_safe_step_transition_controls(browser_surface)
                automation_metrics = _build_application_automation_metrics(
                    action_plan=journey_step.get("action_plan") or {},
                    schema=schema,
                    surface=journey_step.get("surface") or {},
                    navigation=navigation,
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
                        "fill_stability": fill_stability,
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
                    root_surface_kind=_root_surface_kind_from_navigation(navigation),
                )
                continue
            break
        journey_step = {**journey_step, "steps": journey_steps, "step_transitions": step_transitions}
        automation_metrics = _build_application_automation_metrics(
            action_plan=journey_step.get("action_plan") or {},
            schema=schema,
            surface=journey_step.get("surface") or {},
            navigation=navigation,
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
    obligation_ledger = build_obligation_ledger(
        schema=schema,
        mapping=mapping,
        action_plan=journey_step.get("action_plan") or {},
        validation_report=validation_report,
        fill_result=live_fill,
        resume_upload=resume_upload,
        repair_report=repair_report,
        forbidden_submit_controls=forbidden_submit_controls,
        surfaces=journey_step.get("surfaces") or [],
        step_transitions=journey_step.get("step_transitions") or [],
    )
    readiness = obligation_ledger.get("readiness") or {}
    next_state = "submit_only" if readiness.get("ready") else "needs_user_input"
    automation_metrics = {
        **automation_metrics,
        "outcome_metrics": compute_outcome_metrics(obligation_ledger),
    }
    human_intervention = _build_human_intervention_report(
        next_state=next_state,
        review=review,
        mapping=mapping,
        validation_report=validation_report,
        repair_report=repair_report,
        resume_upload=resume_upload,
        fill_result=live_fill,
        automation_metrics=automation_metrics,
    )
    automation_metrics = {
        **automation_metrics,
        "human_interventions_per_application": human_intervention["required_count"],
        "human_intervention_types": human_intervention["types"],
        "answer_intervention_rate": _ratio(1 if "answer" in human_intervention["types"] else 0, 1),
        "validation_intervention_rate": _ratio(1 if "validation" in human_intervention["types"] else 0, 1),
        "widget_intervention_rate": _ratio(1 if "widget" in human_intervention["types"] else 0, 1),
        "submit_only_intervention_rate": _ratio(1 if "submit_only" in human_intervention["types"] else 0, 1),
    }

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
                "obligation_ledger": obligation_ledger,
                "human_intervention": human_intervention,
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
        "obligation_ledger": obligation_ledger,
        "human_intervention": human_intervention,
    }
    session = db.transition_application_session(
        session_id,
        next_state,
        {
            "note": "Ready for final user submit." if next_state == "submit_only" else "Missing fields require user input.",
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
) -> dict[str, Any]:
    steps: list[dict[str, str]] = [{"action": "opened", "url": page.url}]
    active_page = page
    for hop in range(max_hops):
        html = await active_page.content()
        if _looks_blocked(active_page.url, html) or _looks_login_required(html):
            steps.append({"action": "blocked", "url": active_page.url})
            break
        if _has_form(html):
            steps.append({"action": "form_detected", "url": active_page.url})
            break
        link = _best_apply_link(html, active_page.url)
        if link:
            _progress(progress, f"Following intermediate apply link: {link['text']}.")
            await active_page.goto(link["url"], wait_until="domcontentloaded", timeout=timeout_ms)
            await _safe_network_idle(active_page, timeout_ms)
            stability = await _wait_for_interactive_stability(active_page, timeout_ms)
            steps.append(
                {
                    "action": "followed_link",
                    "url": active_page.url,
                    "text": link["text"],
                    "stability_status": str(stability.get("status") or ""),
                    "stability_mutations": str(stability.get("mutation_count") or 0),
                }
            )
            continue
        click_result = await _click_apply_control(active_page, timeout_ms=timeout_ms)
        if click_result:
            clicked = str(click_result["text"])
            active_page = click_result["page"]
            _progress(progress, f"Clicked intermediate apply control: {clicked}.")
            await _safe_network_idle(active_page, timeout_ms)
            stability = await _wait_for_interactive_stability(active_page, timeout_ms)
            steps.append(
                {
                    "action": "opened_popup" if click_result.get("opened_popup") else "clicked_control",
                    "url": active_page.url,
                    "text": clicked,
                    "stability_status": str(stability.get("status") or ""),
                    "stability_mutations": str(stability.get("mutation_count") or 0),
                }
            )
            continue
        steps.append({"action": "no_apply_control", "url": active_page.url})
        break
    return {"steps": steps, "page": active_page}


async def _click_apply_control(page: Page, *, timeout_ms: int) -> dict[str, Any] | None:
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
                try:
                    async with page.context.expect_page(timeout=min(timeout_ms, 2000)) as popup_info:
                        await locator.click(timeout=min(timeout_ms, 5000))
                    popup = await popup_info.value
                    await popup.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 5000))
                    return {"text": label, "page": popup, "opened_popup": True}
                except PlaywrightTimeoutError:
                    return {"text": label, "page": page, "opened_popup": False}
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None


def _root_surface_kind_from_navigation(navigation: list[dict[str, Any]]) -> str:
    return "popup" if any(step.get("action") == "opened_popup" for step in navigation) else "page"


async def _safe_network_idle(page: Page, timeout_ms: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return


async def _wait_for_interactive_stability(page: Page, timeout_ms: int, *, quiet_ms: int = 400) -> dict[str, Any]:
    wait_timeout = min(max(timeout_ms, 1000), 3000)
    try:
        result = await page.evaluate(
            """({ quietMs, timeoutMs }) => new Promise(resolve => {
              const startedAt = Date.now();
              let mutationCount = 0;
              let lastFingerprint = fingerprint();
              let lastChangeAt = Date.now();
              const observer = new MutationObserver(() => {
                mutationCount += 1;
                const next = fingerprint();
                if (next !== lastFingerprint) {
                  lastFingerprint = next;
                  lastChangeAt = Date.now();
                }
              });
              observer.observe(document.documentElement || document, {
                subtree: true,
                childList: true,
                attributes: true,
                attributeFilter: ['style', 'class', 'hidden', 'disabled', 'aria-hidden', 'aria-expanded', 'aria-invalid', 'required'],
              });
              const interval = window.setInterval(() => {
                const stableFor = Date.now() - lastChangeAt;
                const timedOut = Date.now() - startedAt >= timeoutMs;
                if (stableFor >= quietMs || timedOut) {
                  window.clearInterval(interval);
                  observer.disconnect();
                  resolve({
                    status: stableFor >= quietMs ? 'stable' : 'timeout',
                    mutation_count: mutationCount,
                    stable_for_ms: stableFor,
                    fingerprint: lastFingerprint,
                  });
                }
              }, 100);

              function fingerprint() {
                return Array.from(document.querySelectorAll('form, input, textarea, select, button, a, [role], [aria-required="true"]'))
                  .filter(visible)
                  .map(element => [
                    element.tagName.toLowerCase(),
                    element.getAttribute('role') || '',
                    element.getAttribute('type') || '',
                    element.getAttribute('name') || '',
                    element.id || '',
                    element.getAttribute('aria-label') || '',
                    element.getAttribute('aria-expanded') || '',
                    element.hasAttribute('required') || element.getAttribute('aria-required') === 'true' ? 'required' : '',
                  ].join(':'))
                  .join('|');
              }
              function visible(element) {
                const style = window.getComputedStyle(element);
                return style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && !element.hidden
                  && element.getAttribute('aria-hidden') !== 'true'
                  && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              }
            })""",
            {"quietMs": quiet_ms, "timeoutMs": wait_timeout},
        )
        return result if isinstance(result, dict) else {"status": "unknown"}
    except Exception as exc:
        return {"status": "failed", "error": exc.__class__.__name__}


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
    decision = evaluate_browser_action(label)
    if decision.reason_code == "final_submit_reserved_for_user":
        return "forbidden"
    if decision.outcome == "ALLOW":
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
        stability = await _wait_for_interactive_stability(page, timeout_ms)
        return {"status": "advanced", "control_text": str(control.get("text") or ""), "url": page.url, "stability": stability}
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
    return {"status": "blocked", "reasons": ["final_submit_reserved_for_user"]}


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
    blockers.append("final_submit_reserved_for_user")
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
    _ = (page, timeout_ms)
    return {"status": "blocked", "reasons": ["final_submit_reserved_for_user"], "policy": "reserved_for_user"}


def _schema_requires_resume(schema: dict[str, Any]) -> bool:
    return any(
        str(field.get("type") or "").lower() == "file" and bool(field.get("required"))
        for field in schema.get("fields") or []
        if isinstance(field, dict)
    )


def safe_fill_plan(mapping: dict[str, Any], action_plan: dict[str, Any] | None = None) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    include_state_key = action_plan is not None
    state_keys = {
        str(action.get("field_name") or ""): _action_state_key(action)
        for action in (action_plan or {}).get("actions") or []
        if isinstance(action, dict) and str(action.get("field_name") or "")
    }
    for answer in mapping.get("answers") or []:
        value = str(answer.get("value") or "").strip()
        field_name = str(answer.get("field_name") or "").strip()
        canonical = str(answer.get("canonical_key") or "").strip()
        if not value or not field_name:
            continue
        field_type = str(answer.get("field_type") or "text")
        action_type = {
            "select": "select_option",
            "radio": "choose_radio",
            "checkbox": "check",
        }.get(field_type, "fill_text")
        decision = evaluate_answer_action(answer, action=action_type)
        if decision.outcome != "ALLOW":
            continue
        options = list(answer.get("options") or [])
        if field_type == "select":
            matched = _match_option(value, options)
            if matched is None:
                continue
            item = {"field_name": field_name, "value": matched["value"], "canonical_key": canonical, "action_type": "select_option"}
            if include_state_key:
                item["state_key"] = state_keys.get(field_name, field_name)
            plan.append(item)
            continue
        if field_type == "radio":
            matched = _match_option(value, options)
            if matched is None:
                continue
            item = {"field_name": field_name, "value": matched["value"], "canonical_key": canonical, "action_type": "choose_radio"}
            if include_state_key:
                item["state_key"] = state_keys.get(field_name, field_name)
            plan.append(item)
            continue
        if field_type == "checkbox":
            if _normalized(value) not in {"yes", "true", "checked", "1"}:
                continue
            item = {"field_name": field_name, "value": value, "canonical_key": canonical, "action_type": "check"}
            if include_state_key:
                item["state_key"] = state_keys.get(field_name, field_name)
            plan.append(item)
            continue
        item = {"field_name": field_name, "value": value, "canonical_key": canonical, "action_type": "fill_text"}
        if include_state_key:
            item["state_key"] = state_keys.get(field_name, field_name)
        plan.append(item)
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
        if not field_key or field_key in previous_keys or field_name in answered_keys:
            continue
        if field_name in unknown_keys:
            for unknown in mapping.get("unknown_fields") or []:
                if isinstance(unknown, dict) and str(unknown.get("name") or "").strip() == field_name:
                    unknown.setdefault("reason", "dynamic_required_after_autofill")
                    dynamic.append(unknown)
                    break
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


def _unknown_required_after_autofill(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    dynamic = []
    for field in mapping.get("unknown_fields") or []:
        if not isinstance(field, dict) or not (field.get("required") or field.get("sensitive")):
            continue
        field.setdefault("reason", "dynamic_required_after_autofill")
        dynamic.append(field)
    return dynamic


def _field_identity(field: dict[str, Any]) -> str:
    return str(field.get("name") or field.get("id") or field.get("label") or "").strip()


async def run_bounded_repair_loop(
    *,
    page: Page,
    journey_engine: ApplicationJourneyEngine,
    adapter: Any,
    capabilities: Any,
    current_step: Any,
    html: str,
    profile: dict[str, Any],
    answer_bank: list[dict[str, Any]],
    previous_validation_report: dict[str, Any],
    fill_stability: dict[str, Any],
    fill_result: dict[str, Any],
    resume_upload: dict[str, Any],
    dry_run: bool,
    timeout_ms: int,
    action_states: dict[str, dict[str, Any]],
    progress: Progress | None = None,
) -> dict[str, Any]:
    retry_budget = max(0, int(os.getenv("APPLICATION_REPAIR_RETRY_BUDGET", "1")))
    previous_step_dict = current_step.to_dict()
    rescanned_step = await journey_engine.inspect_surface(
        adapter=adapter,
        capabilities=capabilities,
        surface=current_step.surface,
        browser_surface=current_step.browser_surface,
        html=html,
        profile=profile,
        answer_bank=answer_bank,
        surfaces=current_step.surfaces,
    )
    if resume_upload.get("status") == "uploaded":
        _remove_resolved_file_unknowns(rescanned_step.mapping)
    dynamic_required_fields = _append_dynamic_required_unknowns(
        rescanned_step.mapping,
        previous_schema=current_step.schema,
        rescanned_schema=rescanned_step.schema,
    )
    if not dynamic_required_fields and int(fill_stability.get("mutation_count") or 0) > 0:
        dynamic_required_fields = _unknown_required_after_autofill(rescanned_step.mapping)
    lifecycle = reconcile_surface_lifecycle(
        surface_nodes_from_step(previous_step_dict, generation=0),
        surface_nodes_from_step(rescanned_step.to_dict(), generation=1),
        generation=1,
    )
    repair_report = _build_repair_report(
        previous_action_plan=previous_step_dict.get("action_plan") or {},
        rescanned_action_plan=rescanned_step.to_dict().get("action_plan") or {},
        dynamic_required_fields=dynamic_required_fields,
        previous_validation_report=previous_validation_report,
        lifecycle=[node.to_dict() for node in lifecycle],
        retry_budget=retry_budget,
    )
    repair_report["skipped_already_verified"] = _verified_action_fields(
        previous_step_dict.get("action_plan") or {},
        action_states,
    )
    current_validation = previous_validation_report
    if dynamic_required_fields:
        repair_report["status"] = "needs_user_input"
        repair_report["terminal_blocker"] = "missing_answer"
        return {
            "step": rescanned_step,
            "rescanned_step": rescanned_step.to_dict(),
            "validation_report": current_validation,
            "repair_report": repair_report,
        }
    if retry_budget <= 0:
        repair_report["status"] = "failed_terminal"
        repair_report["terminal_blocker"] = "retry_budget_exhausted"
        repair_report["reason_codes"] = sorted(set([*repair_report["reason_codes"], "retry_budget_exhausted"]))
        return {
            "step": rescanned_step,
            "rescanned_step": rescanned_step.to_dict(),
            "validation_report": current_validation,
            "repair_report": repair_report,
        }
    recoverable = _recoverable_repair_targets(
        previous_action_plan=previous_step_dict.get("action_plan") or {},
        rescanned_action_plan=rescanned_step.to_dict().get("action_plan") or {},
        validation_report=previous_validation_report,
        action_states=action_states,
    )
    if not recoverable:
        if previous_validation_report.get("status") == "validation_failed":
            _append_validation_unknown(rescanned_step.mapping, previous_validation_report)
            repair_report["status"] = "failed_terminal"
            repair_report["terminal_blocker"] = "validation_not_recoverable"
        return {
            "step": rescanned_step,
            "rescanned_step": rescanned_step.to_dict(),
            "validation_report": current_validation,
            "repair_report": repair_report,
        }
    attempts = []
    for target in recoverable[:retry_budget]:
        field_name = str(target.get("field_name") or "")
        state_key = str(target.get("state_key") or field_name)
        rebound = _rebind_target_control(rescanned_step.schema, target)
        attempt = {
            "field_name": field_name,
            "state_key": state_key,
            "classification": target["classification"],
            "strategy": "logical_rebind_retry" if rebound else "rediscovered_field_retry",
            "policy": "not_evaluated",
            "rebound": bool(rebound),
        }
        if not rebound and target["classification"] in {"stale_control", "dynamic_id_changed", "control_missing"}:
            action_states[state_key] = {"status": "failed-terminal", "reason": "ambiguous_semantic_mapping"}
            attempt["status"] = "failed-terminal"
            attempt["reason"] = "ambiguous_semantic_mapping"
            attempts.append(attempt)
            continue
        planned = _find_action_by_field(rescanned_step.action_plan.to_dict(), str((rebound or {}).get("name") or field_name))
        answer = _find_answer_by_field(rescanned_step.mapping, str((planned or {}).get("field_name") or field_name))
        decision = evaluate_answer_action(answer or {}, action=str((planned or {}).get("action_type") or target.get("action_type") or "fill_text"))
        attempt["policy"] = decision.to_dict()
        if decision.outcome != "ALLOW" or planned is None:
            _append_validation_unknown(rescanned_step.mapping, previous_validation_report)
            action_states[state_key] = {"status": "failed-terminal", "reason": decision.reason_code or "policy_review"}
            attempt["status"] = "failed-terminal"
            attempt["reason"] = decision.reason_code or "policy_review"
            attempts.append(attempt)
            continue
        _progress(progress, f"Retrying recoverable application action: {planned['field_name']}.")
        retry_fill = await fill_safe_fields_on_page(
            page,
            rescanned_step.mapping,
            dry_run=dry_run,
            action_plan=rescanned_step.action_plan.to_dict(),
            action_states=action_states,
            only_fields={str(planned["field_name"])},
        )
        _merge_fill_result(fill_result, retry_fill)
        await _wait_for_interactive_stability(page, timeout_ms)
        current_validation = (await validate_application_surface(page, rescanned_step.action_plan.to_dict())).to_dict()
        _update_action_states_from_validation(
            action_states,
            action_plan=rescanned_step.action_plan.to_dict(),
            validation_report=current_validation,
            fill_result=retry_fill,
        )
        attempt["status"] = "verified" if current_validation.get("status") == "validation_clean" else "failed-recoverable"
        attempt["second_validation"] = current_validation
        attempts.append(attempt)
        if current_validation.get("status") == "validation_clean":
            break
    repair_report["attempts"] = len(attempts)
    repair_report["retry_attempts"] = attempts
    repair_report["second_verification"] = any("second_validation" in attempt for attempt in attempts)
    if current_validation.get("status") == "validation_clean":
        repair_report["status"] = "repaired"
        repair_report["failure_classification"] = attempts[-1]["classification"] if attempts else repair_report["failure_classification"]
    else:
        _append_validation_unknown(rescanned_step.mapping, current_validation)
        repair_report["status"] = "failed_terminal"
        repair_report["terminal_blocker"] = "retry_budget_exhausted"
        repair_report["reason_codes"] = sorted(set([*repair_report["reason_codes"], "retry_budget_exhausted"]))
    return {
        "step": rescanned_step,
        "rescanned_step": rescanned_step.to_dict(),
        "validation_report": current_validation,
        "repair_report": repair_report,
    }


def _build_repair_report(
    *,
    previous_action_plan: dict[str, Any],
    rescanned_action_plan: dict[str, Any],
    dynamic_required_fields: list[dict[str, Any]],
    previous_validation_report: dict[str, Any] | None = None,
    lifecycle: list[dict[str, Any]] | None = None,
    retry_budget: int = 1,
) -> dict[str, Any]:
    previous_fingerprint = str(previous_action_plan.get("form_fingerprint") or "")
    rescanned_fingerprint = str(rescanned_action_plan.get("form_fingerprint") or "")
    reason_codes = []
    if dynamic_required_fields:
        reason_codes.append("dynamic_required_after_autofill")
    if previous_fingerprint and rescanned_fingerprint and previous_fingerprint != rescanned_fingerprint:
        reason_codes.append("form_fingerprint_changed")
    if (previous_validation_report or {}).get("status") == "validation_failed":
        reason_codes.append("postcondition_failed")
    return {
        "status": "needs_user_input" if dynamic_required_fields else "no_repair_needed",
        "attempts": 0,
        "retry_budget": retry_budget,
        "rescans": 1,
        "rediscovery_generation": 1,
        "surface_lifecycle": lifecycle or [],
        "form_fingerprint_changed": bool(previous_fingerprint and rescanned_fingerprint and previous_fingerprint != rescanned_fingerprint),
        "failure_classification": _classify_repair_failure(previous_validation_report or {}, dynamic_required_fields),
        "reason_codes": reason_codes,
        "dynamic_required_fields": dynamic_required_fields,
        "dynamic_required_count": len(dynamic_required_fields),
        "previous_form_fingerprint": previous_fingerprint,
        "rescanned_form_fingerprint": rescanned_fingerprint,
    }


def _recoverable_repair_targets(
    *,
    previous_action_plan: dict[str, Any],
    rescanned_action_plan: dict[str, Any],
    validation_report: dict[str, Any],
    action_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if validation_report.get("status") != "validation_failed":
        return []
    previous_actions = [action for action in previous_action_plan.get("actions") or [] if isinstance(action, dict)]
    issue_fields = {
        str(issue.get("field_name") or "")
        for issue in validation_report.get("issues") or []
        if isinstance(issue, dict)
    }
    targets = []
    for action in previous_actions:
        field_name = str(action.get("field_name") or "")
        state_key = _action_state_key(action)
        state = action_states.get(state_key) or {}
        if state.get("status") == "verified":
            targets.append(
                {
                    "field_name": field_name,
                    "state_key": state_key,
                    "classification": "skipped-already-verified",
                    "action_type": action.get("action_type"),
                    "skipped": True,
                }
            )
            continue
        if issue_fields and field_name not in issue_fields:
            continue
        classification = _classify_action_repair_failure(action, rescanned_action_plan)
        if classification in {"missing_answer", "ambiguous_semantic_mapping", "policy_review"}:
            action_states[state_key] = {"status": "failed-terminal", "reason": classification}
            continue
        targets.append(
            {
                "field_name": field_name,
                "state_key": state_key,
                "classification": classification,
                "action_type": action.get("action_type"),
                "control_identity": ((action.get("control_handle") or {}).get("logical_identity") or {}),
            }
        )
    return [target for target in targets if not target.get("skipped")]


def _verified_action_fields(action_plan: dict[str, Any], action_states: dict[str, dict[str, Any]]) -> list[str]:
    verified = []
    for action in action_plan.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if (action_states.get(_action_state_key(action)) or {}).get("status") == "verified":
            field_name = str(action.get("field_name") or "")
            if field_name:
                verified.append(field_name)
    return list(dict.fromkeys(verified))


def _classify_repair_failure(validation_report: dict[str, Any], dynamic_required_fields: list[dict[str, Any]]) -> str:
    if dynamic_required_fields:
        return "dynamic_required"
    issues = [issue for issue in validation_report.get("issues") or [] if isinstance(issue, dict)]
    if not issues:
        return "none"
    if any(str(issue.get("issue_type") or "") == "control_missing" for issue in issues):
        return "stale_control"
    if any(str(issue.get("issue_type") or "") in {"browser_invalid", "aria_invalid", "visible_error"} for issue in issues):
        return "async_validation"
    return "postcondition_failed"


def _classify_action_repair_failure(action: dict[str, Any], rescanned_action_plan: dict[str, Any]) -> str:
    field_name = str(action.get("field_name") or "")
    rescanned = _find_action_by_field(rescanned_action_plan, field_name)
    if rescanned:
        return "postcondition_failed"
    identity = ((action.get("control_handle") or {}).get("logical_identity") or {})
    if identity:
        return "dynamic_id_changed"
    return "control_missing"


def _rebind_target_control(schema: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    identity = target.get("control_identity") if isinstance(target.get("control_identity"), dict) else {}
    if identity:
        return rebind_control(schema, identity)
    field_name = str(target.get("field_name") or "")
    for field in schema.get("fields") or []:
        if isinstance(field, dict) and str(field.get("name") or field.get("id") or "") == field_name:
            return field
    return None


def _find_action_by_field(action_plan: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    for action in action_plan.get("actions") or []:
        if isinstance(action, dict) and str(action.get("field_name") or "") == field_name:
            return action
    return None


def _find_answer_by_field(mapping: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    for answer in mapping.get("answers") or []:
        if isinstance(answer, dict) and str(answer.get("field_name") or "") == field_name:
            return answer
    return None


def _append_validation_unknown(mapping: dict[str, Any], validation_report: dict[str, Any]) -> None:
    unknowns = mapping.setdefault("unknown_fields", [])
    if any(isinstance(item, dict) and item.get("name") == "validation" for item in unknowns):
        return
    unknowns.append(
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


def _update_action_states_from_validation(
    action_states: dict[str, dict[str, Any]],
    *,
    action_plan: dict[str, Any],
    validation_report: dict[str, Any],
    fill_result: dict[str, Any],
) -> None:
    issue_fields = {
        str(issue.get("field_name") or "")
        for issue in validation_report.get("issues") or []
        if isinstance(issue, dict) and str(issue.get("field_name") or "")
    }
    filled = {str(item) for item in fill_result.get("filled_fields") or [] if str(item).strip()}
    skipped = {str(item) for item in fill_result.get("skipped_fields") or [] if str(item).strip()}
    for action in action_plan.get("actions") or []:
        if not isinstance(action, dict):
            continue
        field_name = str(action.get("field_name") or "")
        key = _action_state_key(action)
        if field_name in skipped:
            action_states[key] = {"status": "failed-recoverable", "field_name": field_name, "reason": "planned_action_not_executed"}
            continue
        if field_name in filled:
            action_states.setdefault(key, {"status": "attempted", "field_name": field_name})
        if field_name in filled and field_name not in issue_fields:
            action_states[key] = {"status": "verified", "field_name": field_name}
            continue
        if field_name in issue_fields:
            action_states[key] = {"status": "failed-recoverable", "field_name": field_name, "reason": "postcondition_failed"}


def _action_state_key(action: dict[str, Any]) -> str:
    handle = action.get("control_handle") if isinstance(action.get("control_handle"), dict) else {}
    logical = handle.get("logical_identity") if isinstance(handle.get("logical_identity"), dict) else {}
    return str(logical.get("fingerprint") or handle.get("fingerprint") or action.get("field_name") or "")


def _build_application_automation_metrics(
    *,
    action_plan: dict[str, Any],
    schema: dict[str, Any] | None = None,
    surface: dict[str, Any] | None = None,
    navigation: list[dict[str, Any]] | None = None,
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
    skipped_fields = {
        str(field_name)
        for field_name in (fill_result or {}).get("skipped_fields") or []
        if str(field_name).strip()
    }
    executed = len(executed_fields)
    upload_planned = any(str(action.get("action_type") or "") == "upload_file" for action in actions)
    file_fields = [
        field for field in (schema or {}).get("fields") or []
        if isinstance(field, dict) and str(field.get("type") or "").lower() == "file"
    ]
    resume_upload_planned = upload_planned or bool(file_fields)
    resume_upload_verified = resume_upload_planned and resume_upload.get("status") == "uploaded"
    strategy_counts = _control_strategy_action_counts(actions, executed_fields)
    file_widget_planned = any(
        str(field.get("locator_strategy") or "") == "file_widget"
        for field in file_fields
    ) or strategy_counts["planned"].get("file_widget", 0) > 0
    file_widget_executed = resume_upload_verified and (
        file_widget_planned or str(resume_upload.get("strategy") or "") == "file_chooser"
    )
    checked_postconditions = int(validation_report.get("checked_postconditions") or 0)
    satisfied_postconditions = int(validation_report.get("satisfied_postconditions") or 0)
    verifiable = checked_postconditions + (1 if resume_upload_planned else 0)
    verified = satisfied_postconditions + (1 if resume_upload_verified else 0)
    unresolved_count = len(mapping.get("unknown_fields") or [])
    transitions = step_transitions or []
    popup_opened = any(step.get("action") == "opened_popup" for step in navigation or [])
    popup_surface_selected = popup_opened and str((surface or {}).get("kind") or "") == "popup"
    advanced_steps = [
        transition for transition in transitions
        if (transition.get("result") or {}).get("status") == "advanced"
    ]
    return {
        "planned_action_count": planned,
        "executed_action_count": executed,
        "skipped_action_count": len(skipped_fields),
        "verified_action_count": verified,
        "control_strategy_counts": strategy_counts,
        "action_success_rate": _ratio(executed, planned),
        "verified_action_success_rate": _ratio(verified, verifiable),
        "native_control_success_rate": _strategy_success_rate(strategy_counts, "native_control"),
        "custom_control_success_rate": _strategy_success_rate(strategy_counts, "custom_control"),
        "shadow_control_success_rate": _strategy_success_rate(strategy_counts, "shadow_control"),
        "file_widget_success_rate": _ratio(1 if file_widget_executed else 0, 1 if file_widget_planned else 0),
        "resume_upload_success_rate": _ratio(1 if resume_upload_verified else 0, 1 if resume_upload_planned else 0),
        "resume_upload_strategy": resume_upload.get("strategy"),
        "popup_handling_success_rate": _ratio(1 if popup_surface_selected else 0, 1 if popup_opened else 0),
        "popup_surface_selected": popup_surface_selected,
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
            and not skipped_fields
        ),
    }


def _build_human_intervention_report(
    *,
    next_state: str,
    review: dict[str, Any],
    mapping: dict[str, Any],
    validation_report: dict[str, Any],
    repair_report: dict[str, Any],
    resume_upload: dict[str, Any],
    fill_result: dict[str, Any] | None,
    automation_metrics: dict[str, Any],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    unknown_fields = [
        field for field in (review.get("unknown_fields") or mapping.get("unknown_fields") or [])
        if isinstance(field, dict)
    ]
    for field in unknown_fields:
        field_type = str(field.get("type") or "")
        reason = str(field.get("reason") or "")
        if field_type == "validation":
            items.append(
                {
                    "type": "validation",
                    "field": str(field.get("name") or "validation"),
                    "label": str(field.get("label") or "Validation failed"),
                    "reason": "validation_failed",
                }
            )
            continue
        if reason == "dynamic_required_after_autofill":
            items.append(
                {
                    "type": "dynamic_field",
                    "field": str(field.get("name") or ""),
                    "label": str(field.get("label") or field.get("name") or ""),
                    "reason": reason,
                }
            )
            continue
        items.append(
            {
                "type": "answer",
                "field": str(field.get("name") or field.get("id") or ""),
                "label": str(field.get("label") or field.get("name") or ""),
                "reason": "missing_or_unapproved_answer",
                "required": bool(field.get("required")),
                "sensitive": bool(field.get("sensitive")),
            }
        )
    existing_fields = {str(item.get("field") or "") for item in items}
    for item in policy_intervention_items(mapping):
        field = str(item.get("field") or "")
        if field and field not in existing_fields:
            items.append(item)
            existing_fields.add(field)
    if validation_report.get("status") == "validation_failed" and not any(item["type"] == "validation" for item in items):
        items.append({"type": "validation", "field": "validation", "label": "Validation failed", "reason": "validation_failed"})
    if int(repair_report.get("dynamic_required_count") or 0) > 0 and not any(item["type"] == "dynamic_field" for item in items):
        for field in repair_report.get("dynamic_required_fields") or []:
            if isinstance(field, dict):
                items.append(
                    {
                        "type": "dynamic_field",
                        "field": str(field.get("name") or ""),
                        "label": str(field.get("label") or field.get("name") or ""),
                        "reason": "dynamic_required_after_autofill",
                    }
                )
    if resume_upload.get("status") == "unresolved":
        items.append(
            {
                "type": "resume_upload",
                "field": str(resume_upload.get("field_name") or "resume"),
                "label": "Resume upload",
                "reason": str(resume_upload.get("reason") or "resume_upload_unresolved"),
            }
        )
    skipped_fields = [
        str(field) for field in (fill_result or {}).get("skipped_fields") or []
        if str(field).strip()
    ]
    for field_name in skipped_fields:
        if not any(item.get("field") == field_name for item in items):
            items.append({"type": "widget", "field": field_name, "label": field_name, "reason": "planned_action_not_executed"})
    if next_state == "submit_only" and automation_metrics.get("submit_only_ready"):
        items.append(
            {
                "type": "submit_only",
                "field": "final_submit",
                "label": "Final review and submit",
                "reason": "human_final_submit_boundary",
            }
        )
    types = sorted({str(item["type"]) for item in items if item.get("type")})
    counts_by_type: dict[str, int] = {}
    for item in items:
        item_type = str(item.get("type") or "unknown")
        counts_by_type[item_type] = counts_by_type.get(item_type, 0) + 1
    blocking_items = [item for item in items if item.get("type") != "submit_only"]
    return {
        "status": "submit_only" if types == ["submit_only"] else "needs_human" if blocking_items else "none",
        "required_count": len(items),
        "blocking_count": len(blocking_items),
        "types": types,
        "counts_by_type": counts_by_type,
        "items": items,
    }


def _control_strategy_action_counts(actions: list[dict[str, Any]], executed_fields: set[str]) -> dict[str, dict[str, int]]:
    planned: dict[str, int] = {}
    executed: dict[str, int] = {}
    for action in actions:
        bucket = _control_strategy_bucket(action)
        planned[bucket] = planned.get(bucket, 0) + 1
        field_name = str(action.get("field_name") or "")
        if field_name in executed_fields:
            executed[bucket] = executed.get(bucket, 0) + 1
    return {"planned": planned, "executed": executed}


def _control_strategy_bucket(action: dict[str, Any]) -> str:
    strategies = {
        str(strategy)
        for strategy in ((action.get("control_handle") or {}).get("locator_strategies") or [])
        if str(strategy).strip()
    }
    if str(action.get("action_type") or "") == "upload_file":
        return "file_widget" if "file_widget" in strategies else "native_file"
    if "shadow_root" in strategies:
        return "shadow_control"
    if "aria_role" in strategies:
        return "custom_control"
    if "file_widget" in strategies:
        return "file_widget"
    return "native_control"


def _strategy_success_rate(strategy_counts: dict[str, dict[str, int]], bucket: str) -> float:
    return _ratio(
        int(strategy_counts.get("executed", {}).get(bucket, 0)),
        int(strategy_counts.get("planned", {}).get(bucket, 0)),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _merge_fill_result(target: dict[str, Any], update: dict[str, Any]) -> None:
    filled = list(dict.fromkeys([*list(target.get("filled_fields") or []), *list(update.get("filled_fields") or [])]))
    skipped = list(dict.fromkeys([*list(target.get("skipped_fields") or []), *list(update.get("skipped_fields") or [])]))
    skipped_verified = list(
        dict.fromkeys([*list(target.get("skipped_already_verified") or []), *list(update.get("skipped_already_verified") or [])])
    )
    target["fields_autofilled"] = len(filled)
    target["filled_fields"] = filled
    target["skipped_fields"] = skipped
    target["skipped_already_verified"] = skipped_verified


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


async def fill_safe_fields_on_page(
    page: Page,
    mapping: dict[str, Any],
    *,
    dry_run: bool = True,
    action_plan: dict[str, Any] | None = None,
    action_states: dict[str, dict[str, Any]] | None = None,
    only_fields: set[str] | None = None,
) -> dict[str, Any]:
    filled: list[str] = []
    skipped: list[str] = []
    skipped_verified: list[str] = []
    for item in safe_fill_plan(mapping, action_plan):
        field_name = item["field_name"]
        if only_fields is not None and field_name not in only_fields:
            continue
        state_key = str(item.get("state_key") or field_name)
        if (action_states or {}).get(state_key, {}).get("status") == "verified":
            skipped_verified.append(field_name)
            continue
        value = item["value"]
        action_type = item.get("action_type") or "fill_text"
        if action_states is not None:
            action_states[state_key] = {"status": "attempted", "field_name": field_name}
        if action_type == "select_option":
            locator = page.locator(f'select[name="{field_name}"], select[id="{field_name}"]').first
            try:
                if await locator.count() > 0:
                    await locator.select_option(value=value, timeout=3000)
                    filled.append(field_name)
                elif await _select_deep_native(page, field_name=field_name, value=value, dry_run=dry_run):
                    filled.append(field_name)
                elif await _select_aria_choice(page, field_name=field_name, value=value, dry_run=dry_run):
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
                elif await _choose_deep_native_radio(page, field_name=field_name, value=value, dry_run=dry_run):
                    filled.append(field_name)
                elif await _choose_aria_radio(page, field_name=field_name, value=value, dry_run=dry_run):
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
                elif await _check_deep_native_checkbox(page, field_name=field_name, dry_run=dry_run):
                    filled.append(field_name)
                elif await _check_aria_checkbox(page, field_name=field_name, dry_run=dry_run):
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
            if await _fill_deep_text(page, field_name=field_name, value=value, dry_run=dry_run):
                filled.append(field_name)
                continue
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
        "action_states": action_states or {},
        "skipped_already_verified": skipped_verified,
    }


async def _fill_deep_text(page: Page, *, field_name: str, value: str, dry_run: bool) -> bool:
    return bool(
        await page.evaluate(
            """({ fieldName, value, dryRun }) => {
              const element = findDeepControl(fieldName, 'input:not([type]), input[type="text"], input[type="email"], input[type="tel"], input[type="url"], textarea');
              if (!element) return false;
              element.focus();
              element.value = value;
              element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
              element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
              if (dryRun) element.setAttribute('data-joborchestrator-dry-run', 'filled');
              return true;

              function findDeepControl(fieldName, selector) {
                const wanted = normalize(fieldName);
                return collectDeep(document, selector)
                  .find(element => visible(element) && normalize(element.getAttribute('name') || element.id || element.getAttribute('aria-label') || element.getAttribute('placeholder')) === wanted) || null;
              }
              function collectDeep(root, selector) {
                const found = [];
                const visit = node => {
                  if (!node) return;
                  if (node.querySelectorAll) found.push(...Array.from(node.querySelectorAll(selector)));
                  const descendants = node.querySelectorAll ? Array.from(node.querySelectorAll('*')) : [];
                  for (const descendant of descendants) {
                    if (descendant.shadowRoot) visit(descendant.shadowRoot);
                  }
                };
                visit(root);
                return found;
              }
              function visible(element) {
                const style = window.getComputedStyle(element);
                return style.display !== 'none' && style.visibility !== 'hidden' && !element.hidden && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              }
              function normalize(raw) {
                return String(raw || '').replace(/\\s+/g, ' ').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
              }
            }""",
            {"fieldName": field_name, "value": value, "dryRun": dry_run},
        )
    )


async def _select_deep_native(page: Page, *, field_name: str, value: str, dry_run: bool) -> bool:
    return bool(
        await page.evaluate(
            """({ fieldName, value, dryRun }) => {
              const element = findDeepControl(fieldName, 'select');
              if (!element) return false;
              const wanted = normalize(value);
              const option = Array.from(element.options).find(item => normalize(item.value) === wanted || normalize(item.textContent) === wanted);
              if (!option) return false;
              element.value = option.value;
              element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
              element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
              if (dryRun) element.setAttribute('data-joborchestrator-dry-run', 'filled');
              return true;

              function findDeepControl(fieldName, selector) {
                const wanted = normalize(fieldName);
                return collectDeep(document, selector)
                  .find(element => visible(element) && normalize(element.getAttribute('name') || element.id || element.getAttribute('aria-label')) === wanted) || null;
              }
              function collectDeep(root, selector) {
                const found = [];
                const visit = node => {
                  if (!node) return;
                  if (node.querySelectorAll) found.push(...Array.from(node.querySelectorAll(selector)));
                  const descendants = node.querySelectorAll ? Array.from(node.querySelectorAll('*')) : [];
                  for (const descendant of descendants) if (descendant.shadowRoot) visit(descendant.shadowRoot);
                };
                visit(root);
                return found;
              }
              function visible(element) {
                const style = window.getComputedStyle(element);
                return style.display !== 'none' && style.visibility !== 'hidden' && !element.hidden && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              }
              function normalize(raw) {
                return String(raw || '').replace(/\\s+/g, ' ').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
              }
            }""",
            {"fieldName": field_name, "value": value, "dryRun": dry_run},
        )
    )


async def _choose_deep_native_radio(page: Page, *, field_name: str, value: str, dry_run: bool) -> bool:
    return bool(
        await page.evaluate(
            """({ fieldName, value, dryRun }) => {
              const wantedField = normalize(fieldName);
              const wantedValue = normalize(value);
              const radio = collectDeep(document, 'input[type="radio"]')
                .find(element => visible(element) && normalize(element.getAttribute('name') || element.id) === wantedField && normalize(element.value) === wantedValue);
              if (!radio) return false;
              radio.checked = true;
              radio.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
              radio.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
              if (dryRun) radio.setAttribute('data-joborchestrator-dry-run', 'filled');
              return true;

              function collectDeep(root, selector) {
                const found = [];
                const visit = node => {
                  if (!node) return;
                  if (node.querySelectorAll) found.push(...Array.from(node.querySelectorAll(selector)));
                  const descendants = node.querySelectorAll ? Array.from(node.querySelectorAll('*')) : [];
                  for (const descendant of descendants) if (descendant.shadowRoot) visit(descendant.shadowRoot);
                };
                visit(root);
                return found;
              }
              function visible(element) {
                const style = window.getComputedStyle(element);
                return style.display !== 'none' && style.visibility !== 'hidden' && !element.hidden && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              }
              function normalize(raw) {
                return String(raw || '').replace(/\\s+/g, ' ').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
              }
            }""",
            {"fieldName": field_name, "value": value, "dryRun": dry_run},
        )
    )


async def _check_deep_native_checkbox(page: Page, *, field_name: str, dry_run: bool) -> bool:
    return bool(
        await page.evaluate(
            """({ fieldName, dryRun }) => {
              const wanted = normalize(fieldName);
              const checkbox = collectDeep(document, 'input[type="checkbox"]')
                .find(element => visible(element) && normalize(element.getAttribute('name') || element.id || element.getAttribute('aria-label')) === wanted);
              if (!checkbox) return false;
              checkbox.checked = true;
              checkbox.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
              checkbox.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
              if (dryRun) checkbox.setAttribute('data-joborchestrator-dry-run', 'filled');
              return true;

              function collectDeep(root, selector) {
                const found = [];
                const visit = node => {
                  if (!node) return;
                  if (node.querySelectorAll) found.push(...Array.from(node.querySelectorAll(selector)));
                  const descendants = node.querySelectorAll ? Array.from(node.querySelectorAll('*')) : [];
                  for (const descendant of descendants) if (descendant.shadowRoot) visit(descendant.shadowRoot);
                };
                visit(root);
                return found;
              }
              function visible(element) {
                const style = window.getComputedStyle(element);
                return style.display !== 'none' && style.visibility !== 'hidden' && !element.hidden && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              }
              function normalize(raw) {
                return String(raw || '').replace(/\\s+/g, ' ').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
              }
            }""",
            {"fieldName": field_name, "dryRun": dry_run},
        )
    )


async def _select_aria_choice(page: Page, *, field_name: str, value: str, dry_run: bool) -> bool:
    result = await page.evaluate(
        """({ fieldName, value, dryRun }) => {
          function text(raw) {
            return String(raw || '').replace(/\\s+/g, ' ').trim();
          }
          function normalized(raw) {
            return text(raw).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
          }
          function visible(element) {
            const style = window.getComputedStyle(element);
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && !element.hidden
              && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
          }
          function labelFor(element) {
            const explicitLabel = element.id ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`) : null;
            if (explicitLabel) return text(explicitLabel.innerText || explicitLabel.textContent);
            const labelledBy = element.getAttribute('aria-labelledby');
            if (labelledBy) {
              const label = labelledBy.split(/\\s+/).map(part => document.getElementById(part)?.innerText || document.getElementById(part)?.textContent || '').join(' ');
              if (text(label)) return text(label);
            }
            return text(element.getAttribute('aria-label') || element.getAttribute('name') || element.id || '');
          }
          function keyFor(element) {
            return element.getAttribute('name') || element.id || element.getAttribute('aria-label') || labelFor(element);
          }
          function optionText(element) {
            return text(element.innerText || element.textContent || element.getAttribute('aria-label') || element.getAttribute('data-value') || element.getAttribute('value'));
          }
          const wantedField = normalized(fieldName);
          const wantedValue = normalized(value);
          const controls = Array.from(document.querySelectorAll('[role="combobox"], [role="listbox"]'))
            .filter(element => visible(element) && normalized(keyFor(element)) === wantedField);
          for (const control of controls) {
            control.click();
            const ownerIds = (control.getAttribute('aria-controls') || control.getAttribute('aria-owns') || '').split(/\\s+/).filter(Boolean);
            const containers = [control, ...ownerIds.map(id => document.getElementById(id)).filter(Boolean)];
            const options = containers.flatMap(container => Array.from(container.querySelectorAll('[role="option"]')));
            const option = options.find(item => visible(item) && normalized(optionText(item)) === wantedValue);
            if (!option) continue;
            option.click();
            control.setAttribute('data-joborchestrator-selected-value', value);
            if (dryRun) control.setAttribute('data-joborchestrator-dry-run', 'filled');
            return true;
          }
          return false;
        }""",
        {"fieldName": field_name, "value": value, "dryRun": dry_run},
    )
    return bool(result)


async def _choose_aria_radio(page: Page, *, field_name: str, value: str, dry_run: bool) -> bool:
    result = await page.evaluate(
        """({ fieldName, value, dryRun }) => {
          function text(raw) {
            return String(raw || '').replace(/\\s+/g, ' ').trim();
          }
          function normalized(raw) {
            return text(raw).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
          }
          function visible(element) {
            const style = window.getComputedStyle(element);
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && !element.hidden
              && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
          }
          function labelFor(element) {
            const labelledBy = element.getAttribute('aria-labelledby');
            if (labelledBy) {
              const label = labelledBy.split(/\\s+/).map(part => document.getElementById(part)?.innerText || document.getElementById(part)?.textContent || '').join(' ');
              if (text(label)) return text(label);
            }
            return text(element.getAttribute('aria-label') || element.getAttribute('name') || element.id || element.innerText || element.textContent);
          }
          function keyFor(element) {
            return element.getAttribute('name') || element.id || element.getAttribute('aria-label') || labelFor(element);
          }
          const wantedField = normalized(fieldName);
          const wantedValue = normalized(value);
          const groups = Array.from(document.querySelectorAll('[role="radiogroup"]'))
            .filter(element => visible(element) && normalized(keyFor(element)) === wantedField);
          for (const group of groups) {
            const radios = Array.from(group.querySelectorAll('[role="radio"]')).filter(visible);
            const radio = radios.find(item => normalized(labelFor(item)) === wantedValue || normalized(item.getAttribute('data-value')) === wantedValue);
            if (!radio) continue;
            radio.click();
            radios.forEach(item => item.setAttribute('aria-checked', item === radio ? 'true' : 'false'));
            group.setAttribute('data-joborchestrator-selected-value', value);
            if (dryRun) group.setAttribute('data-joborchestrator-dry-run', 'filled');
            return true;
          }
          return false;
        }""",
        {"fieldName": field_name, "value": value, "dryRun": dry_run},
    )
    return bool(result)


async def _check_aria_checkbox(page: Page, *, field_name: str, dry_run: bool) -> bool:
    result = await page.evaluate(
        """({ fieldName, dryRun }) => {
          function text(raw) {
            return String(raw || '').replace(/\\s+/g, ' ').trim();
          }
          function normalized(raw) {
            return text(raw).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
          }
          function visible(element) {
            const style = window.getComputedStyle(element);
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && !element.hidden
              && Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
          }
          function labelFor(element) {
            const labelledBy = element.getAttribute('aria-labelledby');
            if (labelledBy) {
              const label = labelledBy.split(/\\s+/).map(part => document.getElementById(part)?.innerText || document.getElementById(part)?.textContent || '').join(' ');
              if (text(label)) return text(label);
            }
            return text(element.getAttribute('aria-label') || element.getAttribute('name') || element.id || element.innerText || element.textContent);
          }
          const wantedField = normalized(fieldName);
          const checkbox = Array.from(document.querySelectorAll('[role="checkbox"]'))
            .find(element => visible(element) && normalized(element.getAttribute('name') || element.id || element.getAttribute('aria-label') || labelFor(element)) === wantedField);
          if (!checkbox) return false;
          if (checkbox.getAttribute('aria-checked') !== 'true') checkbox.click();
          checkbox.setAttribute('aria-checked', 'true');
          if (dryRun) checkbox.setAttribute('data-joborchestrator-dry-run', 'filled');
          return true;
        }""",
        {"fieldName": field_name, "dryRun": dry_run},
    )
    return bool(result)


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
                return _resume_upload_success_result(
                    field_name=field_name,
                    path=path,
                    resume_file=resume_file,
                    strategy="input_file",
                )
        except Exception:
            continue
    file_chooser_result = await _upload_resume_with_file_chooser(page, field_name=field_name, path=path, resume_file=resume_file)
    if file_chooser_result.get("status") == "uploaded":
        return file_chooser_result
    return {"status": "unresolved", "field_name": field_name, "reason": "file_input_not_found", "cleanup_path": resume_file.get("cleanup_path")}


def _resume_upload_success_result(
    *,
    field_name: str,
    path: Path,
    resume_file: dict[str, Any],
    strategy: str,
) -> dict[str, Any]:
    return {
        "status": "uploaded",
        "field_name": field_name,
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "resume_variant_id": resume_file.get("resume_variant_id"),
        "cleanup_path": resume_file.get("cleanup_path"),
        "strategy": strategy,
    }


async def _upload_resume_with_file_chooser(
    page: Page,
    *,
    field_name: str,
    path: Path,
    resume_file: dict[str, Any],
) -> dict[str, Any]:
    selectors = [
        f'button:has-text("{field_name}")',
        f'[role="button"]:has-text("{field_name}")',
        f'[aria-label*="{field_name}" i]',
        '[data-testid*="resume" i]',
        '[data-testid*="upload" i]',
        '[data-testid*="file" i]',
        '[aria-label*="resume" i]',
        '[aria-label*="upload" i]',
        '[aria-label*="attach" i]',
        'button:has-text("Upload")',
        'button:has-text("Attach")',
        'button:has-text("Resume")',
        'button:has-text("CV")',
        '[role="button"]:has-text("Upload")',
        '[role="button"]:has-text("Attach")',
        '[role="button"]:has-text("Resume")',
        '[role="button"]:has-text("CV")',
        '.dropzone',
        '[class*="dropzone"]',
        '[class*="upload"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0 or not await locator.is_visible(timeout=1000):
                continue
            async with page.expect_file_chooser(timeout=3000) as chooser_info:
                await locator.click(timeout=3000)
            chooser = await chooser_info.value
            await chooser.set_files(str(path))
            return _resume_upload_success_result(
                field_name=field_name,
                path=path,
                resume_file=resume_file,
                strategy="file_chooser",
            )
        except Exception:
            continue
    return {"status": "unresolved", "field_name": field_name, "reason": "file_chooser_not_found", "cleanup_path": resume_file.get("cleanup_path")}


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
