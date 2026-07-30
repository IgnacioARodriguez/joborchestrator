# Materials Controlled Generation Baseline

Baseline source: `materials_generation_logs_for_gpt_20260730_122014.zip`, generated on 2026-07-30.

The packet contains 29 sanitized operation records. NVIDIA completed 6 operations, failed 4, had 3 running and 12 queued. OpenAI completed 4. Recorded average durations were 288.7 seconds for NVIDIA and 29.8 seconds for OpenAI.

Observed validation themes:

- `overcompressed_cv`: 10
- `missing_canonical_role_tech`: 8
- `keywords_not_in_cv`: 5
- `unsupported_role_specific_tech`: 2
- `unsupported_ranking_terms`: 3

Representative regression fixtures are stored in `tests/fixtures/materials_evidence_baseline.json`.

Controlled pipeline direction:

```text
Base CV
  |
Canonical CV IR
  |
Supported job facts
  |
LLM planning
  |
Deterministic rendering
  |
Validation
  |
Deterministic repair
  |
Targeted semantic repair
  |
Fallback / human review
```

Initial implementation notes:

- `keywords_used` is derived in code from rendered CV text and supported keywords.
- Validation feedback can be converted to stable structured issues.
- NVIDIA repair prompts receive the previous response and an explicit frozen-field directive.
- A deterministic CV IR and renderer provide a rollout path behind feature flags.
- Accepted and failed materials attempts are persisted in `materials_generation_attempts`; accepted metadata can emit `stage_attempts` so CV and kit rows remain separable.
- Application kit parsing accepts a structured internal `autofill` object, renders it to persisted `autofill_notes`, and rejects JSON-encoded object strings in `autofill_notes`.
- Application kit validation fails closed on clear English/Spanish language mismatch when the job language has enough signal.

Known remaining gaps:

- The legacy freeform CV path still exists for rollout comparison.
- Live benchmark arms require provider credentials.
- Planner prompt versions are not promoted until offline coverage and live comparison are complete.


## Planner And Renderer Rollout

The controlled path now has a dedicated NVIDIA planner contract: `materials/nvidia_cv_planner_contract` at `v1`. When both `MATERIALS_CONTROLLED_CV_ENABLED` and `MATERIALS_NVIDIA_PLANNER_ENABLED` are enabled, `build_application_kit_with_nvidia` uses NVIDIA for CV planning and renders `ats_cv_text` deterministically in code.

Responsibilities:

- Planner: select evidence IDs, skill IDs, and role bullet IDs. It must not write `ats_cv_text` or `keywords_used`.
- Renderer: preserve identity, all role headers, titles, companies, dates, mandatory bullets, canonical technologies, and education.
- Validator: map legacy feedback into structured `ValidationIssue` codes while compatibility callers still consume strings.
- Repair: deterministic repair runs before semantic repair. Semantic repair receives the previous response, mutable fields, and frozen fields.
- Kit: active `materials/nvidia_kit_contract` v14 requires structured `autofill` with `core_pitch`, availability, work authorization, location, and caveats while storage/API compatibility still exposes rendered `autofill_notes`.
- Language: kit validation checks recruiter, cover letter, and autofill text against conservative English/Spanish job-language detection.

Rollout flags remain off by default:

- `MATERIALS_CONTROLLED_CV_ENABLED`
- `MATERIALS_NVIDIA_PLANNER_ENABLED`
- `MATERIALS_OPENAI_FALLBACK_ENABLED` enables OpenAI CV planner fallback after NVIDIA CV-stage failure; the rendered CV still comes from code.
- `MATERIALS_MAX_SEMANTIC_REPAIRS` defaults to `1`

Queued LLM regenerations now clear stale material fields and mark `queued_generation_pending`, so an old successful CV cannot appear as the result of a queued or failed new operation.

## Offline Benchmark

Command:

```bash
python scripts/run_materials_controlled_benchmark.py --output data/materials_controlled_benchmark_offline.json
```

Latest offline run on the evidence packet:

| Arm | Label | Hard-valid first pass | Hard-valid final | Retries / remaining themes | Fallbacks | Median latency seconds | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| A | Baseline NVIDIA current | not measured | not measured | 28 | 0 | 288.7 | Stored packet baseline |
| B | NVIDIA freeform improved | offline only | offline only | 23 | 0 | 202.09 | Derives metadata, still freeform |
| C | NVIDIA planner + renderer | offline only | offline only | 15 | 0 | 101.04 | Removes canonical-tech and metadata classes by construction |
| D | NVIDIA planner + renderer + OpenAI fallback | offline only | offline only | 0 | 1 | 65.42 | Estimated offline architecture target; live credentials required |
| E | OpenAI with CV IR and renderer | offline only | offline only | 15 | 0 | 29.8 | Provider control arm |

Context size sample: legacy `6733` chars vs generation context `269` chars.

These are offline architecture estimates from stored evidence themes, not live pass-rate claims. Live benchmark remains pending provider credentials.

## Production Recommendation

Safe now:

- Keep legacy materials generation active.
- Enable the deterministic `keywords_used` derivation already integrated into legacy/provider calls.
- Keep accepted/failed attempt persistence active.
- Use `materials_generation_attempts` for audit and debugging.

Keep disabled until live paired benchmark evidence exists:

- `MATERIALS_CONTROLLED_CV_ENABLED`
- `MATERIALS_NVIDIA_PLANNER_ENABLED`
- `MATERIALS_OPENAI_FALLBACK_ENABLED`

OpenAI fallback is implemented as planner fallback for the CV stage, not as freeform historical CV authorship. If `OPENAI_API_KEY` is unavailable, the original NVIDIA CV failure metadata is preserved and the operation remains auditable.

Retire legacy only after a 10-20 job paired benchmark shows hard factual invariants at target thresholds and no regression in application kit quality.
