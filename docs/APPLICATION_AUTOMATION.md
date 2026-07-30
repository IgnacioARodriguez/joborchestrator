# Application Automation

Automation is safe-by-default.

- Default mode: `review_before_submit`.
- `dry_run` defaults to true for form filling.
- Final submit is reserved for the user; automation does not click final submit controls.
- Unknown or sensitive fields stop the session in `needs_user_input`.
- Provider support is exposed through `GET /api/automation/provider-capabilities`.
- The UI shows provider capabilities separately from provider detection.
- Real submissions are recorded through `submitted_manually` or later `submission_verified`.

Adapters:

- `GenericAssistedAdapter`: works for unsupported providers by preparing copyable answers and a review payload.
- `GenericFormAdapter`: detects ordinary HTML forms, extracts labels/fields from the Playwright DOM, maps safe answers, fills safe compatible fields, uploads a generated resume PDF and creates a review summary.
- `GreenhouseAdapter`: detects Greenhouse pages and reuses the generic browser form engine with Greenhouse-specific form recognition.
- `LeverAdapter`: detects Lever pages, opens the apply form when needed and reuses the generic browser form engine.

Current provider capability matrix:

| Provider | Open | Redirects | Detect fields | Fill text | Selects | Radios | Checkboxes | Resume upload | Browser resume | Auto-submit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Greenhouse | yes | yes | yes | yes | yes | yes | yes | yes | yes | blocked |
| Lever | yes | yes | yes | yes | yes | yes | yes | yes | yes | no |
| Generic forms | yes | yes | yes | yes | yes | yes | yes | yes | yes | no |
| Generic assisted | yes | yes | no | no | no | no | no | no | no | no |
| Ashby | yes | yes | no | no | no | no | no | no | no | no |
| Workday | yes | yes | no | no | no | no | no | no | no | no |
| LinkedIn Easy Apply | yes | no | no | no | no | no | no | no | no | no |

External apply flow:

1. LinkedIn scan stores `external_apply_url` / `apply_url`.
2. `Prepare application` creates an `application_sessions` row.
3. If no HTML is provided, the v0/API queues `application_execution` in Turso.
4. The local worker opens the external URL with Playwright, captures HTML, detects the adapter and updates the session in Turso.
5. Generic browser form execution uses Playwright DOM inspection for fields and can fill safe text/select/radio/checkbox controls when the answer is confirmed and non-sensitive.
6. Generic form, Greenhouse and Lever can export the generated ATS CV as a temporary local PDF and upload it to a local/browser file input with `set_input_files`.
7. Final submit-like controls are classified as `forbidden` by default and recorded in session artifacts.
8. If `APPLICATION_BROWSER_HANDOFF=1`, the worker keeps the local Chromium page alive and stores only an opaque `local-browser://session/<uuid>` reference.
9. Sensitive or unknown fields remain unfilled and are reported for review.
10. By default, the session ends at `submit_only` or `needs_user_input`.
    `submit_only` means all registered required obligations were resolved,
    policy-authorized, executed and verified, and the only remaining action is
    the user-owned final submit boundary.
11. After the user submits manually on the company site, they can record `submitted_manually`.
12. A later confirmation can move the session to `submission_verified`.

Final submit boundary:

- `auto_submit_approved` is retained as a compatibility mode, but it is blocked
  with `final_submit_reserved_for_user`.
- The worker can detect exactly one final submit control and include it in
  artifacts as the submit boundary.
- Real submissions are recorded only after the user submits manually and marks
  the session `submitted_manually`.

Obligation ledger:

- Browser execution writes `artifacts_json.obligation_ledger`.
- Each ledger entry records logical control identity, owning surface, required
  evidence, semantic category, resolved answer source, policy decision, planned
  action, execution result, validation result, blocker and reason codes.
- `artifacts_json.obligation_ledger.readiness.terminal_state` is `SUBMIT_ONLY`
  only when the ledger has no fail-closed blockers.

Answer bank:

- Answers have explicit `status`: `proposed`, `approved`, `rejected`, `expired`, or `requires_confirmation`.
- `generated` answers default to `proposed` and are never used for autofill until approved by the user.
- Deterministic matching runs before any semantic/AI path: canonical key, normalized exact question pattern, then `re:` regex patterns.
- Normalization lowercases, removes accents, removes non-significant punctuation, and collapses whitespace.
- Sensitive, expired, rejected, proposed, or confirmation-required answers are not autofilled.

When a session stops at `needs_user_input`, the UI can queue `Continue after manual step`.
For login or account pages, use `APPLICATION_BROWSER_HEADLESS=0` plus
`APPLICATION_BROWSER_PROFILE_DIR` so the local worker can reuse the browser
session after you resolve the manual step.

Local browser handoff:

```bash
APPLICATION_BROWSER_HANDOFF=1
APPLICATION_BROWSER_HEADLESS=0
APPLICATION_BROWSER_HANDOFF_TIMEOUT_SECONDS=3600
APPLICATION_BROWSER_PROFILE_DIR=data/application_browser_profile
```

The database stores only `browser_session_ref` values such as
`local-browser://session/<uuid>`. Cookies, tokens, passwords, browser storage,
and complete HTML stay in the local browser process/profile and are not stored
in Turso/SQLite session artifacts.

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
POST /api/application-sessions/{session_id}/submitted-manually
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
