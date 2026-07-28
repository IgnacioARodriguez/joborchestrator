# Remaining Gaps

- Greenhouse browser automation is still partial: text, select, radio, checkbox, generated PDF resume upload, submit-button detection and in-memory local browser handoff work against local Playwright fixtures, but handoff cleanup/UX can still be deepened.
- Lever, Ashby and Workday are recognized in the capabilities matrix but still need provider-specific autofill adapters.
- LinkedIn Easy Apply remains explicitly non-automated.
- CV anti-invention validation should be expanded from existing material generation into a structured persisted diff.
- Review screen can be deepened to edit unknown answers inline.
- Worker execution types exist broadly, but application execution should get a dedicated local browser worker before real sites are used.
- Browser sessions can now use an opaque `local-browser://session/<uuid>` ref in the local worker, but there is not yet a full browser-session management screen.
- Visual browser verification was not run in this edit pass; CLI checks cover build/type/lint/tests.
