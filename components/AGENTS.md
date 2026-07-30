# Active frontend instructions

Applies to this active Next.js subtree.

## Scope

- The active dashboard uses the root Next.js application.
- Do not edit `dashboard/`; it is legacy.
- Preserve existing UI patterns and shared components.
- Avoid unrelated redesign, copy changes, formatting, or dependency upgrades.
- Reuse existing types, hooks, API clients, and components before creating new ones.

## Contracts

- Trace shared API types and serialization only when affected.
- Do not silently compensate in the UI for an incorrect backend contract.
- Preserve loading, empty, error, and partial-data states.
- Keep server-only logic out of client components where possible.

## Validation

During implementation, run only affected checks.

At completion, when frontend code changed:

```powershell
npm run typecheck
npm run lint
```

Run one build when routing, bundling, server/client boundaries, environment usage, or shared contracts changed:

```powershell
npm run build
```

Do not run `npm run verify` mechanically. Do not run backend suites for a purely visual local change unless a shared contract is involved.
