# Automation Safety

Rules enforced by design:

- No real application is submitted during tests.
- Greenhouse automation tests use local fixtures only.
- Sensitive fields are never invented or silently persisted.
- Salary, work authorization, sponsorship, availability, address, disability, gender, ethnicity, background checks, years of experience and certifications require confirmation.
- CAPTCHA bypass and anti-bot evasion are out of scope.
- Auto-submit is disabled by default.
- Submitted state should only be reached after a verification step or an explicit human-confirmed transition.

Logs and screenshots should avoid PII unless an explicit debug mode is added.
