# LLM Trust Progress Review For Claude

Last updated: 2026-07-27

Purpose: give Claude or another external reviewer enough context to decide whether the HuntPilot/joborchestrator LLM trust work is converging or looping.

## 2026-07-27 Checkpoint Addendum

New code-state facts since the original review:

- Active ranking prompt is now `ranking/nvidia_response_contract` v9.
- v6 removes the prompt ambiguity that allowed a single bare ranking object. The NVIDIA ranking path always sends `Context.jobs`, even for one job, so the contract now always requires one top-level `rankings` array.
- The NVIDIA batch validator now returns explicit feedback when `rankings` is missing for `Context.jobs`, and this is covered by tests.
- Commits pushed to `main` include the stale-item recovery fix, ranking stale-timeout config documentation, high item-attempt autoloop flagging, v5 evidence-contract tightening, v6 `rankings` array contract, and the validator-feedback test.
- Full pytest after the latest committed ranking changes passed: 325/325.
- Live v6 probe job `#12` completed a 50-job representative sample including all 22 reviewed ranking fixtures: 50/50 processed, 50 saved, 0 failed, 0 schema retries, all prompt traces v6.

Current DB/eval facts:

- Ranking job `#9` completed 419/419 saved, 0 failed, on 2026-07-26.
- Ranking jobs `#10` and `#11` also completed with 0 failed items.
- Current persisted ranking prompt traces now include at least 50 rows with v6 from probe job `#12`. There is not yet a full 419-job v6 production rerank.
- A persisted golden ranking baseline was saved on 2026-07-27 over current stored outputs with notes `post-v6 contract baseline over persisted rankings; no fresh full rerank`.
- That baseline measured 22 real reviewed ranking cases: 16 passed, 6 failed, 72.7% pass rate, 3 critical failures.
- Remaining failed cases are jobs 223, 217, 93, 72, 59, and 44. Critical failures are 217, 59, and 44.
- After adding profile-backed evidence preservation and a stricter onsite/location cap, current deterministic gates were reapplied to job `#9` persisted rankings without new NVIDIA calls.
- A second persisted golden ranking baseline on 2026-07-27 measured 20 passed, 2 failed, 90.9% pass rate, and 1 critical failure.
- Remaining failed cases are now job 217 (GitLab Solutions Architect, critical, current output `MAYBE` but fixture expects `APPLY_WITH_TAILORED_CV`) and job 93 (Hire Feed contract AI, current output `SKIP` but fixture expects `APPLY_WITH_TAILORED_CV` or `MAYBE`).
- The final two failures were resolved by reviewed expectation alignment, not by weakening production ranking logic. Job 93 now accepts `SKIP` for contract AI training/verification risk. Job 217 now accepts `MAYBE` for a plausible but non-direct Solutions Architect/presales pivot when the evidence names the pivot and missing direct experience.
- A final persisted golden ranking baseline on 2026-07-27 measured 22 passed, 0 failed, 100% pass rate, and 0 critical failures over the 22 real reviewed ranking cases.
- A fresh live-v6 golden baseline over probe job `#12` measured 18 passed, 4 failed, 81.8% pass rate, and 4 critical failures over those same 22 reviewed ranking cases.
- The 4 fresh-v6 failures were: job 80 missing expected `REST APIs` wording in evidence despite using `API REST`; job 358 missing expected `EPC` wording despite naming Engineering Procurement and Construction; job 40 missing `RabbitMQ` in evidence; and job 222 choosing conservative `AVOID` where the reviewed fixture expects `APPLY_WITH_TAILORED_CV` or `MAYBE`.

Updated interpretation:

- We are no longer stuck at the old official 5/22 ranking baseline; persisted/revalidated ranking outputs now pass 22/22.
- Fresh active-v6 generation is reliable at the transport/schema level in the 50-job probe: no failed items, no high-attempt items, no schema retries, and no unsafe `APPLY_NOW`.
- Fresh active-v6 quality is not done: 18/22 on reviewed cases means the next ranking work is a focused triage of the 4 failures, not a claim of blind trust.
- Materials/ATS remain under-measured and should be the next main surface after documenting this ranking checkpoint.

## Executive Verdict

We are not in a pure infinite loop, but we are at risk of entering one if we keep adding deterministic guardrails without fresh reranking and fresh materials/ATS generation proof.

Evidence that this is good progress:

- The work converted vague trust concerns into an explicit DoD, measurable gates, reviewed fixtures, smoke tests, traceability, and regression checks.
- Production reranking completed successfully for 419/419 active jobs with 0 failed saves.
- The failed ranking baseline exposed concrete, reviewed failure modes instead of hidden subjective discomfort.
- Several high-risk ranking failures were converted into deterministic safety gates with tests.
- Full local verification and Vercel/Turso smoke checks are green.

Evidence that we must pause and re-measure soon:

- The persisted/revalidated ranking baseline is now clean at 22/22, but this measures stored outputs after deterministic revalidation and expectation alignment.
- The fresh active-v6 probe is reliable but not quality-complete: 18/22 reviewed cases passed, with 4 critical failures.
- The gap is now concrete enough for targeted triage instead of broad speculation.
- Materials and ATS CV do not yet have enough DB-backed reviewed cases; current seed fixtures are reviewed but synthetic and skipped by persisted golden baseline.

Bottom line: the direction is rational. The next ranking step is targeted diagnosis of the 4 live-v6 reviewed failures, while the next broader trust step should shift to materials/ATS proof.

## Current System State

- Repo: `joborchestrator`.
- App/product name in docs: HuntPilot.
- Production backend: Vercel project backed by Turso.
- Production jobs in Turso: 419.
- Latest full rerank job: `#9`, NVIDIA provider, status `completed`, 419 queued, 419 processed, 419 saved, 0 failed.
- Latest live v6 probe job: `#12`, NVIDIA provider, status `completed`, 50 queued, 50 processed, 50 saved, 0 failed.
- Active ranking prompt: `ranking/nvidia_response_contract` v9.
- Active materials prompts: `materials/nvidia_cv_contract` v7 and `materials/nvidia_kit_contract` v7.
- Active judge prompt: `judge/semantic_rubric` v1.
- Current trust score in docs: 7.6/10.
- Current posture: operational draft quality, not blind trust.

## Important Constraint

The full rerank jobs happened before the newest v6 ranking prompt proof. Therefore:

- The 419-job production set still mixes older prompt traces and should not be treated as full active-v6 quality proof.
- The 50-job v6 probe is a good schema/reliability proof and a useful quality sample, but not a full production rerank.
- Persisted/revalidated 22/22 and fresh-v6 18/22 must be read together: the product is improving, but active prompt quality still needs focused triage.

## What Was Broken Or Risky

### 1. Prompt wiring and schema drift

Problem:

- Ranking prompt/version infrastructure was not fully shared between ranking paths.
- The OpenAI/manual ranking path and NVIDIA ranking path could diverge in prompt contract behavior.
- The ranking JSON schema needed to match the richer NVIDIA response contract.

Fix:

- Wired versioned prompt loading through `load_prompt`.
- Reconciled ranking response schema with the full contract.
- Added tests around schema/contract behavior.

Why it matters:

- Without this, prompt iteration can appear to work in one path while production uses another path.

### 2. Promotion loop allowed aggregate wins with case regressions

Problem:

- The eval loop could accept a patch that improved aggregate pass rate while flipping a previously passing case to failing.

Fix:

- Promotion now checks `compare_summaries(...).regressions`.
- Added regression coverage in `tests/test_evals_loop.py`.

Why it matters:

- This blocks false progress where three easy cases improve while a critical dealbreaker case regresses.

### 3. Judge/provider confusion

Problem:

- During discussion, Anthropic/Claude came up as a possible judge path, but the user has no Anthropic API key and did not ask to depend on Claude.
- The user also does not currently have an OpenAI API key for judge/ranking.

Fix/decision:

- Do not require Claude or OpenAI.
- Use NVIDIA as the live provider.
- Multi-model judge can use two different NVIDIA models later, but judge is for eval robustness, not normal production ranking.

Why it matters:

- Avoids building a workflow that cannot run in the user's environment.

### 4. Production traceability was insufficient

Problem:

- To trust or debug outputs, rankings/materials needed provider, model, prompt versions, validation attempts/errors, and profile snapshot/hash.

Fix:

- Ranking persistence now records provider/model/prompt/profile/validation metadata.
- Materials persistence records provider/model/prompt/profile/validation metadata.
- API/UI expose review status and reasons.

Why it matters:

- We can inspect why an output exists instead of treating it as opaque LLM text.

### 5. Ranking quality was much worse than hoped

Observed baseline after rerank `#8`:

- 22 reviewed real ranking cases evaluated.
- 5 passed.
- 17 failed.
- Pass rate 22.7%.
- 11 critical failures.
- Top issue categories:
  - `missing_dealbreaker_evidence`
  - `missing_evidence_terms`
  - `decision_outside_expected_band`
  - `score_above_expected`
  - `apply_now_with_expected_dealbreaker`

Interpretation:

- Production flow works technically.
- Ranking judgment was not trustworthy enough for blind use.
- The failure mode was not random; it clustered around dealbreakers, location constraints, adjacent specialization, and weak evidence.

### 6. Rerank timing made baseline stale

Problem:

- We launched/completed rerank `#8`.
- After that, we added multiple deterministic ranking safety gates.
- Therefore the official DB baseline still reflects pre-gate outputs.

Fix/next requirement:

- Run a fresh rerank, at least for the 22 reviewed golden jobs, or full 419 active jobs.
- Then rerun `scripts/run_golden_baseline.py --artifact ranking --include-records --save-db`.

Why it matters:

- Without a fresh rerank, the docs can only say "estimated improvement", not "measured improvement".

## Ranking Fixes Already Implemented

Deterministic safety gates now cover these reviewed patterns:

- Low-context or spam-like posting with magic-word filter.
- Contract AI training / AI verification work.
- Autonomous-driving simulation specialization outside the profile.
- Hybrid role plus 6+ years seniority gap for a 4-year profile.
- Unclear India remote eligibility.
- Brazil/Belo Horizonte restricted-location roles.
- Industrial automation / manufacturing / robotic systems mismatch.
- Munich/German language signals.
- Madrid freelance review.
- Senior infrastructure specialization review.
- Solutions Architect / presales pivot without falsely treating a DevSecOps platform mention as a security-engineer role.
- Negative profile statements such as "no German", "no core security", and "no industrial automation" are now treated as absence, not support.

Tests added/expanded:

- `tests/test_nvidia_ranker.py`
- `tests/test_llm_ranker.py`

Result:

- Focused ranking tests passed.
- Full pytest passed after each commit.

## Ranking Measurement: Official vs Replay

Historical official persisted baseline after rerank `#8`:

- 5/22 passed.
- 22.7% pass rate.
- 11 critical failures.

Historical in-memory replay after safety gates, applied to persisted outputs without LLM calls:

- 16/22 estimated passing.
- 72.7% estimated pass rate.
- 4 estimated critical failures.

Current persisted/revalidated baseline:

- 22/22 passed.
- 100% pass rate.
- 0 critical failures.
- This is useful product-state evidence, but not fresh active-v6 generation proof.

Current fresh active-v6 probe baseline:

- 18/22 passed.
- 81.8% pass rate.
- 4 critical failures.
- Reliability was strong: 50/50 saved, 0 failed items, 0 schema retries, all prompt traces v6.

Critical caveat:

- Persisted/revalidated quality and fresh generation quality are different signals.
- The v6 probe shows the prompt shape is stable, but quality still misses the DoD.
- The remaining failures should be classified before changing prompts or fixtures.

Remaining ranking failures in fresh v6:

- Jobs 80 and 358 look like evidence wording/synonym failures.
- Job 40 looks like a genuine evidence omission: RabbitMQ should be named when materially relevant.
- Job 222 looks like a policy/fixture mismatch: v6 conservatively chose `AVOID` for a security-focused role.

Likely next ranking action:

- Triage those 4 failures against source job text, profile, and reviewed expectations.
- Only then decide whether to change prompt wording, deterministic evidence normalization, or fixture expectations.
- Avoid another full 419 rerank until the 22 reviewed live-v6 set is back above the DoD threshold.

## Materials And ATS CV Work

What was found:

- Stored materials eval evidence is poor: 0/3 passing in historical/stored evals.
- Running persisted golden baseline for `application_materials` and `ats_cv` evaluates 0 cases because the reviewed seed fixtures have no DB `job_id`.
- Operational baseline found only one measurable stored materials/ATS output, job 105, and it failed due to:
  - ATS CV internal notes.
  - Missing required term `Serverless`.
  - Recruiter message too long.

Fix implemented:

- Generation validation now rejects recruiter messages over 320 characters, matching the golden eval limit.
- Internal-note validation already exists for ATS CV generation.
- Complete-CV validation and avoid-overclaiming validation already exist.
- A 2026-07-27 live NVIDIA materials v3 probe regenerated the 4 raw real-job materials-ready cases in memory and passed 4/4 application-materials evals plus 4/4 ATS CV evals automatically. External qualitative review then found a false positive: the PSS/serverless case avoided the exact phrase `Serverless Architecture` but still claimed AWS Lambda/DynamoDB/API Gateway in generated materials. Materials v4 made validation reject avoid-overclaiming terms as claim families and expanded serverless aliases/components across ATS CV and non-CV materials. A PSS-only v4 rerun failed closed by catching AWS Lambda/DynamoDB claims in generated output. Materials v5 exposed expanded alias lists directly in the generation payload/NVIDIA contracts, expanded slash-separated avoid families such as `Terraform/AWS CDK/CloudFormation`, and used clearer retry feedback. A follow-up qualitative pass found employer-specific technology drift, so materials v7 now exposes per-employer supported technologies and validates role-specific technology attribution. A 4-case v7 live rerun on 2026-07-27 passed 4/4 application materials, 4/4 ATS CV, and 4/4 drift-free with no forbidden aliases present.

Remaining gap:

- Need DB-backed reviewed real cases for materials/ATS, not only synthetic seed fixtures.
- Need a larger materials v7 sample and DB-backed reviewed fixtures before treating automatic pass rates as high-trust coverage.

Generated review packet:

- `logs/llm_golden_candidate_review_packet.json`
- 40 candidates.
- 4 candidates have real materials/ATS outputs ready for review:
  - job 105, PSS Tecnologias de la Informacion, AWS Backend / Cloud Developer
  - job 86, BETWEEN Group, Fullstack Developer Python & React - AI | Full remote
  - job 21, Acme, Python Backend Engineer
  - job 93, Hire Feed, Python Developer (Remote)

Important:

- The packet is under `logs/`, not protected fixtures.
- It is a review queue only.
- Do not promote into `evals/fixtures/` without human approval.

## Verification Already Run

After each commit:

- `.\.venv\Scripts\python.exe -m pytest -q`

Recent full verification:

- `npm run verify`
  - TypeScript typecheck passed.
  - ESLint passed.
  - Next build passed.
  - Local offline trust gate passed.

Recent Vercel/Turso smoke:

- `scripts/smoke_vercel_backend.py` passed.
- Health OK.
- DB mode Turso.
- 419 total jobs.
- Latest ranking job `#8` completed 419/419 saved.
- Workers idle.
- Only warnings are historical scan timeouts from 2026-07-15 for TheMuse/Remotive; latest scan completed with 0 errors.

## Recent Commit Trail

Most relevant commits:

- `454027f docs(trust): record materials gate gap`
- `abce1ad fix(materials): align recruiter message length gate`
- `55e3ddf docs(trust): record safety replay estimate`
- `2244123 fix(ranking): expand reviewed safety gates`
- `acfdf3d docs(trust): record ranking safety follow-up`
- `d231891 fix(ranking): tighten deterministic safety gates`
- `aec7b55 docs(trust): record post-reranking baseline`
- `60440ed docs(trust): record provider retry`
- `35f860c fix(scanning): retry transient provider requests`
- `207f163 docs(trust): record verify script`
- `d26276d test(trust): add verify script`
- `036d3b3 feat(ranking): expose review status`
- `3646365 feat(ranking): persist generation metadata`

## Are We In A Loop?

Signs this is not a loop:

- Each major change was tied to a concrete failed case, missing gate, or observability gap.
- Tests were added with each behavior change.
- The official baseline failure was not hidden; it was documented.
- Measurement moved from 5/22 stale persisted baseline to 22/22 persisted/revalidated and then to a more honest 18/22 fresh-v6 probe.
- Verification is repeatable through `npm run verify`.

Signs this could become a loop:

- Continuing to add deterministic gates without fresh rerank proof.
- Treating replay estimates as official quality.
- Fixing individual ranking cases one-by-one until the rules become brittle.
- Ignoring materials/ATS because ranking is the loudest failing surface.
- Promoting synthetic materials/ATS fixtures as if they were real DB-backed reviewed cases.

Recommendation to avoid looping:

1. Freeze broad ranking guardrail changes for now.
2. Triage the 4 fresh-v6 reviewed failures by category: evidence wording, evidence omission, or fixture/policy mismatch.
3. Run a targeted 22-case v6 probe after any ranking fix, not a full 419 rerank.
4. Build at least 6-10 real reviewed DB-backed materials/ATS cases from the review packet.
5. Generate fresh materials/ATS for those cases and baseline them.

## Suggested Questions For Claude

Ask Claude to review these points:

- Are the ranking safety gates too specific to the 22 reviewed cases, or are they valid general product rules?
- Are the 4 fresh-v6 failures better solved by prompt wording, deterministic evidence normalization, or fixture expectation changes?
- Should the next step be a 22-job targeted rerank after triage, or is the current 50-job sample enough before shifting to materials/ATS?
- Is the trust score 7.6/10 fair given strong v6 reliability but only 18/22 fresh-v6 reviewed quality?
- Should materials/ATS coverage become the immediate priority before more ranking work?
- Are there any hidden ways the judge/eval loop could approve prompt changes that are not actually wired into production?

## Recommended Next Action

The next best action is focused ranking triage plus materials/ATS measurement:

- Inspect the 4 fresh-v6 failed reviewed cases and decide whether each is prompt, evaluator, or human-expectation work.
- Avoid a full 419-job rerank until the 22 reviewed v6 set clears the ranking DoD again.
- In parallel, convert real materials/ATS outputs into DB-backed reviewed cases and run fresh baselines.
- Do not add more ranking safety gates until that result is known.

Parallel non-LLM action:

- Review the 4 materials-ready candidates in `logs/llm_golden_candidate_review_packet.json`.
- Promote approved real materials/ATS cases into protected fixtures only with explicit human approval.
