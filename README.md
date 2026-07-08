# Job Orchestrator

Local career-ops app for discovering, AI-ranking, and tracking job
opportunities.

The active product is:

- **FastAPI backend** over the existing Python core and local SQLite database.
- **Next.js dashboard** as the main user interface.
- **Python core** for LinkedIn import, ATS scans, search API scans, NVIDIA LLM
  ranking, and application material generation.

The old Streamlit app has been removed from the active codebase.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cd dashboard
npm install
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
cd dashboard
npm run dev
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

- Vercel/v0 can host the dashboard and FastAPI functions.
- Local SQLite is not durable on Vercel.
- The LinkedIn Playwright scraper should remain local/manual or move to a
  separate worker.
- For real remote use, configure Turso/libSQL via `TURSO_DATABASE_URL` and
  `TURSO_AUTH_TOKEN`.

## Main Structure

```text
joborchestrator/
|-- dashboard/                 # Next.js UI
|-- joborchestrator/
|   |-- api.py                 # FastAPI adapter for the dashboard
|   |-- scanning/              # LinkedIn importer, ATS providers, search APIs
|   |-- ranking/               # Ranking models, rankers, NVIDIA worker
|   |-- intelligence/          # Application materials and supporting signals
|   |-- storage/               # SQLite/Turso persistence
|   |-- batching.py            # LinkedIn Excel filtering utilities
|   `-- paths.py               # Shared local paths
|-- tests/                     # Python tests
|-- candidate_profile.yml      # Local candidate ranking profile, ignored by Git
|-- job_tracker.db             # Local SQLite database, ignored by Git
|-- requirements.txt
`-- run_api.bat
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
cd dashboard
npm run lint
npm run typecheck
npm run build
```

LinkedIn scraper:

```bash
python -m joborchestrator.scanning.linkedin
```

Ranking worker:

```bash
python -m joborchestrator.ranking.worker --once
```

## Local Data

Ignored local/runtime files include:

- `.venv/`
- `job_tracker.db`
- `data/*` except `data/.gitkeep`
- Python caches and test caches
- local dev logs
