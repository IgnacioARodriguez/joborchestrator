# Automation Safety

Rules enforced by design:

- No real application is submitted during tests.
- Generic form, Greenhouse and Lever automation tests use local fixtures only.
- Sensitive fields are never invented or silently persisted.
- Salary, work authorization, sponsorship, availability, address, disability, gender, ethnicity, background checks, years of experience and certifications require confirmation.
- CAPTCHA bypass and anti-bot evasion are out of scope.
- Auto-submit is reserved for the user. `auto_submit_approved` sessions are blocked with `final_submit_reserved_for_user` even when all other preconditions pass.
- Generic form and Lever can fill safe fields, upload a resume PDF and detect final submit controls in `review_before_submit`, but real auto-submit remains blocked until provider-specific live coverage is strong enough.
- Automation capabilities are declared per provider and exposed by API/UI.
- Submit-like controls such as `Submit application`, `Send application`, `Finish`, `Submit`, and `Enviar candidatura` are classified as forbidden browser actions.
- In `auto_submit_approved` mode, classified submit controls are detected for the user-owned final boundary but are not clicked by automation.
- Local browser handoff stores only opaque `local-browser://session/<uuid>` references in application sessions.
- `submitted_manually` is the explicit human-confirmed state for a real submission performed outside automation.
- `submitted` records an application submitted by the env-gated automation path.
- `submission_verified` is reserved for a later confirmation step.

Logs and screenshots should avoid PII unless an explicit debug mode is added.
