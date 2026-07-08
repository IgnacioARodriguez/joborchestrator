# Vercel / v0 Deployment Notes

This repository is prepared for Vercel/v0 deployment with:

- Next.js dashboard built from the repository root
- FastAPI entrypoint at `api/index.py`
- Same-origin API calls in production

## What Works On Vercel Hobby

- Dashboard hosting.
- FastAPI serverless endpoints.
- ATS/search HTTP scans that finish inside function limits.
- Ranking/material generation endpoints if the required API keys are configured
  and the operation finishes inside function limits.
- Queuing CV profile imports into Turso.

## What Does Not Fully Work As-Is

- Persistent local SQLite: Vercel Functions do not provide durable local disk.
- Long-running background workers: serverless functions are request-scoped.
- CV profile extraction should be processed by the local worker on your PC.
- LinkedIn Playwright scraper: it needs a local browser/session and should remain
  a local/manual ingestion step.

## Temporary Ephemeral DB

For a throwaway preview, set:

```text
JOB_ORCHESTRATOR_DB_PATH=/tmp/job_tracker.db
```

This lets the API boot, but data can disappear between cold starts. It is useful
only for smoke tests, not real use.

## Production-Ready Free/Low-Cost Path

Use Turso/libSQL from the Vercel Marketplace. Turso is SQLite-compatible, so the
app can keep the current SQL model without a full Postgres rewrite.

Set these environment variables in Vercel:

```text
TURSO_DATABASE_URL=libsql://...
TURSO_AUTH_TOKEN=...
NVIDIA_API_KEY=...
```

Local development still uses `job_tracker.db` unless those Turso variables are
present.

The candidate profile is stored in the `app_settings` table in Turso. Upload a
CV in the dashboard, keep `run_worker.bat` running locally, and the worker will
read queued operations from Turso, call NVIDIA, save the profile, and write logs
to `logs/worker.log`.

The scraper can remain local and push imported jobs into the remote database via
the API once the Vercel deployment has the Turso variables configured.

## Migrating Local Data To Turso

After creating the Turso database and setting `TURSO_DATABASE_URL` /
`TURSO_AUTH_TOKEN` locally, run:

```bash
python scripts/migrate_sqlite_to_turso.py --source job_tracker.db --replace
```

This copies the active tables from your local SQLite database to Turso.
