# AGENTS.md — Job Orchestrator

## Operating goal

Make the smallest safe, reviewable change that satisfies the current task. Optimize for correctness, targeted verification, low unnecessary token use, and honest evidence.

Task-specific instructions override this file. More specific nested `AGENTS.md` files may add narrower rules.

## Repository map

- `app/`, `components/`, `lib/`: active Next.js dashboard.
- `dashboard/`: legacy duplicate; do not edit unless explicitly requested.
- `joborchestrator/api.py`: FastAPI API.
- `joborchestrator/worker.py`: local long-running operation worker.
- `joborchestrator/automation/`: application browser engine.
- `joborchestrator/scanning/`: imports, ATS providers, and search APIs.
- `joborchestrator/ranking/`: ranking models, prompts, and worker.
- `joborchestrator/intelligence/`: application materials and supporting signals.
- `joborchestrator/storage/`: SQLite/Turso persistence.
- `tests/`: Python tests.
- `scripts/`: smoke, audit, eval, seed, and maintenance commands.
- `docs/`: architecture, safety, trust, and operating evidence.

The root Next.js app is active. Long-running AI/browser work belongs in local workers, not Vercel serverless handlers.

## Evidence and scope

Use this source order when information conflicts:

1. Current user task and acceptance criteria.
2. More specific `AGENTS.md`.
3. This file.
4. Current code, tests, schemas, and fixtures.
5. Documentation and historical reports.

Before editing:

1. Run `git status --short --branch`.
2. Identify branch, base, and relevant diff.
3. Locate symbols with `rg`.
4. Trace only direct callers, consumers, tests, serialization, API, and UI affected.
5. Reuse existing abstractions before creating new ones.
6. Separate baseline failures from regressions.

Do not scan the entire repository by default. Expand only when evidence shows a wider dependency.

Do not perform unrelated cleanup, renames, dependency upgrades, formatting, or architectural rewrites. Preserve API, artifact, storage, worker, fixture, and frontend compatibility unless the task explicitly permits a breaking change. Prefer additive, non-destructive changes.

## Application automation safety

Default to review-before-submit.

Unless explicitly authorized for a controlled test:

- Never submit a real application or enable/broaden auto-submit.
- Never accept legal consent, terms, privacy acknowledgements, declarations, certifications, signatures, or background-check authorization.
- Never solve CAPTCHA, MFA, login challenges, password recovery, or email verification.
- Never create irreversible accounts or withdraw applications.
- Prefer local fixtures, snapshots, and `data:` pages over real portals.
- Never expose secrets, cookies, tokens, production records, or personal data.

Work authorization and sponsorship are not generic legal consent; fill them only from exact, current, approved answers under policy.

Fail closed on unknown required controls, ambiguous mappings, unverified uploads, pending validation, unsupported controls, and uncertain postconditions.

## Token-efficient workflow

Context is scarce. Spend it on relevant code and evidence.

- Search before opening files.
- Read relevant ranges, not entire large files.
- Do not reopen unchanged files without a new reason.
- Reuse verified findings within the same task.
- Use `git diff --stat` before reviewing focused diffs.
- Do not print large JSON, databases, lockfiles, environment dumps, generated files, or long logs.
- Use concise command output and summarize counts, failures, and relevant excerpts.
- Do not narrate routine operations or restate the full task after each commit.
- Ask only questions that materially change architecture, safety, or scope.
- Stop exploration once acceptance criteria can be safely implemented and verified.

Progress updates should report only a meaningful finding, blocker, scope change, or validation result.

Final reports should contain changed behavior, commits/files, tests, remaining real risks, and one next action. Do not repeat the prompt or include large code excerpts.

## Efficient validation

The project uses Python `pytest` and a Next.js/TypeScript frontend.

### Default test cadence

For substantial multi-commit work:

1. One initial full backend baseline.
2. Exact or targeted tests during implementation.
3. Relevant subsystem tests before each commit.
4. One final full backend suite.
5. Extra full runs only after a genuinely cross-cutting change or after fixing a final-suite failure.

For small localized work, skip the initial full suite when targeted tests establish a reliable baseline.

Do not run the full suite after every edit or commit.

### Backend

Full suite:

```powershell
python -m pytest
```

Targeted development:

```powershell
python -m pytest <test-files-or-node-ids> -q --maxfail=1
```

Repeat previous failures:

```powershell
python -m pytest --lf -x
```

Temporary selection while locating exact tests:

```powershell
python -m pytest -q --maxfail=1 -k "<relevant expression>"
```

Once exact tests are known, stop using broad `-k` expressions.

Select tests for modified symbols plus direct consumers. Add persistence, worker, API, or frontend checks only when their contracts are affected.

For application-engine work, cover the relevant subset of adapters, answer resolution, journey, planning, executor, surfaces/controls, uploads, postconditions, artifacts, API states, and audit metrics.

For ranking/materials/evals, run targeted tests and the trust gate when relevant.

### Frontend

Run these at final validation only when frontend code or shared contracts changed:

```powershell
npm run typecheck
npm run lint
npm run build
```

Do not run frontend checks for Python-only changes without shared contract impact.

Do not run `npm run verify` mechanically; it also runs build and the trust gate. Use it only when the task spans those surfaces or explicitly requires the full repository gate.

Trust gate:

```powershell
npm run trust:gate
```

Run it only for ranking, prompts, materials, evals, or trust-contract changes.

### Browser and external systems

- Prefer offline fixtures and temporary SQLite databases.
- Do not run live LLM, Turso, Vercel, LinkedIn, or real-portal smokes unless explicitly required and authorized.
- Keep browser contexts isolated and avoid arbitrary sleeps.
- Do not assume browser or shared-database tests are parallel-safe.

`pytest-xdist` is not currently guaranteed. Do not use `-n` or add test infrastructure as part of unrelated work. If parallel execution is explicitly introduced and proven stable, start conservatively with four workers and keep unsafe groups serial.

Profile test speed only when performance is the task:

```powershell
python -m pytest --durations=40 --durations-min=0.5
```

## Validation matrix

| Change | Before commit | Final |
|---|---|---|
| Local Python | modified module + consumers | full pytest |
| Application engine | relevant application subsystem | full pytest |
| Storage/schema | storage + API/worker consumers | full pytest |
| Ranking/materials/evals | targeted suite + trust gate | full pytest + trust gate |
| Frontend | affected type/lint checks | typecheck + lint + build |
| Shared API contract | backend consumers + typecheck | full pytest + frontend checks |
| Docs only | focused review/link checks | no full suite unless generated behavior depends on docs |

## Git discipline

- Do not implement directly on `main` unless explicitly requested.
- Use an isolated branch for substantial work.
- Never discard or overwrite user changes.
- Do not push, open a PR, merge, rebase shared branches, or force-update refs unless requested.
- Keep commits logical, reviewable, and independently testable.

Before each commit:

1. Inspect `git diff --stat` and the relevant full diff.
2. Run targeted validation.
3. Run `git diff --check`.
4. Confirm no unrelated files.

Before completion:

1. Run validation appropriate to impact.
2. Inspect the branch diff against its base.
3. Confirm `git status --short`.
4. Report skipped checks and why.

## Data safety

Never commit `.env`, secrets, tokens, cookies, local databases, generated exports, browser profiles, caches, logs, or personal application data.

Treat `job_tracker.db`, Turso, Vercel, external APIs, and live portals as real systems. External and production checks are read-only by default. Do not seed, mutate, submit, delete, or bulk-process production data without explicit authorization.

## Done and stop rules

A task is done only when requested behavior and acceptance criteria are met, relevant tests pass, safety remains intact, compatibility impact is handled, and no unrelated changes remain. Passing tests alone is not product-level proof; use fixtures, artifacts, postconditions, and outcome evidence appropriate to the task.

Stop instead of improvising when:

- conflicting user changes exist;
- a destructive migration is required;
- real external actions are needed but not authorized;
- credentials or production access are missing;
- scope must expand materially;
- baseline failures cannot be separated from regressions;
- safety conflicts with the requested implementation;
- completion would require claiming evidence not obtained.

When stopped, preserve valid work, explain the blocker, and recommend one smallest next action.
