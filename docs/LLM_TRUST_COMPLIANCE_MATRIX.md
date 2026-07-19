# LLM Trust Compliance Matrix

Last assessed: 2026-07-19

This matrix tracks HuntPilot against the trust bar defined in `docs/LLM_TRUST_DEFINITION_OF_DONE.md`.

Status values:

- Green: meets the DoD.
- Yellow: partially meets the DoD; usable with review.
- Red: does not meet the DoD yet.

## Executive Summary

Current trust posture: Yellow-Red, approximately 6.6/10.

HuntPilot is currently suitable as an operational copilot for job discovery, ranking review, and draft generation. It is not suitable for near-blind trust yet: the fresh post-reranking ranking baseline failed the reviewed golden threshold, materials/ATS CV still need measured quality work, and review-state thresholds need calibration against the failed cases.

## Current Evidence Snapshot

- Active ranking prompt: `ranking/nvidia_response_contract` v2.
- Active materials CV prompt: `materials/nvidia_cv_contract` v2.
- Active materials kit prompt: `materials/nvidia_kit_contract` v2.
- Active judge prompt: `judge/semantic_rubric` v1.
- Production jobs in Turso: 419.
- Production rankings in Turso: 293 before re-ranking job `#8`; 419 saved by completed reranking job `#8`.
- Latest completed recovery ranking job: `#6`, 30/30 saved, 0 failed.
- Latest completed re-ranking job: `#8`, 419 queued, 419 processed, 419 saved, 0 failed.
- Local offline trust gate: `npm run trust:gate` passed on 2026-07-19; `npm run verify` now runs typecheck, lint, build, and the trust gate.
- Latest Vercel backend smoke: passed against Turso on 2026-07-19; warning only for 27 recent historical scan errors, while latest scan completed with 0 errors. Error sample points to `themuse`/`remotive` API timeouts from 2026-07-15.
- Latest Vercel UI smoke: passed on 2026-07-19; dashboard rendered 419 visible jobs across Today/Review/Applications/Profile/Automations/Insights with no console errors or failed requests.
- Fresh stored eval evidence after reranking job `#8`:
  - Ranking: 22 persisted real reviewed cases evaluated, 5 passed, 17 failed, 22.7% pass rate, 11 critical failures, average score 77.5.
  - Application materials: 3 cases, 0 passed, 0.0% pass rate, average score 65.0.
- Post-baseline ranking safety follow-up: deterministic caps now cover low-context magic-word postings, contract AI training/verification work, autonomous-driving simulation specialization, hybrid 6+ seniority review, unclear India remote eligibility, Brazil location restrictions, industrial automation/manufacturing mismatch, Munich/German signals, Madrid freelance review, senior infrastructure review, and Solutions Architect false security-gap avoidance. Unit/full pytest suites passed. In-memory replay over the persisted post-rerank outputs estimates 16/22 passing, 72.7% pass rate, and 4 critical failures, but these fixes still need a fresh reranking/baseline measurement.
- Reviewed golden fixtures: 34 cases under `evals/fixtures/golden` (12 synthetic seed cases plus 22 human-reviewed real ranking cases).
- Known recurring eval issues:
  - `missing_evidence_terms`
  - `missing_dealbreaker_evidence`
  - `decision_outside_expected_band`
  - `score_above_expected`
  - `missing_required_terms`
  - `missing_required_keywords`
  - `recruiter_message_too_long`
  - `recruiter_message_cover_letter_style`
  - `ats_cv_contains_internal_notes`
  - unsupported ATS CV overclaims from ranking avoid-overclaiming terms

## DoD Compliance Table

| Area | DoD Target | Current Status | Evidence | Gap |
| --- | --- | --- | --- | --- |
| Prompt registry | Active prompt versions are explicit and shared | Green | Registry points ranking/materials to v2 and judge to v1 | None immediate |
| Ranking schema | Output validates against structured contract | Green-Yellow | Reranking job `#8` saved 419/419 records with 0 failed; schema was aligned with prompt contract | NVIDIA may still need retry after malformed first response |
| Ranking quality | >= 90% pass rate, 0 critical failures | Red | Fresh persisted ranking baseline after job `#8`: 5/22 passed, 22.7% pass rate, 11 critical failures; deterministic safety replay estimates 16/22 passed, 72.7% pass rate, 4 critical failures | Must rerank/rebaseline and continue fixing remaining decision banding issues before trusting rankings |
| Materials quality | >= 90% pass rate, 0 critical failures | Red | Stored evals show 0/3 passing | Need fresh v2 baseline and prompt fixes for length/specificity |
| ATS CV quality | >= 95% pass rate, 0 critical failures | Red-Yellow | Internal-note validation exists, complete-CV validation preserves base experience, and ranking avoid-overclaiming terms are blocked when unsupported by source CV/profile | Need current ATS CV baseline and more reviewed ATS CV cases |
| Golden set | 30-50 reviewed cases | Green-Yellow | 34 reviewed fixtures exist across ranking/materials/ATS CV, including 22 human-reviewed real ranking cases; local trust gate requires at least 3 cases per surface | Need more real materials/ATS CV cases to balance beyond synthetic coverage |
| Critical failure gate | Critical failures block promotion | Green-Yellow | Eval loop has hard-stop and regression checks; local trust gate verifies deterministic guardrails reject known-bad ranking/materials/ATS CV outputs | Need larger coverage and explicit critical taxonomy in reports |
| Case regressions | 0 regressions on promotion | Green-Yellow | `compare_summaries` regressions are wired into promotion gate | Needs fresh runs to prove effectiveness at scale |
| Judge rubric | Versioned judge prompt and issue codes | Green-Yellow | Judge rubric v1, issue code normalization, multi-model support | Need stronger calibration against human review |
| Multi-model judge | Disputed/high-risk evals can use two models | Yellow | NVIDIA secondary model support exists | Not yet used as routine gate |
| Production ranking | Rankings persist model, version, score, evidence | Green-Yellow | `job_rankings` stores version, decision, confidence, scores/evidence JSON, and reranking job `#8` populated provider, model, prompt version, validation attempts/errors, and candidate profile snapshot hash for 419 rows; API/UI expose ranking review status | Review thresholds need calibration against failed golden cases |
| Production confidence gates | Uncertain outputs become review-required drafts | Yellow | Ranking safety gates set `requires_llm_review`; ranking API/UI marks low confidence, validation retry, thin positive evidence, and missing central requirements for review; deterministic caps were added for three unsafe post-baseline patterns | Need fresh reranking proof and additional caps or prompt fixes for remaining explicit dealbreakers and adjacent-role mismatches |
| Observability | Outputs trace prompt/model/evidence/status | Green | Ranking rows now support provider, model, prompt version, validation attempts/errors, and candidate profile snapshot hash for new NVIDIA rankings; ranking review status is exposed in API/UI; materials persist provider, model, prompt versions, generated timestamp, validation attempts/errors, and candidate profile snapshot hash; eval rows preserve payloads/results; LLM output feedback is stored and summarized by job/artifact/action | Need to use captured traces to debug failed ranking cases |
| Production health | App/API/DB smokes are green | Green | Vercel backend and UI smokes passed against Turso on 2026-07-19; local trust gate runs offline e2e, scan, guardrail, and golden-fixture coverage checks; smoke now summarizes recent scan error samples; HTTP providers retry transient timeout/network/5xx/429 failures once by default | Historical `themuse`/`remotive` timeout rate should be monitored after deploy |

## Current Trust Score By Surface

| Surface | Score | Rationale |
| --- | ---: | --- |
| Ranking | 5.8 | Productive flow works and 419/419 rerank rows were saved with traceability. The official fresh reviewed golden baseline is still 5/22 with 11 critical failures, but deterministic safety replay now estimates 16/22 with 4 critical failures. Treat rankings as review inputs, not trusted decisions, until a fresh rerank confirms this. |
| Application materials | 6.1 | Prompt v2 exists, recruiter specificity/length gates improved, materials review status is exposed, and generation/retry/profile trace metadata is persisted; stored eval evidence still needs a fresh pass. |
| ATS CV | 6.0 | Internal notes, incomplete CVs, omitted base experiences, and unsupported ranking avoid-overclaiming terms now have deterministic gates; needs fresh v2 proof. |
| Judge/evals | 7.5 | Strong framework, offline trust gate, feedback records, saved fresh ranking eval runs, and summary analytics are available for calibration; dataset is still small outside ranking and judge calibration remains limited. |
| Production operations | 7.8 | Vercel/Turso/smokes are healthy; `npm run verify` is repeatable, materials/ranking outputs are traceable for new writes, retry/profile metadata is stored, ranking/material review status is visible, and user feedback can be captured/summarized; remaining risk is quality gating rather than uptime. |

Overall: 6.6/10.

## Immediate Blockers To High Trust

1. Ranking v2 failed the fresh persisted real reviewed baseline: 5/22 passed, 17 failed, 11 critical failures.
2. Materials and ATS CV still need fresh proof against known historical quality failures.
3. Golden coverage is above the minimum count, but real materials/ATS CV coverage is still thin.
4. Ranking failures still cluster around cases where the persisted LLM decision is too low for an adjacent opportunity, plus one strong-fit under-score; deterministic safety gates do not promote low decisions and need fresh rerank proof.
5. Review gates need to catch or downgrade the remaining unsafe positive recommendations before ranking can be treated as high trust.

## Recommended Next Gates

### Gate 1: Freeze The Current State

Goal: make the trust target visible and auditable.

Done when:

- `LLM_TRUST_DEFINITION_OF_DONE.md` is committed.
- `LLM_TRUST_COMPLIANCE_MATRIX.md` is committed.
- Current status is recorded as baseline, not treated as passing.

### Gate 2: Build Reviewed Golden Set

Goal: create the minimum evidence base.

Candidate review packet command:

```bash
python scripts/select_llm_golden_candidates.py --target-total 40 --output logs/llm_golden_candidate_review_packet.json
```

Done when:

- At least 30 reviewed cases exist.
- Cases cover ranking decisions, dealbreakers, weak-fit jobs, strong-fit jobs, materials, and ATS CV.
- Each case has expected behavior and critical-failure markers.
- No protected fixtures are modified without explicit human approval.

Current progress:

- 12 reviewed synthetic seed cases exist in `evals/fixtures/golden/seed`.
- 22 human-reviewed real ranking cases exist in `evals/fixtures/golden/real_reviewed`.
- A 40-case real-job review packet can still be generated under `logs/` for more human review.
- Additional real materials/ATS CV cases should be reviewed before promotion into `evals/fixtures/golden`.

### Gate 3: Run Fresh v2 Baseline

Goal: measure active prompts, not stale historical outputs.

Done when:

- Ranking v2 baseline is run. Current measured result: failed, 5/22 passed, 11 critical failures. Deterministic safety replay estimates 16/22 passed and 4 critical failures; fresh reranking is still required to make that official.
- Materials v2 baseline is run.
- ATS CV v2 baseline is run.
- Results are compared to prior summaries.
- Critical failures are listed separately from ordinary misses.
- `npm run verify` passes before and after prompt changes.

### Gate 4: Fix Highest-Severity Prompt Failures

Goal: remove known recurring failures.

Priority order:

1. ATS CV internal notes.
2. Unsupported or overclaimed skills.
3. APPLY_NOW with central mismatch or dealbreaker.
4. Missing central evidence terms.
5. Recruiter message length and specificity.

### Gate 5: Add Production Review Gates

Goal: production should not silently treat risky output as ready.

Done when outputs require review if:

- confidence is low,
- central requirement coverage is weak,
- job text quality is poor,
- a retry/schema repair was needed,
- relocation/language/seniority/location is uncertain,
- `requires_llm_review` is true.

## Decision Rule

Until all high-trust gates pass, HuntPilot outputs should be treated as:

> Good draft assistance with review required, not blindly trusted decisions.

When ranking, materials, and ATS CV all pass their thresholds with zero critical failures and zero regressions, the system can move to:

> High-trust automation with review only for flagged uncertainty.
