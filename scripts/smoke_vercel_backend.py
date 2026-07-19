from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://joborchestrator.vercel.app"

ENDPOINTS = {
    "health": "/api/health",
    "profile": "/api/profile",
    "jobs": "/api/jobs?limit=3",
    "apply_queue": "/api/apply-queue?limit=3&freshness=all",
    "applications": "/api/applications",
    "ops_status": "/api/ops/status",
    "worker_status": "/api/workers/status",
    "sources": "/api/sources",
    "scan_overview": "/api/scans/overview",
    "ranking_jobs": "/api/ranking/jobs",
}


def run_vercel_backend_smoke(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 45,
    min_jobs: int = 1,
    min_rankings: int = 1,
    require_profile: bool = True,
) -> dict[str, Any]:
    normalized_base_url = base_url.rstrip("/")
    responses = {
        name: _get_json(normalized_base_url + path, timeout_seconds=timeout_seconds)
        for name, path in ENDPOINTS.items()
    }
    summary = summarize_backend_responses(responses)
    checks = evaluate_backend_summary(
        summary,
        min_jobs=min_jobs,
        min_rankings=min_rankings,
        require_profile=require_profile,
    )
    return {
        "passed": checks["passed"],
        "mode": "vercel_backend_readonly",
        "base_url": normalized_base_url,
        "checks": checks,
        "summary": summary,
    }


def summarize_backend_responses(responses: dict[str, Any]) -> dict[str, Any]:
    jobs = responses.get("jobs") or {}
    apply_queue = responses.get("apply_queue") or {}
    profile = (responses.get("profile") or {}).get("profile")
    applications = (responses.get("applications") or {}).get("applications") or []
    ops_status = responses.get("ops_status") or {}
    worker_status = responses.get("worker_status") or {}
    scan_overview_payload = responses.get("scan_overview") or {}
    scan_overview = scan_overview_payload.get("overview") or {}
    scan_errors = scan_overview_payload.get("errors") or []
    ranking_jobs = (responses.get("ranking_jobs") or {}).get("jobs") or []
    sources = responses.get("sources") or {}

    latest_scan = ops_status.get("latest_scan_operation")
    latest_ranking = ops_status.get("latest_ranking_job") or (ranking_jobs[0] if ranking_jobs else None)

    return {
        "health": responses.get("health"),
        "db_modes": _collect_db_modes(jobs, apply_queue, ops_status, worker_status),
        "profile_present": bool(profile),
        "profile_keys": sorted(profile.keys()) if isinstance(profile, dict) else [],
        "jobs_total": ((jobs.get("meta") or {}).get("total")),
        "jobs_returned": len(jobs.get("jobs") or []),
        "apply_queue_total": ((apply_queue.get("meta") or {}).get("total")),
        "apply_queue_returned": len(apply_queue.get("jobs") or []),
        "applications_returned": len(applications),
        "sources_returned": len(sources.get("sources") or []),
        "ranking_jobs_returned": len(ranking_jobs),
        "latest_ranking_job": _summarize_ranking_job(latest_ranking),
        "worker_status": {
            "pending_count": worker_status.get("pending_count"),
            "running_count": worker_status.get("running_count"),
            "needs_local_worker": worker_status.get("needs_local_worker"),
        },
        "ops_status": {
            "local_worker_needed": ops_status.get("local_worker_needed"),
            "ranking_worker_needed": ops_status.get("ranking_worker_needed"),
            "summary": ops_status.get("summary"),
        },
        "scan_overview": {
            "total_jobs": scan_overview.get("total_jobs"),
            "recent_errors": scan_overview.get("recent_errors"),
            "last_scan_status": scan_overview.get("last_scan_status"),
            "last_scan": scan_overview.get("last_scan"),
        },
        "recent_scan_errors": [_summarize_scan_error(error) for error in scan_errors[:5]],
        "latest_scan_operation": _summarize_operation(latest_scan),
    }


def evaluate_backend_summary(
    summary: dict[str, Any],
    *,
    min_jobs: int = 1,
    min_rankings: int = 1,
    require_profile: bool = True,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []

    if summary.get("health") != {"status": "ok"}:
        failures.append("Health endpoint did not return {'status': 'ok'}.")
    db_modes = set(summary.get("db_modes") or [])
    if "turso" not in db_modes:
        failures.append("Backend did not report db_mode=turso.")
    if int(summary.get("jobs_total") or 0) < min_jobs:
        failures.append(f"Expected at least {min_jobs} jobs from /api/jobs.")
    if int(summary.get("ranking_jobs_returned") or 0) < min_rankings:
        failures.append(f"Expected at least {min_rankings} ranking jobs.")
    if require_profile and not summary.get("profile_present"):
        failures.append("Profile endpoint returned no candidate profile.")

    latest_ranking = summary.get("latest_ranking_job") or {}
    failed_items = int(latest_ranking.get("failed_items") or 0)
    if failed_items:
        warnings.append(f"Latest ranking job has {failed_items} failed items.")

    scan_overview = summary.get("scan_overview") or {}
    if scan_overview.get("last_scan_status") == "error":
        warnings.append("Latest scan status is error.")
    if int(scan_overview.get("recent_errors") or 0) > 0:
        warnings.append(f"Scan overview reports {scan_overview['recent_errors']} recent errors.")
    recent_scan_errors = summary.get("recent_scan_errors") or []
    if recent_scan_errors:
        warnings.append(
            "Recent scan error sample: "
            + "; ".join(
                f"{item.get('provider') or 'unknown'}:{item.get('company_name') or 'unknown'}"
                for item in recent_scan_errors[:3]
            )
        )

    latest_scan = summary.get("latest_scan_operation") or {}
    if latest_scan.get("error"):
        warnings.append(f"Latest scan operation error: {latest_scan['error']}")
    output_errors = latest_scan.get("output_errors") or {}
    for source, message in sorted(output_errors.items()):
        warnings.append(f"Latest scan output error for {source}: {message}")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "thresholds": {
            "min_jobs": min_jobs,
            "min_rankings": min_rankings,
            "require_profile": require_profile,
        },
    }


def _get_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "joborchestrator-vercel-smoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not (200 <= response.status < 300):
                raise RuntimeError(f"{url} returned HTTP {response.status}: {body[:500]}")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {body[:500]}") from exc


def _collect_db_modes(*payloads: dict[str, Any]) -> list[str]:
    modes: set[str] = set()
    for payload in payloads:
        mode = payload.get("mode")
        if mode:
            modes.add(str(mode))
        meta_mode = (payload.get("meta") or {}).get("db_mode")
        if meta_mode:
            modes.add(str(meta_mode))
    return sorted(modes)


def _summarize_ranking_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "id": job.get("id"),
        "provider": job.get("provider"),
        "model": job.get("model"),
        "ranking_version": job.get("ranking_version"),
        "status": job.get("status"),
        "total_items": job.get("total_items"),
        "processed_items": job.get("processed_items"),
        "saved_items": job.get("saved_items"),
        "failed_items": job.get("failed_items"),
        "latest_item_error": job.get("latest_item_error"),
    }


def _summarize_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not operation:
        return None
    output = operation.get("output_json") or {}
    return {
        "id": operation.get("id"),
        "type": operation.get("type"),
        "status": operation.get("status"),
        "progress_message": operation.get("progress_message"),
        "error": operation.get("error"),
        "output_errors": output.get("errors") or {},
    }


def _summarize_scan_error(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": error.get("provider"),
        "company_name": error.get("company_name"),
        "error": _truncate(error.get("error"), 240),
        "finished_at": error.get("finished_at"),
    }


def _truncate(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only smoke against the deployed Vercel backend.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Production or preview deployment URL.")
    parser.add_argument("--timeout-seconds", type=float, default=45, help="Per-endpoint timeout.")
    parser.add_argument("--min-jobs", type=int, default=1, help="Minimum expected /api/jobs total.")
    parser.add_argument("--min-rankings", type=int, default=1, help="Minimum expected ranking jobs.")
    parser.add_argument(
        "--allow-missing-profile",
        action="store_true",
        help="Do not fail if /api/profile has no candidate profile.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_vercel_backend_smoke(
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            min_jobs=args.min_jobs,
            min_rankings=args.min_rankings,
            require_profile=not args.allow_missing_profile,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print a readable smoke failure.
        print(json.dumps({"passed": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
