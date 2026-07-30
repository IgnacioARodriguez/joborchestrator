# AGENTS.md — Job Orchestrator

## Mission

Make the smallest safe, reviewable change that satisfies the task.

Priorities:

1. Correctness.
2. Minimal scope.
3. Targeted verification.
4. Low unnecessary token and tool use.
5. Honest evidence.

Task instructions override this file. The nearest nested `AGENTS.md` overrides broader rules in its scope. Do not restate instructions or narrate routine work.

## Repository map

- `app/`, `components/`, `lib/`: active Next.js dashboard.
- `dashboard/`: legacy duplicate; edit only when explicitly requested.
- `joborchestrator/api.py`: FastAPI API.
- `joborchestrator/worker.py`: local long-running worker.
- `joborchestrator/automation/`: browser application engine.
- `joborchestrator/scanning/`: imports, ATS providers, search APIs.
- `joborchestrator/ranking/`: ranking models, prompts, worker.
- `joborchestrator/intelligence/`: application materials and signals.
- `joborchestrator/storage/`: SQLite/Turso persistence.
- `tests/`: Python tests.
- `scripts/`: smoke, audit, eval, seed, maintenance.
- `docs/`: architecture, safety, trust, evidence.

The root Next.js app is active. Long-running AI and browser work belongs in local workers, not Vercel serverless handlers.

## Source order

When information conflicts:

1. Current task and acceptance criteria.
2. Nearest applicable `AGENTS.md`.
3. Current code, schemas, tests, and fixtures.
4. This file.
5. Documentation and historical reports.

Old plans and docs are not proof of current behavior.

## Complexity boundary

Use a low-complexity workflow only when the task is explicit, localized, mechanically implementable, and has obvious exact validation.

Treat the task as medium-complexity when any of these apply:

- Unknown root cause.
- Multiple subsystems or contracts.
- Ambiguous behavior or conflicting evidence.
- New abstraction or compatibility decision.
- Browser automation, storage, schemas, workers, ranking, materials, trust, security, concurrency, migrations, or external systems.

This classification controls exploration and validation only; it does not change the configured model or reasoning effort.

If a low-complexity task reveals medium scope, stop broad implementation, preserve valid work, report the evidence, and recommend one smallest continuation step. Do not silently expand scope.

## Default workflow

Before editing:

1. Run `git status --short --branch`.
2. Identify the branch and relevant existing diff.
3. Check for a nearer `AGENTS.md`.
4. Locate exact symbols with `rg`.
5. Read only relevant ranges.
6. Trace direct callers, consumers, tests, serialization, API, worker, storage, and UI only when affected.
7. Separate baseline failures from regressions.

During implementation:

1. Reuse existing abstractions.
2. Prefer additive, non-destructive changes.
3. Preserve public contracts unless breaking changes are explicitly allowed.
4. Make one coherent change at a time.
5. Run the smallest test that can falsify the change.
6. Expand exploration only when evidence requires it.

Before completion:

1. Inspect `git diff --stat` and the relevant full diff.
2. Run `git diff --check`.
3. Run validation appropriate to actual impact.
4. Confirm `git status --short`.
5. Report skipped checks and why.

## Scope and efficiency

Do not:

- Scan the whole repository by default.
- Open large files before searching for symbols.
- Reopen unchanged files without a new reason.
- Perform unrelated cleanup, renames, formatting, dependency upgrades, or rewrites.
- Modify generated or legacy files unless required.
- Add dependencies for convenience.
- Introduce an abstraction when a local change is enough.
- Change tests merely to make incorrect behavior pass.
- Print large JSON, databases, lockfiles, environment dumps, generated files, or long logs.
- Create subagents or parallel investigations unless duplication is controlled and clearly useful.
- Claim behavior, validation, or completion not directly observed.

Search before reading. Prefer exact ranges, focused diffs, concise output, and targeted tests. Reuse verified findings. Stop exploration once the acceptance criteria can be safely implemented and verified.

Ask only questions that materially affect architecture, safety, scope, or irreversible actions.

## Application automation safety

Default to review-before-submit.

Unless explicitly authorized for a controlled test, never:

- Submit a real application or broaden auto-submit.
- Accept legal consent, terms, privacy acknowledgements, declarations, certifications, signatures, or background-check authorization.
- Solve CAPTCHA, MFA, login challenges, password recovery, or email verification.
- Create irreversible accounts or withdraw applications.
- Expose secrets, cookies, tokens, production records, or personal data.

Prefer fixtures, snapshots, temporary databases, and `data:` pages over real portals.

Work authorization and sponsorship are not generic legal consent. Fill them only from exact, current, approved answers under policy.

Fail closed on unknown required controls, ambiguous mappings, unverified uploads, pending validation, unsupported controls, and uncertain postconditions.

## External systems and data safety

Treat Turso, Vercel, LinkedIn, external APIs, live portals, and production databases as real systems.

By default:

- External checks are read-only.
- Do not seed, mutate, submit, delete, deploy, or bulk-process production data.
- Do not run live LLM, browser, Turso, Vercel, LinkedIn, or portal smokes unless explicitly required and authorized.
- Use temporary SQLite databases and offline fixtures.
- Keep browser contexts isolated.
- Avoid arbitrary sleeps.
- Do not assume browser or shared-database tests are parallel-safe.

Never commit `.env` files, secrets, tokens, cookies, local databases, browser profiles, logs, caches, generated exports, or personal application data.

## Validation routing

Use the smallest validation that can reasonably falsify the change.

| Impact | During implementation | At completion |
|---|---|---|
| Docs only | Focused diff review | No suite unless behavior is generated from docs |
| Localized Python | Exact affected tests | Exact tests plus direct consumers |
| Cross-cutting backend | Relevant subsystem tests | One full `pytest` run |
| Ranking/materials/prompts/evals/trust | Exact affected tests | `npm run trust:gate`; full `pytest` only if backend/shared contracts changed |
| Frontend | Affected type/lint checks | Typecheck, lint, and one build |
| Shared API contract | Backend consumers + frontend typecheck | Full backend suite + frontend checks |

Do not run full `pytest` solely because a Python file changed. Do not repeat a passing full suite unless later changes could invalidate it. Do not run frontend checks for Python-only changes without shared contract impact. Do not run `npm run verify` mechanically.

### Commands

Targeted backend:

```powershell
python -m pytest <test-files-or-node-ids> -q --maxfail=1
```

Full backend:

```powershell
python -m pytest
```

Repeat failures:

```powershell
python -m pytest --lf -x
```

Temporary test discovery:

```powershell
python -m pytest -q --maxfail=1 -k "<expression>"
```

Stop using broad `-k` once exact tests are known.

Frontend:

```powershell
npm run typecheck
npm run lint
npm run build
```

Trust gate:

```powershell
npm run trust:gate
```

Do not use `pytest-xdist` unless parallel safety has been explicitly introduced and proven.

Select tests for modified behavior, direct consumers, changed contracts, and regression coverage. Broaden only when evidence shows wider impact.

## Git discipline

- Do not perform substantial work directly on `main` unless explicitly requested.
- Use an isolated branch for substantial work.
- Never discard, overwrite, reset, or rewrite user changes.
- Do not push, open a PR, merge, rebase shared branches, or force-update refs unless requested.
- Do not create commits unless requested or clearly required.
- Keep commits logical, reviewable, and independently testable.

Before each requested commit:

1. Inspect `git diff --stat` and the relevant diff.
2. Run targeted validation.
3. Run `git diff --check`.
4. Confirm no unrelated files are included.

## Communication

Send progress updates only for a meaningful finding, blocker, scope change, validation result, or irreversible decision requiring authorization.

Final reports must contain:

- Changed behavior.
- Relevant files or commits.
- Validation run and results.
- Skipped checks and why.
- Remaining real risks.
- One smallest next action only when needed.

Do not repeat the prompt, paste large code excerpts, or present planned work as completed.

## Done and stop rules

A task is done only when acceptance criteria are met, relevant validation passes, safety remains intact, compatibility impact is handled, no unrelated changes remain, and evidence supports every completion claim.

Passing tests alone is not product-level proof. Use fixtures, artifacts, postconditions, and observable outcomes appropriate to the task.

Stop instead of improvising when:

- Conflicting user changes exist.
- A destructive migration is required.
- Unauthorized real-world actions are needed.
- Credentials or production access are missing.
- Scope must expand materially.
- Baseline failures cannot be separated from regressions.
- Safety conflicts with the requested implementation.
- Completion would require claiming evidence not obtained.

When stopped, preserve valid work, explain the blocker precisely, and recommend one smallest next action.
