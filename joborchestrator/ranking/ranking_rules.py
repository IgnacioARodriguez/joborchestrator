from __future__ import annotations

RANKING_GOAL = (
    "Prioritize jobs where the candidate has the highest probability of getting hired quickly. "
    "This is not a salary, prestige or dream-job ranking."
)

RANKING_RULES = [
    "Evaluate each job independently; do not compare jobs against each other.",
    "Use raw job text and structured job metadata as source of truth; do not invent candidate skills or job requirements.",
    "Central mandatory requirements dominate the score.",
    "Generic matches such as Git, Agile, cloud, testing or communication cannot rescue a job whose main stack/domain is outside the profile.",
    "Adjacent, translated or industry-specific role labels are viable when the job text supports transfer from the candidate profile.",
    "Treat role_aliases as equivalent labels for the same user-defined role; do not treat aliases as extra skills.",
    "Separate missing requirements from unstated requirements; do not penalize or reward facts absent from the job text.",
    "The model must decide how dealbreakers, relocation, visa constraints, unpaid roles, commission-only roles, technical_fit, seniority_fit and role_fit affect the final score.",
]

NVIDIA_EXTRA_RULES = [
    "Return one result for every input job_id.",
    "Return only valid JSON. No markdown.",
]

OPENAI_INSTRUCTIONS = {
    "goal": "Improve the ranking by reading nuanced job context while preserving explainability.",
    "ranking_goal": RANKING_GOAL,
    "rules": RANKING_RULES,
    "safety": "Do not invent candidate skills. Mark uncertain or adjacent skills as partial matches.",
}

OPENAI_BATCH_INSTRUCTIONS = {
    "evaluate_from_raw_job_text": True,
    "do_not_use_heuristic_as_truth": True,
    "ranking_goal": RANKING_GOAL,
    "rules": RANKING_RULES,
    "hard_overrides": "Unpaid, commission-only and critical dealbreakers cap the job at AVOID/SKIP.",
    "return_only_json": True,
}

SCORING_RUBRIC = {
    "technical_fit": "Truthful fit against mandatory and central requirements.",
    "seniority_fit": "Declared seniority and years of experience alignment.",
    "role_fit": "Fit against target roles, secondary roles, and role_aliases.",
    "application_roi": "Priority for fast interview/hire, considering profile fit and application effort.",
    "risk_penalty": "Penalty for dealbreakers, unsupported claims, domain mismatch, and unclear job data.",
}
