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

To keep this running remotely, replace SQLite persistence with a serverless
database from Vercel Marketplace or another free tier provider, for example:

- Neon Postgres
- Supabase Postgres
- Upstash

The dashboard can stay on Vercel/v0. The scraper can remain local and push
imported jobs into the remote database via an authenticated API endpoint.
