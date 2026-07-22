# Autoloop Usage

The autoloop is a controlled optimization framework for ranking prompts, safety gates, and evals. The current implementation is intentionally read-only: it selects probe cases and computes metrics, but it does not edit prompts, rerank jobs, commit changes, or call an LLM.

## Safety Rules

- Golden fixtures under `evals/fixtures/` are read-only unless a human explicitly approves edits.
- Runtime state and logs live under `logs/`, which is ignored by git.
- `AUTOLOOP_STOP` is the planned kill switch for the future orchestrator.
- Probe selection must stay small before any unattended rerank.
- Any future loop that applies changes must run `python -m pytest -q` before and after each commit.

## Files

- `config/autoloop_config.json`: default budgets, probe size, quotas, and guards.
- `config/autoloop_state.example.json`: example runtime state shape.
- `config/autoloop_known_hard_cases.json`: editable hard-case pool outside protected fixtures.
- `scripts/select_probe_cases.py`: selects a small stratified probe set.
- `scripts/compute_autoloop_metrics.py`: computes safety metrics over persisted rankings.
- `scripts/run_autoloop.py`: runs one dry-run iteration, writes state/logs, and evaluates guardrails.

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

## Acceptance Gates

The loop must not auto-accept a change when any of these regress:

- `critical_failures`
- `apply_now_unsafe_rate`
- `stale_completion_count`
- case-level regressions against the previous accepted baseline

Operational trust is not absolute correctness. The target is zero known critical failures under current coverage, honest review flags for uncertain cases, and repeatable gates before future prompt/model changes.
