# GitHub Actions job automation

The automation is split into three independent workflows because the workloads have different runtime and credential requirements.

## 1. Job discovery (ATS + public search)

File: `.github/workflows/job-discovery.yml`

- Runs on `ubuntu-latest` every six hours and on manual dispatch.
- Queues and claims only a `job_scan` operation.
- Reads enabled ATS company sources from Turso.
- Builds public-search queries from `target_roles` and `secondary_roles` in the candidate profile.
- Uses all public providers that are configured.
- Queues new or updated jobs for NVIDIA ranking but does not execute ranking inside the scan workflow.

Required repository secrets:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

Optional provider secrets:

- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `INFOJOBS_CLIENT_ID`
- `INFOJOBS_CLIENT_SECRET`

## 2. LinkedIn scraping

File: `.github/workflows/linkedin-scraping.yml`

LinkedIn is intentionally not run on a GitHub-hosted runner. The scraper uses a persistent Playwright browser profile, a manual login, and may require visible user intervention for checkpoints or verification. An ephemeral hosted runner would lose the session and repeatedly present a new IP/device to LinkedIn.

Configure a Windows self-hosted runner with the custom label `linkedin`:

1. In the repository, open **Settings → Actions → Runners → New self-hosted runner**.
2. Install it on the Windows machine that owns the LinkedIn browser profile.
3. Add the label `linkedin`.
4. Run the runner interactively rather than as a Windows service so Playwright can open a visible browser.
5. Keep `linkedin_user_profile_*` and `salidas_todas_posiciones_raw` in the runner workspace. The workflow uses `actions/checkout` with `clean: false` so those ignored directories survive subsequent runs.
6. Start the workflow manually once and complete the LinkedIn login in the opened browser. Later runs reuse that local profile.

Required repository secrets:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

The workflow is manual-only by default. Scheduling it without supervising account checkpoints is not recommended. It does not bypass login challenges, CAPTCHA, or LinkedIn verification.

## 3. NVIDIA rankings

File: `.github/workflows/rankings.yml`

- Runs after either discovery workflow completes successfully.
- Also runs hourly as recovery for interrupted or delayed ranking queues.
- Can be dispatched manually.
- Reuses an existing queued/running ranking job when present.
- Otherwise queues currently unranked jobs.
- Drains ranking work by chunks until the queue is empty or the configured safety limit is reached.

Required repository secrets:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `NVIDIA_API_KEY`

## Shared database requirement

GitHub-hosted jobs are ephemeral. `TURSO_DATABASE_URL` must be configured; otherwise each workflow would create an isolated SQLite database that disappears when the runner is destroyed and would not update the deployed dashboard.

## Operational notes

- Workflow concurrency groups prevent two instances of the same lane from running simultaneously.
- Scan workflows only queue ranking; the ranking workflow owns ranking execution.
- Logs are uploaded as seven-day workflow artifacts.
- GitHub cron expressions use UTC and may start later than the exact requested minute during platform congestion.
