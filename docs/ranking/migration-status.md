# Ranking migration status

This file is updated by `scripts/verify_ranking_migration.py`. A phase is not complete unless its executable verification command has replaced `PENDING` with `PASSED`.

<!-- phase:phase-0-integrity:start -->
## Phase 0 — Decision authority and trace integrity

- Status: `PASSED`
- Verification: `python scripts/verify_ranking_migration.py --phase phase-0-integrity`
- Criterion: ranking decisions control the next action; current visibility controls freshness; work-mode fields are combined; stale candidate-profile hashes force reranking; central requirements survive compact DTO serialization.
- Last verified UTC: `2026-08-02T11:09:29+00:00`
- Metrics: `{"after_action":"Skip","before_action":"Apply now","contradictions_after":0,"contradictions_before":4,"freshness_after":"fresh","profile_status_after":"current"}`
<!-- phase:phase-0-integrity:end -->

<!-- phase:phase-1-persistence:start -->
## Phase 1 — Persistence and queue idempotency

- Status: `PASSED`
- Verification: `python scripts/verify_ranking_migration.py --phase phase-1-persistence`
- Criterion: active ranking jobs cannot duplicate the same posting/version pair, and rankings created from an older candidate profile are returned for reranking.
- Last verified UTC: `2026-08-02T11:09:29+00:00`
- Metrics: `{"duplicate_items_after":0,"duplicate_items_before":1,"rerank_ids_after":[2,3],"second_job_total_after":1}`
<!-- phase:phase-1-persistence:end -->

<!-- phase:phase-2-deterministic:start -->
## Phase 2 — Fact extraction and deterministic decision

- Status: `PASSED`
- Verification: `python scripts/verify_ranking_migration.py --phase phase-2-deterministic`
- Criterion: the deterministic engine satisfies all fixed abstract cases, improves decision agreement over the frozen baseline, exposes every required assessment, and contains no fixture-specific rule or prompt example.
- Last verified UTC: `2026-08-02T11:09:29+00:00`
- Metrics: `{"cases":6,"decision_agreement_after":6,"decision_agreement_before":1,"outputs":[{"coverage":1.0,"decision":"APPLY_NOW","expected":"APPLY_NOW","id":"direct_match","score":98},{"coverage":0.8594,"decision":"APPLY_WITH_TAILORED_CV","expected":"APPLY_WITH_TAILORED_CV","id":"partial_match","score":78},{"coverage":0.5,"decision":"SKIP","expected":"SKIP","id":"missing_required","score":47},{"coverage":0.4545,"decision":"AVOID","expected":"AVOID","id":"blocking_constraint","score":34},{"coverage":0.6,"decision":"MAYBE","expected":"MAYBE","id":"unknown_required","score":62},{"coverage":0.0,"decision":"AVOID","expected":"AVOID","id":"invalid_posting","score":0}]}`
<!-- phase:phase-2-deterministic:end -->

<!-- phase:phase-3-activation:start -->
## Phase 3 — Default activation and rollback

- Status: `PASSED`
- Verification: `python scripts/verify_ranking_migration.py --phase phase-3-activation`
- Criterion: the deterministic ranking version is the default, the worker dispatches through the versioned service, the extraction prompt is registered, and the legacy version remains available only through an explicit environment override.
- Last verified UTC: `2026-08-02T11:09:29+00:00`
- Metrics: `{"default_version":"ranking_v2.0.0-nvidia-facts","fact_prompt":"v1","rollback_version":"ranking_v1.1.0-nvidia","worker_dispatch":"service"}`
<!-- phase:phase-3-activation:end -->

## Rollback constraint

The deterministic facts version is the default. The legacy ranking path and its prompt remain available only as an explicit rollback and before/after baseline by setting `NVIDIA_RANKING_VERSION=ranking_v1.1.0-nvidia`. Physical deletion is deferred until the rollback window closes; no new case-specific rule may be added to it.
