# Autoloop Usage

The autoloop is a controlled optimization framework for ranking prompts, safety gates, and evals. The current implementation is intentionally read-only: it selects probe cases and computes metrics, but it does not edit prompts, rerank jobs, commit changes, or call an LLM.

## Safety Rules

- Golden fixtures under `evals/fixtures/` are read-only unless a human explicitly approves edits.
- Runtime state and logs live under `logs/`, which is ignored by git.
- `AUTOLOOP_STOP` is the planned kill switch for the future orchestrator.
- Runtime limits in `config/autoloop_config.json` stop the loop before work starts when iteration, API-call, token, or no-improvement caps are reached.
- Probe selection must stay small before any unattended rerank.
- Any future loop that applies changes must run `python -m pytest -q` before and after each commit.

## Files

- `config/autoloop_config.json`: default budgets, probe size, quotas, and guards.
- `config/autoloop_state.example.json`: example runtime state shape.
- `config/autoloop_known_hard_cases.json`: editable hard-case pool outside protected fixtures.
- `scripts/select_probe_cases.py`: selects a small stratified probe set.
- `scripts/compute_autoloop_metrics.py`: computes safety metrics over persisted rankings.
- `scripts/run_autoloop.py`: runs one dry-run iteration, writes state/logs, and evaluates guardrails.
- `scripts/create_probe_ranking_job.py`: turns selected probe cases into a small ranking job; dry-run unless `--execute` is passed.
- `scripts/autoloop_checkpoints.py`: creates idempotent annotated git tags such as `autoloop-checkpoint-3`.

## Dry-Run Commands

Select probe cases for the current ranking job:

```bash
python scripts/select_probe_cases.py --ranking-job-id 9 --target-total 20
```

Compute metrics for the current ranking job:

```bash
python scripts/compute_autoloop_metrics.py --ranking-job-id 9
```

Write metrics to logs:

```bash
python scripts/compute_autoloop_metrics.py --ranking-job-id 9 --output logs/autoloop_metrics.json
```

Run one dry-run iteration:

```bash
python scripts/run_autoloop.py --dry-run --ranking-job-id 9
```

The dry-run command writes:

- `logs/autoloop_state.json`
- `logs/autoloop_log.jsonl`
- `logs/autoloop_probe_cases.json`

It does not call an LLM, edit prompts, rerank jobs, commit, or push.

Create a git checkpoint before a future real loop applies a change:

```bash
python scripts/autoloop_checkpoints.py --iteration 3
```

The checkpoint command refuses a dirty worktree by default. Re-running it for the same iteration is allowed only when the existing tag points at the current commit.

Preview a small probe ranking job from selected risky cases:

```bash
python scripts/create_probe_ranking_job.py --category suspicious_apply_now --limit 8
```

Create that small ranking job explicitly:

```bash
python scripts/create_probe_ranking_job.py --category suspicious_apply_now --limit 8 --execute
```

## Acceptance Gates

The loop must not auto-accept a change when any of these regress:

- `critical_failures`
- `apply_now_unsafe_rate`
- `stale_completion_count`
- `non_active_prompt_rate`
- case-level regressions against the previous accepted baseline

Operational trust is not absolute correctness. The target is zero known critical failures under current coverage, honest review flags for uncertain cases, and repeatable gates before future prompt/model changes.

`non_active_prompt_rate` must be `0.0` before trusting a ranking-job baseline. A mixed prompt set can make safety metrics look green while old rankings still represent the prior behavior.
