from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smoke_vercel_backend import DEFAULT_BASE_URL, run_vercel_backend_smoke


SECTIONS = {
    "Today": "Action queue",
    "Review": "Opportunity review",
    "Applications": "Application kanban",
    "Profile": "Candidate profile",
    "Automations": "Automation control room",
    "Insights": "Performance signals",
}


def run_vercel_ui_smoke(
    *,
    base_url: str = DEFAULT_BASE_URL,
    headless: bool = True,
    screenshot_path: Path | None = None,
    backend_attempts: int = 3,
) -> dict[str, Any]:
    normalized_base_url = base_url.rstrip("/")
    backend: dict[str, Any] | None = None
    backend_error: str | None = None
    try:
        backend = _run_backend_preflight(normalized_base_url, attempts=backend_attempts)
        if not backend["passed"]:
            return {
                "passed": False,
                "mode": "vercel_ui_readonly",
                "base_url": normalized_base_url,
                "backend": _compact_backend_result(backend, None),
                "ui": None,
            }
    except Exception as exc:  # noqa: BLE001 - UI should still prove what the browser sees.
        backend_error = f"{type(exc).__name__}: {exc}"

    target_screenshot = screenshot_path or PROJECT_ROOT / "logs" / "vercel-ui-smoke.png"
    target_screenshot.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    failed_requests: list[str] = []
    responses: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
        page.on("response", lambda response: _record_response(responses, response.url, response.status))
        try:
            page.goto(normalized_base_url, wait_until="networkidle", timeout=90_000)
            ui_summary = verify_production_ui(page, backend["summary"] if backend else {})
            page.screenshot(path=str(target_screenshot), full_page=True)
        finally:
            browser.close()

    serious_console_errors = [
        error
        for error in console_errors
        if "favicon" not in error.lower() and "failed to load resource" not in error.lower()
    ]
    serious_failed_requests = [
        request
        for request in failed_requests
        if "favicon" not in request.lower() and "/_next/static/" not in request.lower()
    ]
    server_errors = [response for response in responses if response["status"] >= 500]
    ui_passed = not serious_console_errors and not serious_failed_requests and not server_errors
    return {
        "passed": bool((backend is None or backend["passed"]) and ui_passed),
        "mode": "vercel_ui_readonly",
        "base_url": normalized_base_url,
        "backend": _compact_backend_result(backend, backend_error),
        "ui": ui_summary,
        "console_errors": serious_console_errors,
        "failed_requests": serious_failed_requests,
        "server_errors": server_errors,
        "api_response_count": len(responses),
        "screenshot": str(target_screenshot),
    }


def verify_production_ui(page: Page, backend_summary: dict[str, Any]) -> dict[str, Any]:
    expect(page.get_by_text("Job Orchestrator").first).to_be_visible(timeout=30_000)
    expect(page.get_by_role("heading", name="Action queue")).to_be_visible(timeout=30_000)

    checked_sections: list[str] = []
    for nav_label, heading in SECTIONS.items():
        _click_nav(page, nav_label)
        expect(page.get_by_role("heading", name=heading)).to_be_visible(timeout=30_000)
        checked_sections.append(nav_label)

    text = page.locator("body").inner_text(timeout=15_000)
    require_screen_text(text, backend_summary)
    return {
        "checked_sections": checked_sections,
        "body_text_chars": len(text),
        "visible_profile": bool(backend_summary.get("profile_present")),
        "visible_jobs_total": backend_summary.get("jobs_total"),
    }


def require_screen_text(body_text: str, backend_summary: dict[str, Any]) -> None:
    required_labels = [
        "Job Orchestrator",
        "Performance signals",
        "turso",
    ]
    if backend_summary.get("profile_present"):
        required_labels.append("Profile")
    missing = [label for label in required_labels if label not in body_text]
    if missing:
        raise AssertionError(f"Production UI missing expected text: {', '.join(missing)}")


def _click_nav(page: Page, name: str) -> None:
    page.get_by_role("button", name=name).first.click(timeout=15_000)
    page.wait_for_load_state("networkidle", timeout=30_000)


def _record_response(responses: list[dict[str, Any]], url: str, status: int) -> None:
    if "/api/" in url:
        responses.append({"url": url, "status": status})


def _run_backend_preflight(base_url: str, *, attempts: int) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result = run_vercel_backend_smoke(base_url=base_url)
        except Exception as exc:  # noqa: BLE001 - retries should capture transient network failures.
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        else:
            if attempt > 1:
                result.setdefault("checks", {}).setdefault("warnings", []).append(
                    f"Backend preflight succeeded after {attempt} attempts."
                )
            return result
        time.sleep(min(2 * attempt, 10))
    raise RuntimeError("; ".join(errors))


def _compact_backend_result(backend: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    if backend is None:
        return {"passed": None, "error": error, "warnings": ["Backend preflight failed; UI browser checks continued."]}
    return {
        "passed": backend["passed"],
        "warnings": backend["checks"].get("warnings", []),
        "summary": {
            "db_modes": backend["summary"].get("db_modes"),
            "jobs_total": backend["summary"].get("jobs_total"),
            "profile_present": backend["summary"].get("profile_present"),
            "applications_returned": backend["summary"].get("applications_returned"),
            "ranking_jobs_returned": backend["summary"].get("ranking_jobs_returned"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only browser smoke against the deployed Vercel UI.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Production or preview deployment URL.")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while the smoke runs.")
    parser.add_argument("--screenshot-path", type=Path, help="Optional screenshot output path.")
    parser.add_argument("--backend-attempts", type=int, default=3, help="Retries for the backend preflight.")
    args = parser.parse_args(argv)

    try:
        result = run_vercel_ui_smoke(
            base_url=args.base_url,
            headless=not args.headed,
            screenshot_path=args.screenshot_path,
            backend_attempts=args.backend_attempts,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
