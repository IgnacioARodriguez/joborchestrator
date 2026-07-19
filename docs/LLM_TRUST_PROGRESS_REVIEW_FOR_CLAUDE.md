# LLM Trust Progress Review For Claude

Last updated: 2026-07-19

Purpose: give Claude or another external reviewer enough context to decide whether the HuntPilot/joborchestrator LLM trust work is converging or looping.

## Executive Verdict

We are not in a pure infinite loop, but we are at risk of entering one if we keep adding deterministic guardrails without fresh reranking and fresh materials/ATS generation proof.

Evidence that this is good progress:

- The work converted vague trust concerns into an explicit DoD, measurable gates, reviewed fixtures, smoke tests, traceability, and regression checks.
- Production reranking completed successfully for 419/419 active jobs with 0 failed saves.
- The failed ranking baseline exposed concrete, reviewed failure modes instead of hidden subjective discomfort.
- Several high-risk ranking failures were converted into deterministic safety gates with tests.
- Full local verification and Vercel/Turso smoke checks are green.

Evidence that we must pause and re-measure soon:

- The official persisted ranking baseline is still based on rankings produced before the newest safety gates.
- The official ranking baseline is still bad: 5/22 reviewed real cases passed, 11 critical failures.
- In-memory replay estimates improvement to 16/22 and 4 critical failures, but that is not an official production measurement.
- Materials and ATS CV do not yet have enough DB-backed reviewed cases; current seed fixtures are reviewed but synthetic and skipped by persisted golden baseline.

Bottom line: the direction is rational, but the next ranking step should be measurement, not more speculative patching.

## Current System State

- Repo: `joborchestrator`.
- App/product name in docs: HuntPilot.
- Production backend: Vercel project backed by Turso.
- Production jobs in Turso: 419.
- Latest rerank job: `#8`, NVIDIA provider, status `completed`, 419 queued, 419 processed, 419 saved, 0 failed.
- Active ranking prompt: `ranking/nvidia_response_contract` v2.
- Active materials prompts: `materials/nvidia_cv_contract` v2 and `materials/nvidia_kit_contract` v2.
- Active judge prompt: `judge/semantic_rubric` v1.
- Current trust score in docs: 6.6/10.
- Current posture: operational draft quality, not blind trust.

## Important Constraint

The rerank job `#8` happened before the newest ranking safety gates were added. Therefore:

- The official DB ranking baseline measures stale production outputs.
- Any expected improvement from the newest guardrails needs a fresh rerank to become real.
- The in-memory replay is useful as a diagnostic estimate only.

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

Official persisted baseline after rerank `#8`:

- 5/22 passed.
- 22.7% pass rate.
- 11 critical failures.

In-memory replay after safety gates, applied to persisted outputs without LLM calls:

- 16/22 estimated passing.
- 72.7% estimated pass rate.
- 4 estimated critical failures.

Critical caveat:

- Replay is not the same as reranking. It applies current post-processing to old LLM outputs.
- It is useful to show the safety gates are directionally valuable.
- It is not enough to claim the current production ranking quality.

Remaining ranking failures in replay:

- Some persisted outputs were already too low for adjacent-but-worth-tailoring roles.
- Deterministic safety gates should not promote low decisions upward.
- These likely need prompt/model reranking, not more safety caps.

Likely next ranking action:

- Rerank the 22 reviewed golden jobs first if possible, then full 419 active jobs.
- If only full rerank infrastructure exists, rerank all 419.
- After rerank, run the official golden baseline and compare to both 5/22 official old baseline and 16/22 replay estimate.

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

Remaining gap:

- Need fresh generation proof for materials and ATS CV.
- Need DB-backed reviewed real cases for materials/ATS, not only synthetic seed fixtures.

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
- Replay moved from 5/22 official stale baseline to 16/22 estimated with fewer critical failures.
- Verification is repeatable through `npm run verify`.

Signs this could become a loop:

- Continuing to add deterministic gates without fresh rerank proof.
- Treating replay estimates as official quality.
- Fixing individual ranking cases one-by-one until the rules become brittle.
- Ignoring materials/ATS because ranking is the loudest failing surface.
- Promoting synthetic materials/ATS fixtures as if they were real DB-backed reviewed cases.

Recommendation to avoid looping:

1. Freeze ranking guardrail changes for now.
2. Rerank the 22 reviewed ranking jobs or all 419 active jobs.
3. Run official ranking golden baseline.
4. If ranking is still below threshold, separate failures into:
   - unsafe high scores requiring safety caps,
   - low-score false negatives requiring prompt/model improvement,
   - fixture expectation mismatch requiring human review.
5. Build at least 6-10 real reviewed DB-backed materials/ATS cases from the review packet.
6. Generate fresh materials/ATS for those cases and baseline them.

## Suggested Questions For Claude

Ask Claude to review these points:

- Are the ranking safety gates too specific to the 22 reviewed cases, or are they valid general product rules?
- Should the next step be a 22-job targeted rerank or full 419-job rerank?
- Which remaining replay failures should not be solved by deterministic gates?
- Is the trust score 6.6/10 too optimistic given official ranking is still 5/22?
- Should materials/ATS coverage become the immediate priority before more ranking work?
- Are there any hidden ways the judge/eval loop could approve prompt changes that are not actually wired into production?

## Recommended Next Action

The next best action is measurement:

- Rerank at least the 22 reviewed real ranking jobs with current code.
- Prefer full 419-job rerank if operationally acceptable.
- Run the persisted golden ranking baseline and save DB eval results.
- Do not add more ranking safety gates until that result is known.

Parallel non-LLM action:

- Review the 4 materials-ready candidates in `logs/llm_golden_candidate_review_packet.json`.
- Promote approved real materials/ATS cases into protected fixtures only with explicit human approval.

