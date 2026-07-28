# Runbook

## Environment

Copy `.env.example` to `.env`. Configure API keys only when you need external ranking or material generation.

Important variables:

- `NEXT_PUBLIC_JOB_API_URL`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `NVIDIA_API_KEY`
- `OPENAI_API_KEY`
- `ENABLE_AUTO_SUBMIT_APPROVED` defaults off
- `APPLICATION_BROWSER_HEADLESS` defaults to `1`; set `0` to watch the local browser dry-run
- `APPLICATION_BROWSER_TIMEOUT_MS` defaults to `30000`
- `APPLICATION_BROWSER_PROFILE_DIR` optional; set it to reuse browser login/session between application dry-runs
- `ALLOW_PLAINTEXT_CREDENTIAL_STORE` defaults off; set `1` only if you accept local plaintext fallback for saved portal passwords

## Recommended v0 + Local Workers Mode

Use this when the dashboard/API are hosted in v0 and this PC runs the long jobs.

Required: the local `.env` must contain the same Turso credentials used by v0:

```bash
TURSO_DATABASE_URL=...
TURSO_AUTH_TOKEN=...
```

Then run only the workers locally:

```bash
npm run workers
```

Or separately:

```bash
python -m joborchestrator.worker
python -m joborchestrator.ranking.worker
```

In this mode:

- v0/API creates `operation_runs` in Turso.
- Local workers claim those operations from Turso.
- Playwright/browser automation runs on your PC.
- The v0 UI refreshes from the API and sees worker results.

## Full Local Mode

```bash
npm run dev:all
```

Or separately:

```bash
python -m uvicorn joborchestrator.api:app --host 127.0.0.1 --port 8000 --reload
npm run dev
python -m joborchestrator.worker
python -m joborchestrator.ranking.worker
```

Dashboard: `http://127.0.0.1:3000`
API health: `http://127.0.0.1:8000/api/health`

## Workflow

1. Upload/import CV in Profile.
2. Run scan from the dashboard or `POST /api/scans/all`.
3. Run ranking from the dashboard and start `run_ranking_worker.bat`.
4. Open Today. This is the Apply Queue ordered by priority.
5. Open a LinkedIn job with an external apply URL.
6. Click `Prepare application`.
7. The API creates a persistent session and queues `application_execution`.
8. Keep `npm run workers` running locally.
9. The worker opens the external apply URL locally with Playwright, detects the provider, extracts the form, runs mapping/fill and updates the session.
10. In `review_before_submit`, resolve unknown fields, review, then manually confirm any real submission.
11. Click `Mark submitted manually` only after you submit on the company site yourself.
12. Use verification follow-up separately when a confirmation page or email is available.

For personal Greenhouse auto-submit:

```bash
ENABLE_AUTO_SUBMIT_APPROVED=1
```

Then create the session with `"mode": "auto_submit_approved"`. The worker submits only when required fields are resolved, the resume upload succeeds, and exactly one final submit control is detected. If it blocks, inspect `application_sessions.artifacts_json.auto_submit.reasons`.

Before testing against a real company page, run the isolated local smoke. It forces SQLite, ignores `.env`/Turso, uses a synthetic Greenhouse fixture and verifies the full worker path reaches `submitted`:

```bash
npm run smoke:auto-submit
```

To rehearse a real application page without submitting, use a URL-specific dry run. Add `-- --headful` to watch Chromium:

```bash
npm run rehearse:application -- "https://boards.greenhouse.io/company/jobs/123"
npm run rehearse:application -- "https://boards.greenhouse.io/company/jobs/123" --headful
```

For login/account pages, set:

```bash
APPLICATION_BROWSER_HANDOFF=1
APPLICATION_BROWSER_HEADLESS=0
APPLICATION_BROWSER_PROFILE_DIR=data/application_browser_profile
```

Then resolve the login/check manually in the visible browser and click `Continue after manual step` in the session panel. The session stores only an opaque `local-browser://session/<uuid>` reference.

For fixture/debug Greenhouse dry-run, paste form HTML in the job drawer or call:

```bash
POST /api/jobs/{job_id}/application-sessions
{
  "provider": "greenhouse",
  "mode": "review_before_submit",
  "html": "<form id=\"application_form\">...</form>",
  "dry_run": true
}
```

## Recovery

- Stale scan operations: `POST /api/scans/all` reuses or requeues active scan work.
- Ranking jobs: use requeue failed/stale endpoints in the dashboard/API.
- Application sessions: list by job and continue from the latest state.
- Application dry-runs: inspect `application_execution` operations and `logs/worker.log`.

## Manual Steps

LinkedIn login, CAPTCHA, security checks and unresolved sensitive answers remain human actions.
