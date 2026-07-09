# Job Orchestrator

Local career-ops app for discovering, AI-ranking, and tracking job
opportunities.

The active product is:

- **FastAPI backend** over the existing Python core and SQLite/Turso storage.
- **Next.js dashboard** as the main user interface, built from the repository root.
- **Local Python worker** for long-running AI tasks that should not run inside
  Vercel serverless time limits.
- **Python core** for LinkedIn import, ATS scans, search API scans, NVIDIA LLM
  ranking, and application material generation.

The old Streamlit app has been removed from the active codebase.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
npm install
```

Copy the local environment template and fill your keys once:

```bash
copy .env.example .env
```

## Run Locally

Start the API:

```bash
run_api.bat
```

Or manually:

```bash
python -m uvicorn joborchestrator.api:app --host 127.0.0.1 --port 8000 --reload
```

Start the dashboard:

```bash
npm run dev
```

Start the local worker when you want to process queued long-running tasks such
as CV profile extraction:

```bash
run_worker.bat
```

Open:

- Dashboard: `http://127.0.0.1:3000`
- API health: `http://127.0.0.1:8000/api/health`

## Deploy To Vercel / v0

The repo includes a Vercel entrypoint:

- `vercel.json`
- `api/index.py`
- dashboard production API calls use same-origin `/api/*`

See [VERCEL_DEPLOYMENT.md](./VERCEL_DEPLOYMENT.md) for limits and the production storage path. Short version:

- Vercel/v0 can host the dashboard and short FastAPI functions.
- Local SQLite is not durable on Vercel.
- Long AI tasks are queued in Turso and processed by `run_worker.bat` on your PC.
- The LinkedIn Playwright scraper should remain local/manual or move to a
  separate worker.
- For real remote use, configure Turso/libSQL via `TURSO_DATABASE_URL` and
  `TURSO_AUTH_TOKEN`.

## Main Structure

```text
joborchestrator/
|-- app/                       # Active Next.js app routes
|-- components/                # Active dashboard components
|-- lib/                       # Active dashboard API client and types
|-- dashboard/                 # Legacy v0 duplicate, not used by root build
|-- joborchestrator/
|   |-- api.py                 # FastAPI adapter for the dashboard
|   |-- worker.py              # Local operation worker
|   |-- scanning/              # LinkedIn importer, ATS providers, search APIs
|   |-- ranking/               # Ranking models, rankers, NVIDIA worker
|   |-- intelligence/          # Application materials and supporting signals
|   |-- storage/               # SQLite/Turso persistence
|   |-- batching.py            # LinkedIn Excel filtering utilities
|   `-- paths.py               # Shared local paths
|-- tests/                     # Python tests
|-- job_tracker.db             # Local SQLite database, ignored by Git
|-- requirements.txt
|-- run_api.bat
`-- run_worker.bat
```

## Dashboard Capabilities

- Load real opportunities from `job_tracker.db`.
- Import the latest LinkedIn scraper Excel output.
- Add and scan ATS sources such as Greenhouse, Lever, and Ashby.
- Run public search API scans.
- Queue and process NVIDIA LLM ranking jobs.
- Track pipeline state: new, opened, shortlisted, applied, discarded.
- Generate application kits: recruiter message, cover letter, ATS CV notes, and
  autofill notes.

## Useful Commands

Backend tests:

```bash
python -m pytest
```

Dashboard checks:

```bash
npm run lint
npm run typecheck
npm run build
```

Local operation worker:

```bash
python -m joborchestrator.worker --once
python -m joborchestrator.worker
```

This worker processes async operations such as CV profile imports. Local logs are written to `logs/worker.log`.

LinkedIn scraper:

```bash
python -m joborchestrator.scanning.linkedin
```

Ranking worker:

```bash
python -m joborchestrator.ranking.worker --once
python -m joborchestrator.ranking.worker
```

On Windows you can also run:

```bash
run_ranking_worker.bat
```

The dashboard queues NVIDIA ranking jobs, but long-running ranking is processed by this local worker. Local ranking logs are written to `logs/ranking-worker.log`. The API `run-once` endpoint is disabled by default to avoid Vercel/serverless timeouts; set `ALLOW_API_RANKING_RUN_ONCE=1` only for controlled local debugging.

## Local Data

Ignored local/runtime files include:

- `.venv/`
- `.env`
- `job_tracker.db`
- `data/*` except `data/.gitkeep`
- Python caches and test caches
- local dev and worker logs
