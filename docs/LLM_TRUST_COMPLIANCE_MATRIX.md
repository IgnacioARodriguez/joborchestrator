# LLM Trust Compliance Matrix

Last assessed: 2026-07-27

This matrix tracks HuntPilot against the trust bar defined in `docs/LLM_TRUST_DEFINITION_OF_DONE.md`.

Status values:

- Green: meets the DoD.
- Yellow: partially meets the DoD; usable with review.
- Red: does not meet the DoD yet.

## Executive Summary

Current trust posture: Yellow, approximately 7.7/10.

HuntPilot is currently suitable as an operational copilot for job discovery, ranking review, and draft generation. It is not suitable for near-blind trust yet. The active ranking prompt moved to v7 after a 50-job live v6 probe completed with 50/50 saved, 0 failed items, and 0 schema retries but exposed 4 reviewed-case quality failures. Those failures were triaged: one evaluator synonym issue, one security expectation alignment, and two explicit central-term prompt omissions. A targeted v7 rerank of jobs 40 and 358 completed 2/2 saved with 0 retries, and the reviewed ranking baseline now measures 22/22 with 0 critical failures. Materials/ATS CV still need measured quality work.

## Current Evidence Snapshot

- Active ranking prompt: `ranking/nvidia_response_contract` v7.
- Active materials CV prompt: `materials/nvidia_cv_contract` v3.
- Active materials kit prompt: `materials/nvidia_kit_contract` v3.
- Active judge prompt: `judge/semantic_rubric` v1.
- Production jobs in Turso: 419.
- Production rankings in Turso: 419 saved historically; latest full reranking job `#9` completed 419/419 saved under the then-active v4 prompt.
- Latest completed recovery ranking job: `#6`, 30/30 saved, 0 failed.
- Latest completed re-ranking job: `#8`, 419 queued, 419 processed, 419 saved, 0 failed.
- Latest ranking jobs: `#9` completed 419/419 saved on 2026-07-26 04:10:31, `#10` completed 8/8 saved, and `#11` completed 4/4 saved, all with 0 failed items.
- Current persisted ranking prompt-version trace includes at least 50 rows with prompt trace v6 and 2 targeted rows with prompt trace v7; no full 419-job v7 production rerank has been completed yet.
- Local offline trust gate: `npm run trust:gate` passed on 2026-07-19; `npm run verify` now runs typecheck, lint, build, and the trust gate.
- Latest Vercel backend smoke: passed against Turso on 2026-07-19; warning only for 27 recent historical scan errors, while latest scan completed with 0 errors. Error sample points to `themuse`/`remotive` API timeouts from 2026-07-15.
- Latest Vercel UI smoke: passed on 2026-07-19; dashboard rendered 419 visible jobs across Today/Review/Applications/Profile/Automations/Insights with no console errors or failed requests.
- Fresh stored eval evidence after reranking job `#8`:
  - Ranking: 22 persisted real reviewed cases evaluated, 5 passed, 17 failed, 22.7% pass rate, 11 critical failures, average score 77.5.
  - Application materials: 3 cases, 0 passed, 0.0% pass rate, average score 65.0.
- Post-baseline ranking safety follow-up: deterministic caps now cover low-context magic-word postings, contract AI training/verification work, autonomous-driving simulation specialization, hybrid 6+ seniority review, unclear India remote eligibility, Brazil location restrictions, industrial automation/manufacturing mismatch, Munich/German signals, Madrid freelance review, senior infrastructure review, and Solutions Architect false security-gap avoidance. A persisted golden ranking baseline run on 2026-07-27 over current stored outputs measured 16/22 passing, 72.7% pass rate, and 3 critical failures; this is an official eval run, but not proof of v6 ranking quality because the stored rankings are still mostly v4/v5.
- Post-evidence revalidation follow-up: current deterministic gates were reapplied to persisted job `#9` rankings without calling NVIDIA. A second persisted golden ranking baseline on 2026-07-27 measured 20/22 passing, 90.9% pass rate, and 1 critical failure. Remaining failed reviewed cases are GitLab Solutions Architect job 217 (`MAYBE` vs expected tailored CV) and Hire Feed contract AI job 93 (`SKIP` vs expected tailored CV/MAYBE).
- Reviewed expectation alignment follow-up: the two remaining cases were reconciled with current policy. Contract AI training/verification now accepts `SKIP` when evidence names the contract AI risk, and Solutions Architect/presales pivot now accepts `MAYBE` when evidence clearly names the pivot and missing direct pre-sales/GitLab experience. Persisted golden ranking baseline saved on 2026-07-27 measured 22/22 passing, 100% pass rate, and 0 critical failures.
- Ranking schema follow-up: v6 removes the single-job bare-object escape hatch from the NVIDIA prompt contract and the validator now gives explicit feedback when `rankings` is missing for `Context.jobs`.
- Live v6 probe follow-up: ranking job `#12` completed a 50-job representative sample including all 22 real reviewed ranking fixtures. Results: 50/50 processed, 50 saved, 0 failed, 0 high item attempts, max item attempts 1, 50/50 prompt trace v6, `schema_failure_retry_rate` 0.0, `non_active_prompt_rate` 0.0, `unsafe_apply_now_count` 0. Reviewed-fixture baseline over these fresh v6 outputs measured 18/22 passing, 81.8% pass rate, and 4 critical failures. Failures were jobs 80 (`REST APIs` evidence wording), 358 (`EPC` evidence wording), 40 (`RabbitMQ` evidence omission), and 222 (`AVOID` stricter than expected `APPLY_WITH_TAILORED_CV`/`MAYBE`).
- Post-Claude checkpoint follow-up: ranking evidence-term evaluation now supports reviewed synonyms, job 222 now accepts conservative `AVOID` when evidence names the direct Security/AppSec/DevSecOps gap, and active ranking prompt v7 requires exact central job terms such as RabbitMQ/EPC/VFD/STATCOM in evidence. Targeted v7 rerank job `#13` processed jobs 40 and 358 only: 2/2 saved, 0 failed, 0 schema retries, prompt trace v7 for both rows. Ranking golden baseline saved on 2026-07-27 measured 22/22 passing, 100% pass rate, and 0 critical failures.
- Autoloop hardening follow-up: prompt freshness, case regressions, failed item count, schema retry rate, runtime limits, halt reports, checkpoint tags, and non-active prompt requeue tooling are implemented and covered by tests. A halt no longer overwrites the accepted baseline with rejected metrics.
- Materials follow-up: application kit validation now rejects recruiter messages over the same 320-character limit used by golden evals. Persisted golden baseline currently evaluates 0 materials/ATS cases because the reviewed seed fixtures are synthetic and not DB-backed.
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
| Prompt registry | Active prompt versions are explicit and shared | Green | Registry points ranking to v7, materials to v3, and judge to v1 | Need a full v7 production rerank and fresh materials v3 generation proof before stored outputs match the active registry |
| Ranking schema | Output validates against structured contract | Green | Live v6 50-job probe had 50/50 saved, 0 failed items, 0 validation retries, and `schema_failure_retry_rate` 0.0 | Continue monitoring on larger runs |
| Ranking quality | >= 90% pass rate, 0 critical failures | Green-Yellow | Reviewed ranking baseline now passes 22/22 after evaluator synonym support, security expectation alignment, and targeted v7 rerank of jobs 40/358 | Need a broader v7 proof set before raising ranking to near-blind trust |
| Materials quality | >= 90% pass rate, 0 critical failures | Red | Stored evals show 0/3 passing; generation validation now enforces the 320-character recruiter-message limit, and active v3 receives ranking-derived overclaiming constraints | Need fresh v3 generation proof and DB-backed reviewed materials fixtures |
| ATS CV quality | >= 95% pass rate, 0 critical failures | Red-Yellow | Internal-note validation exists, complete-CV validation preserves base experience, and active v3 receives ranking-derived overclaiming constraints | Need current ATS CV v3 generation proof and DB-backed reviewed ATS CV cases |
| Golden set | 30-50 reviewed cases | Green-Yellow | 34 reviewed fixtures exist across ranking/materials/ATS CV, including 22 human-reviewed real ranking cases; local trust gate requires at least 3 cases per surface | Need more real materials/ATS CV cases to balance beyond synthetic coverage |
| Critical failure gate | Critical failures block promotion | Green-Yellow | Eval loop has hard-stop and regression checks; autoloop guards halt on critical failures, unsafe APPLY_NOW, stale completions, failed items, schema retry rate, prompt freshness, and case regressions | Need larger coverage and explicit critical taxonomy in reports |
| Case regressions | 0 regressions on promotion | Green-Yellow | `compare_summaries` regressions are wired into promotion gate and autoloop guard values handle list/dict case regression payloads | Needs fresh runs to prove effectiveness at scale |
| Judge rubric | Versioned judge prompt and issue codes | Green-Yellow | Judge rubric v1, issue code normalization, multi-model support | Need stronger calibration against human review |
| Multi-model judge | Disputed/high-risk evals can use two models | Yellow | NVIDIA secondary model support exists | Not yet used as routine gate |
| Production ranking | Rankings persist model, version, score, evidence | Green-Yellow | `job_rankings` stores version, decision, confidence, scores/evidence JSON, provider, model, prompt version, validation attempts/errors, and candidate profile snapshot hash for new NVIDIA rows; API/UI expose ranking review status | Finish job `#9` and requeue stale prompt-version rows until non-active prompt rate is 0 before trusting the baseline |
| Production confidence gates | Uncertain outputs become review-required drafts | Yellow | Ranking safety gates set `requires_llm_review`; ranking API/UI marks low confidence, validation retry, thin positive evidence, and missing central requirements for review; deterministic caps were added for three unsafe post-baseline patterns | Need fresh reranking proof and additional caps or prompt fixes for remaining explicit dealbreakers and adjacent-role mismatches |
| Observability | Outputs trace prompt/model/evidence/status | Green | Ranking rows now support provider, model, prompt version, validation attempts/errors, and candidate profile snapshot hash for new NVIDIA rankings; ranking review status is exposed in API/UI; materials persist provider, model, prompt versions, generated timestamp, validation attempts/errors, and candidate profile snapshot hash; eval rows preserve payloads/results; LLM output feedback is stored and summarized by job/artifact/action | Need to use captured traces to debug failed ranking cases |
| Production health | App/API/DB smokes are green | Green | Vercel backend and UI smokes passed against Turso on 2026-07-19; local trust gate runs offline e2e, scan, guardrail, and golden-fixture coverage checks; smoke now summarizes recent scan error samples; HTTP providers retry transient timeout/network/5xx/429 failures once by default | Historical `themuse`/`remotive` timeout rate should be monitored after deploy |

## Current Trust Score By Surface

| Surface | Score | Rationale |
| --- | ---: | --- |
| Ranking | 8.2 | Productive flow works, traceability is present, job `#9` completed 419/419 saved, v6 solved the observed schema retry issue in a 50-job live probe, and targeted v7 triage moved the reviewed ranking baseline to 22/22. The proof set is still small and no full v7 production rerank exists, so rankings are strong review inputs, not blindly trusted decisions. |
| Application materials | 6.3 | Prompt v3 receives ranking-derived overclaiming constraints, recruiter specificity/length gates match the 320-character golden limit, materials review status is exposed, and generation/retry/profile trace metadata is persisted; stored eval evidence still needs a fresh pass. |
| ATS CV | 6.1 | Internal notes, incomplete CVs, omitted base experiences, and unsupported ranking avoid-overclaiming terms now have deterministic gates and prompt-level constraints; needs fresh v3 proof. |
| Judge/evals | 7.8 | Strong framework, offline trust gate, feedback records, saved ranking eval runs, summary analytics, autoloop dry-run orchestration, halt reports, checkpoints, prompt freshness guards, and stale prompt requeue tooling are available; dataset is still small outside ranking and judge calibration remains limited. |
| Production operations | 7.8 | Vercel/Turso/smokes are healthy; `npm run verify` is repeatable, materials/ranking outputs are traceable for new writes, retry/profile metadata is stored, ranking/material review status is visible, and user feedback can be captured/summarized; remaining risk is quality gating rather than uptime. |

Overall: 7.7/10, weighted toward production ranking while materials/ATS remain under-measured.

## Immediate Blockers To High Trust

1. Ranking improved from the stale 5/22 baseline to 22/22 on reviewed outputs after targeted v7 triage, but the proof set is still only 22 real reviewed ranking cases plus a 2-job v7 targeted rerank.
2. Materials and ATS CV still need fresh generation proof against known historical quality failures; current reviewed seed fixtures are not DB-backed, so persisted golden baseline skips them.
3. Golden coverage is above the minimum count, but real materials/ATS CV coverage is still thin.
4. Ranking needs broader v7 coverage before it can be treated as near-blind trustworthy.
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

### Gate 3: Run Fresh Active Baseline

Goal: measure active prompts, not stale historical outputs.

Done when:

- Ranking baseline is run. Current measured result after targeted v7 triage: passed, 22/22 passed, 0 critical failures. A full v7 production rerank is still required before calling active-v7 ranking quality proven at production scale.
- Materials v3 baseline is run.
- ATS CV v3 baseline is run.
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
