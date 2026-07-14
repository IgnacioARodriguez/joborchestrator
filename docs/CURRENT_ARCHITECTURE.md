# Current Architecture

Job Orchestrator is a local-first career operations system.

- FastAPI exposes profile, scan, ranking, materials, applications, apply queue and application-session APIs.
- SQLite is the default store; Turso/libSQL is supported through the existing connection layer.
- Next.js is the dashboard and now consumes `/api/apply-queue` as the primary work surface.
- Local Python workers process scans, rankings and material generation. Browser automation stays local and safe-by-default.
- Application automation is split into adapters under `joborchestrator/automation`.

The active vertical slice is: scan/import jobs, deduplicate, rank, compute deterministic priority, show Apply Queue, prepare materials, create a persistent application session, run Greenhouse fixture dry-run, review unknown fields, pause/resume through session state.
