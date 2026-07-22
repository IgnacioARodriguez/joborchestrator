# LLM Trust Definition of Done

This document defines the minimum bar for trusting HuntPilot LLM outputs in production: job rankings, application materials, and ATS CV optimization.

The goal is not blind faith in an LLM. The goal is operational trust: the system should be reliable enough to save time, surface uncertainty honestly, and block or flag risky outputs before they affect real applications.

Current compliance is tracked in `docs/LLM_TRUST_COMPLIANCE_MATRIX.md`.

## Trust Target

HuntPilot LLM outputs are considered production-trustworthy when:

- Ranking, materials, and ATS CV prompts pass the reviewed golden set at the required thresholds.
- There are zero critical failures.
- Any uncertain, incomplete, or high-risk output is marked for human review.
- Prompt/model changes cannot be promoted if they introduce case-level regressions.
- Every production output is traceable to a prompt version, model, evidence, score, and review status.

## Scorecard

Use this as the plain-language maturity scale:

- 1-3: Experimental. Useful for exploration only.
- 4-5: Partially useful. Human review required for every output.
- 6-7: Operational draft quality. Good enough to assist, not good enough to trust automatically.
- 8-9: High trust. Most outputs can be accepted after quick review; risky cases are flagged.
- 10: Not a realistic target for LLM-driven job decisions. Treat as "no known critical failures under current coverage", not absolute correctness.

Target state for HuntPilot: 8+ across ranking, materials, and ATS CV.

Operational interpretation:

- 8/10 means critical failures and unsafe APPLY_NOW cases are zero on the reviewed golden set plus recent probes, case regressions are zero, and current production outputs are traceable to active prompt versions. This is enough for supervised personal use.
- 9/10 means the 8/10 bar plus human sampling of APPLY_NOW precision/recall and at least two consecutive reranking/eval runs without critical regression.
- 10/10 is not an automation target. LLM confidence is operational confidence, not a proof of perfect judgment.

## Required Golden Set

Before calling prompts high-trust, maintain a reviewed golden set with at least:

- 30-50 total cases minimum.
- Ranking cases covering APPLY_NOW, APPLY_WITH_TAILORED_CV, MAYBE, SKIP, and AVOID.
- Clear dealbreaker cases where APPLY_NOW must be blocked.
- Low-context or messy job descriptions.
- Strong-fit jobs with central requirements clearly present.
- Weak-fit jobs with tempting but unsupported keywords.
- Application materials cases for company-specific and role-specific writing.
- ATS CV cases that check truthfulness, required terms, formatting, and absence of internal notes.
- At least 10 negative cases where the correct behavior is restraint.

Golden cases must be reviewed before being used as a promotion gate. Unreviewed generated cases can be useful for exploration but must not become hard gates without review.

## Pass Thresholds

Minimum promotion thresholds:

- Ranking: >= 90% pass rate.
- Application materials: >= 90% pass rate.
- ATS CV: >= 95% pass rate.
- Critical failures: 0.
- Case-level regressions: 0 against the previous accepted prompt version.

Aggregate improvement is not enough. A prompt that improves average score but flips a previously passing critical case to failing is not promotable.

## Critical Failures

Any of these blocks promotion immediately:

- Inventing employers, degrees, certifications, projects, tools, years of experience, or responsibilities.
- Recommending APPLY_NOW despite an explicit dealbreaker or central requirement mismatch.
- Treating an unsupported skill as a strong match.
- Omitting a central requirement gap from ranking evidence.
- Producing ATS CV text with internal notes, prompt instructions, headings like "optimization notes", or reviewer-only metadata.
- Generating application materials that are generic and do not reference the target company, role, or truthful candidate strengths.
- Producing recruiter messages that are too long for realistic outreach.
- Failing schema validation or returning malformed JSON after retry.
- Hiding uncertainty instead of using review flags.

## Ranking DoD

A ranking prompt/version is done when:

- It returns valid structured JSON matching the ranking contract.
- It includes evidence for strong matches, gaps, dealbreakers, and red flags.
- It does not recommend APPLY_NOW for dealbreaker or central mismatch cases.
- It uses candidate profile and job text as source of truth.
- It sets confidence and review signals honestly.
- It passes ranking golden set threshold.
- It has zero critical ranking failures.
- Production ranking results store prompt version, model, score, decision, confidence, evidence, and timestamps.

## Materials DoD

Application materials prompts are done when:

- Recruiter messages are concise, specific, and truthful.
- Cover letters, when generated, are job-specific and not generic boilerplate.
- Materials do not invent credentials or exaggerate experience.
- Claims are derived from the candidate profile, ranking evidence, or job text.
- Output includes useful application angle and autofill notes without leaking internal instructions.
- Materials pass golden set threshold.
- Materials with low confidence or risky gaps are marked as drafts requiring review.

## ATS CV DoD

ATS CV prompts are done when:

- Generated CV text remains truthful to the base CV.
- Required keywords are included only when supportable.
- Unsupported keywords are avoided or framed conservatively.
- No internal notes, prompt instructions, or evaluation metadata appear in the CV.
- Formatting is usable as a candidate-facing CV.
- ATS CV pass rate is >= 95%.
- Critical ATS failures are 0.

## Judge And Eval DoD

The judge/eval system is done when:

- Deterministic evals cover known hard rules.
- LLM judge uses the versioned rubric prompt.
- Judge outputs normalized issue_codes from the known taxonomy.
- Multi-model judge mode is available for disputed or high-risk evaluations.
- Same-provider/same-model judge duplication is skipped.
- Eval loop compares against previous accepted summaries.
- Promotion blocks on case regressions.
- Eval summaries are human-readable and stored.

The judge is for evaluating prompt robustness. It is not part of normal production ranking unless a separate audited-ranking feature is explicitly enabled.

## Production Confidence Gates

Production outputs should require human review when:

- Confidence is below the configured threshold.
- Evidence is thin or job text is low quality.
- A central requirement is uncertain.
- The job has possible relocation, language, seniority, authorization, salary, or location mismatch.
- The model flags requires_llm_review.
- The output was produced after validation retry.
- A schema repair or fallback path was needed.

Default behavior should be "draft/review" for uncertain outputs, not silent acceptance.

## Observability Requirements

Each production LLM output should preserve:

- Artifact type: ranking, materials, ATS CV, judge result.
- Prompt target and active version.
- Provider and model.
- Input job id and candidate profile version or snapshot reference.
- Output score, decision, confidence, and evidence.
- Review flags and escalation reasons.
- Validation/retry metadata.
- Created and updated timestamps.
- User action when available: accepted, edited, rejected, applied, ignored.

## Prompt Promotion Checklist

Before promoting a prompt version:

- Run deterministic evals.
- Run golden set evals.
- Run LLM judge where appropriate.
- Compare against previous accepted summary.
- Confirm pass thresholds are met.
- Confirm zero critical failures.
- Confirm zero case-level regressions.
- Review a sample of passing outputs manually.
- Commit prompt changes atomically.
- Record summary of tests and assumptions.

## Current Known Gaps

As of this document, the prompt infrastructure is stronger than the measured prompt quality.

Known gaps to close:

- The golden set is still small.
- Materials and ATS CV need a fresh v2 baseline run.
- Historical eval summaries showed failures around missing required terms, recruiter message length, and internal notes in ATS CV output.
- Ranking still relies on retry for some malformed NVIDIA first responses.
- Production ranking does not run judge automatically, by design.

## Done Means

Prompts can be considered high-trust when the repo can answer "yes" to all of these:

- Do we have reviewed golden cases for this surface?
- Does the current prompt pass the threshold?
- Are critical failures at zero?
- Are regressions at zero?
- Are uncertain outputs flagged?
- Can every production output be traced to prompt version, model, evidence, and review status?
- Can we rerun the same gate before any future prompt/model change?

Until then, outputs are useful assistance, not blindly trusted decisions.
