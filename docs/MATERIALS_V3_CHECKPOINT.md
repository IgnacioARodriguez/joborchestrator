# Materials v3 Checkpoint

Date: 2026-07-29
Branch: `codex/chat-isolated-work`
Remote: `https://github.com/IgnacioARodriguez/joborchestrator.git`
Latest reviewed state: current `codex/chat-isolated-work` HEAD after rebase.
Base checked against: `origin/main` after rebase; `origin/main...HEAD` is `0 behind / 26 ahead`.

This packet is intentionally sanitized. Raw generated CVs, cover letters, PDFs, DOCX files, and probe JSONs contain candidate contact/profile data and remain local under ignored paths (`data/` and `output/`). Use this document for remote code review and qualitative checkpointing; use local artifacts only when a reviewer explicitly needs full generated material text.

## Current Verdict

Not yet a final merge recommendation by itself. The branch is in a materially better state and currently passes the automated suite, but the final decision should still include human qualitative review of representative generated materials.

What is now supported by evidence:

- The branch is remote-visible at `origin/codex/chat-isolated-work`.
- The latest code is rebased on current `origin/main`; the branch no longer shows unrelated deletions from application automation or branding assets when diffed against `origin/main`.
- Deterministic materials validation now catches overcompressed ATS CVs, unparseable experience density, omitted single-role experience, unsupported years-of-experience claims, and unsupported employer/technology attribution.
- ATS CV completeness now uses a source-aware line threshold: normal multi-role CVs still require 18+ parseable lines, while very short one-role source CVs may pass with 16-17 well-structured lines if all required sections and source-backed bullets are preserved.
- ATS CV validation now rejects `keywords_used` items that do not appear verbatim in `ats_cv_text`, preventing keyword accounting from claiming ATS coverage that the submitted CV text does not actually contain.
- The ATS semantic evaluator no longer false-fails truthful wording variants such as `documentation` vs `Documented`, singular/plural, and punctuation-preserving bullet rewrites.
- Full pytest suite, frontend lint, frontend typecheck, and frontend production build are green locally.

## Commits Above `origin/main`

After rebase onto current `origin/main`, `origin/main..HEAD` contains 25 implementation/docs commits:

```text
b80963e test(materials): capture fresh v3 raw fixtures
620413f fix(evals): prioritize central materials expectations
a2a4c80 fix(evals): pass ranking constraints through runners
8da988c docs(trust): record live materials v3 probe
f3bfe54 fix(materials): block avoid-overclaiming claim families
6cbbdfe fix(materials): expose avoid-overclaiming aliases
3d2873b fix(materials): constrain employer technology attribution
718dac1 fix(materials): calibrate risky application tone
20aa489 fix(materials): add ats fit map and cautious retries
950dc8c fix(materials): allow bounded validation probes
db6f9d4 fix(materials): preserve metadata on request timeouts
21e233b fix(materials): require complete ats cv prompt
7a14cb9 fix(materials): enforce multiline ats cv contract
ccc3c9b fix(materials): polish ats cv export and kit gaps
26edbda fix(materials): detect overcompressed ats cvs
2720cd3 fix(materials): align density checks with real cv format
2fcfb0f fix(materials): fail fast on unparseable cv density
da2d01a fix(materials): reject omitted single-role cvs
2e6579b fix(materials): align cv prompt with density gate
f62fb13 fix(materials): reject unsupported experience-year claims
3f2c820 fix(evals): tolerate truthful ATS wording variants
cd66038 docs(materials): add v3 checkpoint packet
00a764f fix(materials): align ATS keyword coverage with generated CV
9394bbf docs(materials): add qualitative review packet
1c71e70 docs(materials): record PDF render review
```

## Local Verification

Commands run from `C:\Projects\joborchestrator-chat-work`:

```text
python -m pytest tests/test_llm_semantic_evals.py -q
Result: 21 passed

python -m pytest tests/test_career_ops_features.py -q
Result: 65 passed

python -m pytest tests/test_llm_semantic_evals.py tests/test_career_ops_features.py -q
Result: 86 passed

python -m pytest -qq --tb=short
Result: full suite passed
```

Full-suite warnings observed are pre-existing FastAPI/Starlette deprecation warnings.

Latest full-suite run after adaptive-line and keyword-presence follow-up:

```text
python -m pytest -qq --tb=short
Result: full suite passed
```

Post-rebase CI-equivalent local checks:

```text
python -m pytest -qq --tb=short
Result: full suite passed

npm run lint
Result: passed

npm run typecheck
Result: passed

npm run build
Result: passed
```

GitHub CLI was available locally but not authenticated, so PR creation/check inspection could not be performed from this environment.

## Probe Artifact Map

Raw artifacts are local-only and intentionally ignored by git.

| Case | Job | Local artifact | CV status | Kit status | Attempts | Semantic result |
| --- | --- | --- | --- | --- | --- | --- |
| `pss_full_retry3` | AWS Backend / Cloud Developer at PSS Tecnologias de la Informacion | `data/materials_live_probe/20260728_140737_pss_full_retry3.json` | completed | completed | CV 4, kit 2 | materials 100, ATS 100 |
| `pss_cv_after_density_prompt_alignment` | PSS follow-up CV-only probe | `data/materials_live_probe/20260728_141345_pss_cv_after_density_prompt_alignment.json` | completed | n/a | CV 2 | deterministic validation clean |
| `acme_backend_strong` | Python Backend Engineer at Acme Systems | `data/materials_live_probe/20260729_111354_acme_backend_strong.json` | completed | completed | CV 2, kit 1 | materials 100, ATS 100 |
| `between_fullstack_adjacent` | Fullstack Developer Python & React - AI Full remote at BETWEEN Group | `data/materials_live_probe/20260729_111851_between_fullstack_adjacent.json` | completed | completed | CV 2, kit 2 | materials 100, ATS 100 |
| `hirefeed_contract_ai_cautious` | Python Developer Remote at Hire Feed | `data/materials_live_probe/20260729_112345_hirefeed_contract_ai_cautious.json` | completed | completed | CV 2, kit 3 | materials 100, ATS 100 |
| `synthetic_single_role_backend` | Python Backend Engineer at Acme Systems | `data/materials_live_probe/20260729_112749_synthetic_single_role_backend.json` | completed | completed | CV 1, kit 1 | materials 100, ATS 100 |
| `synthetic_short_unknown_heading` | Backend Developer at Acme Labs | `data/materials_live_probe/20260729_112824_synthetic_short_unknown_heading.json` | failed as expected | completed | CV 1, kit 1 | unrecoverable density parse failure, `human_review_required` |
| `synthetic_spanish_numeric_dates` | Desarrollador Backend Python at Datosur | `data/materials_live_probe/20260729_112907_synthetic_spanish_numeric_dates.json` | completed | completed | CV 1, kit 1 | old semantic flagged unsupported `4+ years`; now deterministically rejected by commit `544e335` |
| `synthetic_short_source_role` | API Integration Developer at LeanOps | `data/materials_live_probe/20260729_113102_synthetic_short_source_role.json` | completed | completed | CV 2, kit 1 | old semantic false-failed wording variants; recalculated after `36c4fee` as materials 100, ATS 100 |
| `synthetic_short_source_role_keywords_presence` | API Integration Developer at LeanOps | `data/materials_live_probe/20260729_120305_synthetic_short_source_role_keywords_presence.json` | completed | completed | CV 2, kit 1 | fresh live follow-up passed materials 100, ATS 100; first CV attempt was rejected for short text and `keywords_used` claiming `operations workflows` before the phrase appeared in `ats_cv_text` |

## Export Verification

Generated PDF/DOCX exports are local-only under `output/pdf/materials_live_probe/`.

Direct text extraction was verified for:

- `pss_full_retry3.pdf` and `.docx`
- `acme_backend_strong.pdf` and `.docx`
- `between_fullstack_adjacent.pdf` and `.docx`
- `hirefeed_contract_ai_cautious.pdf` and `.docx`

For all four exported cases, direct extraction found:

- `Professional Summary`
- `Technical Skills`
- `Professional Experience`
- `Education`

Observed page counts:

- `pss_full_retry3`: 1 PDF page
- `acme_backend_strong`: 1 PDF page
- `between_fullstack_adjacent`: 2 PDF pages
- `hirefeed_contract_ai_cautious`: 1 PDF page

Visual raster render was attempted earlier through `pdftoppm`, but the local wrapper failed with `El sistema no puede encontrar la ruta especificada.` A follow-up render using PyMuPDF succeeded for all exported PDF pages. Visual inspection found nonblank, readable pages with no visible clipping or overlap. The exports remain intentionally dense and ATS-classic rather than visually branded.

## Notes For Reviewer

Focus review on whether the final behavior is structurally acceptable, not only whether individual examples look good.

Suggested review questions:

- Are the deterministic guards general enough, or do they still encode examples too tightly?
- Is the source-aware ATS CV density threshold appropriate for both detailed multi-role CVs and very short one-role source CVs?
- Is requiring `keywords_used` to appear verbatim in `ats_cv_text` the right level of ATS strictness?
- Is failing fast on unparseable base-CV experience headings the right product behavior, or should the UI surface a guided fix?
- Is the new semantic wording matcher appropriately conservative?
- Should sanitized review packets be generated automatically by a script instead of maintained manually?

## Current Remaining Work

Likely remaining before merge:

- Recommended: qualitative human review of at least the four real-case generated materials before merging.
