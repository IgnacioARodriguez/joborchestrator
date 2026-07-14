# Application Automation

Automation is safe-by-default.

- Default mode: `review_before_submit`.
- `dry_run` defaults to true for form filling.
- Auto-submit is disabled unless `ENABLE_AUTO_SUBMIT_APPROVED=1`.
- Unknown or sensitive fields stop the session in `needs_user_input`.

Adapters:

- `GenericAssistedAdapter`: works for unsupported providers by preparing copyable answers and a review payload.
- `GreenhouseAdapter`: detects Greenhouse HTML, extracts labels/fields, maps safe answers, simulates fill in dry-run and creates a review summary.

External apply flow:

1. LinkedIn scan stores `external_apply_url` / `apply_url`.
2. `Prepare application` creates an `application_sessions` row.
3. If no HTML is provided, the v0/API queues `application_execution` in Turso.
4. The local worker opens the external URL with Playwright, captures HTML, detects the adapter and updates the session in Turso.
5. The session ends at `ready_for_review` or `needs_user_input`; never submitted automatically.

When a session stops at `needs_user_input`, the UI can queue `Continue after manual step`.
For login or account pages, use `APPLICATION_BROWSER_HEADLESS=0` plus
`APPLICATION_BROWSER_PROFILE_DIR` so the local worker can reuse the browser
session after you resolve the manual step.

Site account tracking:

- The worker records domains as `unknown`, `needs_login`, `ready`, `failed`, or `blocked`.
- Usernames/status live in the app DB.
- Passwords are stored in the OS keyring when available.
- Set `ALLOW_PLAINTEXT_CREDENTIAL_STORE=1` only for a personal local setup where plaintext storage is acceptable.

Persistent sessions live in `application_sessions` and can be resumed via:

```bash
GET /api/application-sessions?job_id=123
GET /api/application-sessions/{session_id}
POST /api/application-sessions/{session_id}/transition
```

Create a Greenhouse dry-run session:

```bash
POST /api/jobs/{job_id}/application-sessions
{
  "provider": "greenhouse",
  "mode": "review_before_submit",
  "html": "<form id=\"application_form\">...</form>",
  "dry_run": true
}
```
