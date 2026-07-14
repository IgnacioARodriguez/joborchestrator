# Ranking And Priority

LLM ranking remains a fit signal, not the final operational score.

`priority_score` is deterministic and explainable. Components:

- `fit_score`
- `eligibility_score`
- `freshness_score`
- `application_effort_score`
- `recruiter_advantage_score`
- `data_quality_score`
- `competition_signal`
- `risk_penalty`

Freshness is computed from `posted_at`, `first_seen_at` or `last_seen_at`.
Recruiter advantage uses hiring contacts, recruiter profile URL and recruiter name.
Effort uses ATS/provider, apply type and existing materials.

The dashboard orders `/api/apply-queue` by `priority.priority_score`, then ranking fit.
