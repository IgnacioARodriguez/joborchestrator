# Vercel / v0 Deployment Notes

This repository is prepared for Vercel/v0 deployment with:

- Next.js dashboard built from `dashboard/`
- FastAPI entrypoint at `api/index.py`
- Same-origin API calls in production

## What Works On Vercel Hobby

- Dashboard hosting.
- FastAPI serverless endpoints.
- ATS/search HTTP scans that finish inside function limits.
- Ranking/material generation endpoints if the required API keys are configured.

## What Does Not Fully Work As-Is

- Persistent local SQLite: Vercel Functions do not provide durable local disk.
- Long-running background workers: serverless functions are request-scoped.
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
CANDIDATE_PROFILE_YAML=<contents of candidate_profile.yml>
```

Local development still uses `job_tracker.db` unless those Turso variables are
present.

`candidate_profile.yml` is intentionally ignored by Git. In production, paste
the YAML contents into `CANDIDATE_PROFILE_YAML` so NVIDIA ranking receives the
same candidate profile used locally.

The scraper can remain local and push imported jobs into the remote database via
the API once the Vercel deployment has the Turso variables configured.

## Migrating Local Data To Turso

After creating the Turso database and setting `TURSO_DATABASE_URL` /
`TURSO_AUTH_TOKEN` locally, run:

```bash
python scripts/migrate_sqlite_to_turso.py --source job_tracker.db --replace
```

This copies the active tables from your local SQLite database to Turso.
