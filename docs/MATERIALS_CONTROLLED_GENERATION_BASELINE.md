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
- Failed materials attempts are persisted in `materials_generation_attempts`.

Known remaining gaps:

- The legacy freeform CV path still exists for rollout comparison.
- Live benchmark arms require provider credentials.
- Planner prompt versions are not promoted until offline coverage and live comparison are complete.
