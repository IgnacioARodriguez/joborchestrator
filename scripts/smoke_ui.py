from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import Page, expect, sync_playwright

from joborchestrator.ranking.schemas import RankingEvidence, RankingResult, RankingScores
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION
from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash
from joborchestrator.storage import persistence as db
from scripts.smoke_e2e import synthetic_profile


def run_ui_smoke(
    *,
    db_path: Path | None = None,
    dashboard_port: int | None = None,
    api_port: int | None = None,
    headless: bool = True,
    keep_servers: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="joborchestrator-ui-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        active_db = db_path or tmp_path / "ui_smoke.db"
        seed = seed_ui_database(active_db)
        selected_dashboard_port = dashboard_port or _first_free_port([3000, 3001])
        selected_api_port = api_port or _free_port()
        dashboard_url = f"http://127.0.0.1:{selected_dashboard_port}"
        api_url = f"http://127.0.0.1:{selected_api_port}"

        env = _server_env(active_db, api_url)
        api_log = tmp_path / "api.log"
        dashboard_log = tmp_path / "dashboard.log"
        api_proc = _start_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "joborchestrator.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(selected_api_port),
            ],
            env=env,
            log_path=api_log,
        )
        dashboard_proc = _start_process(
            [
                _npm_command(),
                "run",
                "dev",
                "--",
                "-H",
                "127.0.0.1",
                "-p",
                str(selected_dashboard_port),
            ],
            env=env,
            log_path=dashboard_log,
        )
        console_errors: list[str] = []
        screenshot_path = PROJECT_ROOT / "logs" / "ui-smoke.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _wait_for_url(f"{api_url}/api/health", api_proc, api_log, label="api")
            _wait_for_url(dashboard_url, dashboard_proc, dashboard_log, label="dashboard", timeout=90)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=headless)
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.goto(dashboard_url, wait_until="networkidle", timeout=60_000)
                _verify_dashboard(page, seed)
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
            serious_console_errors = [
                error
                for error in console_errors
                if "favicon" not in error.lower() and "failed to load resource" not in error.lower()
            ]
            return {
                "passed": not serious_console_errors,
                "mode": "ui",
                "database": str(active_db),
                "dashboard_url": dashboard_url,
                "api_url": api_url,
                "job_count": seed["job_count"],
                "checked_sections": ["Today", "Review", "Applications", "Profile", "Automations", "Insights"],
                "console_errors": serious_console_errors,
                "screenshot": str(screenshot_path),
            }
        finally:
            if not keep_servers:
                _stop_process_tree(dashboard_proc)
                _stop_process_tree(api_proc)


def seed_ui_database(db_path: Path) -> dict[str, Any]:
    with _isolated_db_path(db_path):
        db.init_db()
        profile = synthetic_profile()
        db.save_candidate_profile_payload(profile)
        job_ids = []
        for index, (title, company, score, decision) in enumerate(
            [
                ("Senior Backend Engineer", "Acme Cloud", 91, "APPLY_NOW"),
                ("Platform Engineer", "Remote SaaS", 84, "APPLY_WITH_TAILORED_CV"),
            ],
            start=1,
        ):
            job = _ui_job(index=index, title=title, company=company)
            db.upsert_job_posting(job, seen_at=datetime.now().isoformat(timespec="seconds"))
            rows = db.get_job_postings(limit=None)
            job_id = int(rows[rows["external_id"] == job.external_id].iloc[0]["id"])
            job_ids.append(job_id)
            db.save_job_ranking(job_id, _ui_ranking(score, decision))
            db.update_job_application_materials(
                job_id,
                pipeline_status="shortlisted",
                recruiter_message=f"Hi {company}, Python and FastAPI backend fit for {title}.",
                cover_letter=f"{company} needs {title} execution with Python, FastAPI and PostgreSQL.",
                ats_cv_text=profile["base_cv_text"],
                autofill_notes="Use Python, FastAPI, PostgreSQL and AWS examples.",
            )
        application = db.create_application(
            {
                "job_id": job_ids[0],
                "ats_type": "greenhouse",
                "status": "submitted",
                "channel": "portal",
            }
        )
        return {
            "job_count": len(job_ids),
            "primary_job_id": job_ids[0],
            "primary_job_title": "Senior Backend Engineer",
            "primary_company": "Acme Cloud",
            "application_id": application["id"],
        }


def _verify_dashboard(page: Page, seed: dict[str, Any]) -> None:
    expect(page.get_by_text("Job Orchestrator").first).to_be_visible(timeout=30_000)
    expect(page.get_by_text(seed["primary_job_title"]).first).to_be_visible(timeout=30_000)
    expect(page.get_by_text(seed["primary_company"]).first).to_be_visible(timeout=30_000)

    _click_nav(page, "Review")
    expect(page.get_by_role("heading", name="Opportunity review")).to_be_visible(timeout=15_000)
    expect(page.get_by_placeholder("Search title, company, location")).to_be_visible(timeout=15_000)

    _click_nav(page, "Applications")
    expect(page.get_by_role("heading", name="Application kanban")).to_be_visible(timeout=15_000)
    expect(page.get_by_text("Submitted").first).to_be_visible(timeout=15_000)

    _click_nav(page, "Profile")
    expect(page.get_by_role("heading", name="Candidate profile")).to_be_visible(timeout=15_000)
    expect(page.get_by_text("Senior backend engineer").first).to_be_visible(timeout=15_000)

    _click_nav(page, "Automations")
    expect(page.get_by_role("heading", name="Automation control room")).to_be_visible(timeout=15_000)

    _click_nav(page, "Insights")
    expect(page.get_by_role("heading", name="Performance signals")).to_be_visible(timeout=15_000)


def _click_nav(page: Page, name: str) -> None:
    page.get_by_role("button", name=name).first.click(timeout=15_000)
    page.wait_for_timeout(250)


def _ui_job(*, index: int, title: str, company: str) -> JobPosting:
    location = "Remote Spain"
    apply_url = f"https://example.com/apply/ui-smoke-{index}"
    description = (
        f"{company} is hiring a {title}. Requirements include Python, FastAPI, PostgreSQL, AWS, "
        "API design and 5+ years backend experience."
    )
    return JobPosting(
        external_id=f"ui-smoke-{index}",
        source="greenhouse" if index == 1 else "remotive",
        company=company,
        title=title,
        location=location,
        workplace_type="Remote",
        url=apply_url,
        apply_url=apply_url,
        description_text=description,
        content_hash=compute_content_hash(title, company, location, description, apply_url),
        raw_payload={"source": "ui_smoke", "index": index},
    )


def _ui_ranking(score: int, decision: str) -> RankingResult:
    return RankingResult(
        final_score=score,
        decision=decision,  # type: ignore[arg-type]
        confidence=0.92,
        scores=RankingScores(
            technical_fit=score,
            seniority_fit=score,
            role_fit=score,
            opportunity_quality=max(70, score - 5),
            application_roi=score,
            market_alignment=max(70, score - 3),
            risk_penalty=1,
            central_requirement_coverage=94,
        ),
        evidence=RankingEvidence(
            strong_matches=["Python", "FastAPI", "PostgreSQL", "AWS"],
            missing_requirements=[],
            dealbreakers=[],
            central_requirement_coverage=94,
        ),
        reasoning_summary="UI smoke seeded ranking with strong backend fit.",
        recommended_application_angle="Emphasize Python, FastAPI, PostgreSQL, AWS and API delivery.",
        cv_keywords_to_emphasize=["Python", "FastAPI", "PostgreSQL", "AWS", "API design"],
        cv_keywords_to_avoid_overclaiming=[],
        ranking_version=NVIDIA_RANKING_VERSION,
    )


@contextmanager
def _isolated_db_path(db_path: Path) -> Iterator[None]:
    old_path = db.DB_PATH
    old_turso_url = os.environ.pop("TURSO_DATABASE_URL", None)
    old_turso_token = os.environ.pop("TURSO_AUTH_TOKEN", None)
    db.DB_PATH = db_path
    try:
        yield
    finally:
        db.DB_PATH = old_path
        if old_turso_url is not None:
            os.environ["TURSO_DATABASE_URL"] = old_turso_url
        if old_turso_token is not None:
            os.environ["TURSO_AUTH_TOKEN"] = old_turso_token


def _server_env(db_path: Path, api_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TURSO_DATABASE_URL", None)
    env.pop("TURSO_AUTH_TOKEN", None)
    env["JOB_ORCHESTRATOR_DB_PATH"] = str(db_path)
    env["NEXT_PUBLIC_JOB_API_URL"] = api_url
    env["JOB_ORCHESTRATOR_SKIP_ENV_FILE"] = "1"
    return env


def _start_process(command: list[str], *, env: dict[str, str], log_path: Path) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _wait_for_url(url: str, proc: subprocess.Popen[Any], log_path: Path, *, label: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{label} process exited early with code {proc.returncode}: {_tail(log_path)}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready at {url}: {last_error}\n{_tail(log_path)}")


def _tail(path: Path, max_chars: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def _stop_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/t", "/f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _first_free_port(candidates: list[int]) -> int:
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"None of these dashboard ports are free: {candidates}")


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a browser UI smoke test for Job Orchestrator.")
    parser.add_argument("--db-path", type=Path, help="Optional SQLite path. Defaults to a temporary DB.")
    parser.add_argument("--dashboard-port", type=int, choices=[3000, 3001], help="Dashboard port allowed by API CORS.")
    parser.add_argument("--api-port", type=int, help="Optional API port. Defaults to a free port.")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while the smoke runs.")
    parser.add_argument("--keep-servers", action="store_true", help="Leave API and dashboard running after the smoke.")
    args = parser.parse_args(argv)

    try:
        result = run_ui_smoke(
            db_path=args.db_path,
            dashboard_port=args.dashboard_port,
            api_port=args.api_port,
            headless=not args.headed,
            keep_servers=args.keep_servers,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
