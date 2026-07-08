// Core domain types for Job Orchestrator.
// Structured to map cleanly onto Supabase tables later.

export type JobSource = "LinkedIn" | "Greenhouse" | "Lever" | "Ashby" | "API"

export type Decision =
  | "APPLY_NOW"
  | "APPLY_WITH_TAILORED_CV"
  | "MAYBE"
  | "SKIP"
  | "AVOID"

export type PipelineStatus =
  | "new"
  | "shortlisted"
  | "applied"
  | "discarded"
  | "opened"

export type JobStatus = "active" | "expired" | "filled"

export interface RankingScores {
  role_fit: number
  requirement_coverage: number
  seniority_match: number
  location_fit: number
  compensation: number
}

export interface RankingEvidence {
  strong_matches: string[]
  partial_matches: string[]
  missing_requirements: string[]
  red_flags: string[]
  central_requirements: string[]
}

export interface JobRanking {
  final_score: number // 0-100
  decision: Decision
  confidence: number // 0-1
  scores: RankingScores
  evidence: RankingEvidence
  reasoning_summary: string
  recommended_application_angle: string
  ranking_version: string
}

export interface ApplicationMaterials {
  recruiter_message: string
  cover_letter: string
  ats_cv_notes: string
  autofill_notes: string
}

export interface ManualReview {
  requires_llm_review: boolean
  review_reason: string
  prompt: string
  pasted_chatgpt_json: string | null
  applied_at: string | null
}

export interface JobPosting {
  id: string
  title: string
  company: string
  location: string
  remote: boolean
  source: JobSource
  url: string
  apply_url: string
  description_text: string
  first_seen_at: string
  last_seen_at: string
  status: JobStatus
  pipeline_status: PipelineStatus
  ranking: JobRanking
  review: ManualReview
  materials: ApplicationMaterials
}

export interface ImportRecord {
  id: string
  file_name: string
  imported_at: string
  rows_detected: number
  inserted: number
  updated: number
  duplicates: number
  errors: number
}

export const DECISION_ORDER: Decision[] = [
  "APPLY_NOW",
  "APPLY_WITH_TAILORED_CV",
  "MAYBE",
  "SKIP",
  "AVOID",
]

export const DECISION_LABELS: Record<Decision, string> = {
  APPLY_NOW: "Apply Now",
  APPLY_WITH_TAILORED_CV: "Tailor CV",
  MAYBE: "Maybe",
  SKIP: "Skip",
  AVOID: "Avoid",
}
