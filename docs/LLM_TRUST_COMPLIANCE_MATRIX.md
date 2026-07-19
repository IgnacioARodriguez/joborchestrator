# LLM Trust Compliance Matrix

Last assessed: 2026-07-19

This matrix tracks HuntPilot against the trust bar defined in `docs/LLM_TRUST_DEFINITION_OF_DONE.md`.

Status values:

- Green: meets the DoD.
- Yellow: partially meets the DoD; usable with review.
- Red: does not meet the DoD yet.

## Executive Summary

Current trust posture: Yellow, approximately 6.5/10.

HuntPilot is currently suitable as a strong copilot for job discovery, ranking, and draft generation. It is not yet suitable for near-blind trust because the reviewed golden set is too small, v2 prompt quality has not been proven with a fresh full baseline, and production confidence gates are not strict enough.

## Current Evidence Snapshot

- Active ranking prompt: `ranking/nvidia_response_contract` v2.
- Active materials CV prompt: `materials/nvidia_cv_contract` v2.
- Active materials kit prompt: `materials/nvidia_kit_contract` v2.
- Active judge prompt: `judge/semantic_rubric` v1.
- Production jobs in Turso: 419.
- Production rankings in Turso: 293.
- Latest completed recovery ranking job: `#6`, 30/30 saved, 0 failed.
- Current paused ranking job: `#7`, 12/36 saved, 0 failed, interrupted manually.
- Stored eval evidence:
  - Ranking: 10 cases, 4 passed, 40.0% pass rate, average score 91.0.
  - Application materials: 3 cases, 0 passed, 0.0% pass rate, average score 65.0.
- Known recurring eval issues:
  - `missing_evidence_terms`
  - `missing_required_terms`
  - `missing_required_keywords`
  - `recruiter_message_too_long`
  - `recruiter_message_cover_letter_style`
  - `ats_cv_contains_internal_notes`

## DoD Compliance Table

| Area | DoD Target | Current Status | Evidence | Gap |
| --- | --- | --- | --- | --- |
| Prompt registry | Active prompt versions are explicit and shared | Green | Registry points ranking/materials to v2 and judge to v1 | None immediate |
| Ranking schema | Output validates against structured contract | Yellow-Green | Ranking worker saves valid records; schema was aligned with prompt contract | NVIDIA often needs retry after malformed first response |
| Ranking quality | >= 90% pass rate, 0 critical failures | Red | Stored evals show 4/10 passing | Need reviewed golden set and fresh v2 baseline |
| Materials quality | >= 90% pass rate, 0 critical failures | Red | Stored evals show 0/3 passing | Need fresh v2 baseline and prompt fixes for length/specificity |
| ATS CV quality | >= 95% pass rate, 0 critical failures | Red | Historical eval loop showed internal-note and missing-keyword failures | Need current ATS CV baseline and hard gate |
| Golden set | 30-50 reviewed cases | Red | Current stored eval evidence is small and mixed | Need curated reviewed cases |
| Critical failure gate | Critical failures block promotion | Yellow | Eval loop has hard-stop and regression checks | Need larger coverage and explicit critical taxonomy in reports |
| Case regressions | 0 regressions on promotion | Green-Yellow | `compare_summaries` regressions are wired into promotion gate | Needs fresh runs to prove effectiveness at scale |
| Judge rubric | Versioned judge prompt and issue codes | Green-Yellow | Judge rubric v1, issue code normalization, multi-model support | Need stronger calibration against human review |
| Multi-model judge | Disputed/high-risk evals can use two models | Yellow | NVIDIA secondary model support exists | Not yet used as routine gate |
| Production ranking | Rankings persist model, version, score, evidence | Yellow-Green | `job_rankings` stores version, decision, confidence, scores/evidence JSON | Need stronger review-state UX and retry metadata |
| Production confidence gates | Uncertain outputs become review-required drafts | Yellow | Ranking evidence has `requires_llm_review`; storage uses review viability signals | Need explicit UI/API policy for low confidence, retry, weak evidence |
| Observability | Outputs trace prompt/model/evidence/status | Yellow-Green | Ranking rows preserve version/model/evidence; eval rows preserve payloads/results | Need candidate profile snapshot/version and user feedback loop |
| Production health | App/API/DB smokes are green | Green | Vercel backend/UI smokes passed; workers idle before ranking #7 | Ranking #7 is paused and should be cancelled or resumed intentionally |

## Current Trust Score By Surface

| Surface | Score | Rationale |
| --- | ---: | --- |
| Ranking | 7.0 | Productive flow works and evidence is structured, but measured pass rate is not high enough and retries are common. |
| Application materials | 5.5 | Prompt v2 exists, but stored eval evidence still fails on length, specificity, and required terms. |
| ATS CV | 5.5 | Known historical internal-note failures are high severity; needs fresh v2 proof. |
| Judge/evals | 7.0 | Strong framework, but small dataset and limited judge calibration. |
| Production operations | 7.0 | Vercel/Turso/smokes are healthy; remaining risk is quality gating rather than uptime. |

Overall: 6.5/10.

## Immediate Blockers To High Trust

1. Golden set is too small.
2. v2 prompts have not been proven with a full fresh baseline.
3. Materials and ATS CV still have known historical quality failures.
4. Production confidence gates are not strict enough to support near-blind trust.
5. Ranking job `#7` is paused after manual interruption and should be intentionally cancelled, requeued, or resumed.

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

### Gate 3: Run Fresh v2 Baseline

Goal: measure active prompts, not stale historical outputs.

Done when:

- Ranking v2 baseline is run.
- Materials v2 baseline is run.
- ATS CV v2 baseline is run.
- Results are compared to prior summaries.
- Critical failures are listed separately from ordinary misses.

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
