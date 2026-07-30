# Backend instructions

Applies to `joborchestrator/`, including `api.py`, `worker.py`, and nested packages. More specific nested files take precedence.

## Architecture

- Keep FastAPI request handling short-lived.
- Keep long-running AI, scanning, and browser operations in workers.
- Preserve API, worker, storage, artifact, and serialization compatibility unless the task explicitly allows a breaking change.
- Reuse existing models, repositories, services, and state transitions before adding abstractions.
- Trace only direct consumers of changed contracts.

## Implementation

- Prefer explicit state transitions and idempotent operations.
- Preserve retry, recovery, and failure semantics.
- Do not hide failures behind broad exception handling.
- Avoid adding network calls to request paths.
- Keep production and external access read-only unless explicitly authorized.

## Validation

Localized backend change:

```powershell
python -m pytest <exact-tests-or-node-ids> -q --maxfail=1
```

Run full backend validation once at completion only for cross-cutting changes involving shared contracts, multiple backend surfaces, storage, API-worker interaction, or broad behavior:

```powershell
python -m pytest
```

Add frontend checks only when a frontend-consumed contract changed.
