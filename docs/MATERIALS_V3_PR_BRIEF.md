# PR Brief: Materials v3 ATS Trust

Branch: `codex/chat-isolated-work`
Base: `origin/main`
Local state at brief time: current branch HEAD after rebase, `0 behind / 26 ahead` relative to `origin/main`.

## Summary

This branch hardens LLM-generated application materials and ATS CVs. It focuses on preventing false-positive "good" materials when the model overcompresses the CV, invents unsupported claims, misattributes technologies to employers, omits source experience, or claims ATS keyword coverage that is not present in the actual CV text.

## Main Changes

- Adds raw materials/ATS CV eval fixtures for four real reviewed cases.
- Routes ranking/material constraints through eval runners.
- Adds stricter materials validation for:
  - avoid-overclaiming claim families and aliases,
  - employer-specific technology attribution,
  - cautious tone for risky/skip-style rankings,
  - complete multi-line ATS CV structure,
  - overcompressed CVs relative to base CV experience,
  - unparseable base-CV experience density,
  - omitted single-role CV experience,
  - unsupported years-of-experience claims,
  - `keywords_used` entries not present verbatim in `ats_cv_text`.
- Updates NVIDIA materials prompts through CV `v14` and kit `v13`.
- Adds source-aware ATS line thresholds so short one-role source CVs can pass with 16-17 well-structured lines, while normal multi-role CVs still require 18+ parseable lines.
- Adds PDF/DOCX export polish plus local text and visual render verification notes.

## Evidence

Local checks after rebasing on `origin/main`:

```text
python -m pytest -qq --tb=short
npm run lint
npm run typecheck
npm run build
```

All passed locally.

Live/local probe evidence is summarized in:

- `docs/MATERIALS_V3_CHECKPOINT.md`
- `docs/MATERIALS_V3_QUALITATIVE_REVIEW.md`

Key final live follow-up:

- `synthetic_short_source_role_keywords_presence`
- CV completed in 2 attempts.
- Kit completed in 1 attempt.
- Materials semantic score: 100.
- ATS CV semantic score: 100.
- First CV attempt was correctly rejected because `keywords_used` declared `operations workflows` before the exact phrase appeared in `ats_cv_text`.

## Review Focus

- Confirm the guardrails are general enough and not overfit to individual probe cases.
- Confirm `keywords_used` verbatim presence is the desired ATS strictness.
- Confirm source-aware ATS line thresholds are acceptable.
- Review prompt wording in `prompts/materials/nvidia_cv_contract/v14.md` and `prompts/materials/nvidia_kit_contract/v13.md`.
- Review whether docs should distinguish ATS-first exports from styled resume exports in product UI later.

## Known Limits

- Raw live artifacts and rendered PNGs are intentionally local-only because they may include candidate/contact data.
- GitHub CLI was not authenticated in the local environment; remote GitHub actions were performed through the authenticated GitHub connector when available.
