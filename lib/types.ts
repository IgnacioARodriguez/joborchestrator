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
  technical_fit?: number
  seniority_fit?: number
  role_fit: number
  opportunity_quality?: number
  application_roi?: number
  market_alignment?: number
  risk_penalty?: number
  speed_signal?: number
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

export interface JobPosting {
  id: string
  title: string
  company: string
  location: string
  remote: boolean
  source: JobSource
  source_raw?: string
  url: string
  apply_url: string
  description_text: string
  first_seen_at: string
  last_seen_at: string
  status: JobStatus
  pipeline_status: PipelineStatus
  ranking: JobRanking
  materials: ApplicationMaterials
}

export interface JobsMeta {
  total: number
  returned: number
  limited: boolean
  db_mode: "sqlite" | "turso" | string
}

export interface JobsResponse {
  jobs: JobPosting[]
  ranking_versions: string[]
  selected_ranking_version?: string | null
  meta?: JobsMeta
}

export interface CompanySource {
  id: number
  provider: string
  company_name: string
  company_ref: string
  enabled: number | boolean
  last_scan_at?: string | null
  last_scan_status?: string | null
  last_scan_error?: string | null
}

export interface ScanResult {
  source_type: string
  company_name: string
  company_ref: string
  found_count: number
  new_count: number
  updated_count: number
  unchanged_count: number
  errors: string[]
  duration_seconds: number
}

export interface LinkedInProfileSetting {
  current: string
  profiles: string[]
  profile_dir: string
}

export interface RankingJobRecord {
  id: number
  provider: string
  model: string
  ranking_version: string
  status: string
  total_items: number
  processed_items: number
  saved_items: number
  failed_items: number
  queued_items?: number
  running_items?: number
  completed_items?: number
  failed_item_count?: number
  cancelled_items?: number
  created_at: string
  updated_at: string
  error?: string | null
  latest_item_error?: string | null
}

export type SkillLevel = "strong" | "medium" | "weak"

export interface ProfileSkill {
  name: string
  category: string
  level: SkillLevel
  evidence: string
}

export interface SkillCatalogItem {
  id: number
  category: string
  name: string
  sort_order: number
}

export type WorkMode = "onsite" | "hybrid" | "remote"

export interface ApplicationTarget {
  label: string
  location: string
  work_modes: WorkMode[]
}

export interface CandidateProfile {
  schema_version: number
  headline: string
  target_roles: string[]
  secondary_roles: string[]
  role_aliases: Record<string, string[]>
  skills: ProfileSkill[]
  industries: string[]
  preferred_locations: string[]
  preferred_work_modes: string[]
  application_targets: ApplicationTarget[]
  dealbreakers: string[]
  avoid_roles: string[]
  real_experience_years: number
  notes: string
  suggested_roles_reasoning: string
  base_cv_text?: string
  base_cv_filename?: string
}

export type OperationStatus = "queued" | "running" | "completed" | "failed" | "cancelled"

export interface OperationRun {
  id: number
  type: string
  status: OperationStatus
  progress_message?: string | null
  input_json?: Record<string, unknown> | null
  output_json?: Record<string, unknown> | null
  error?: string | null
  attempts: number
  claimed_by?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at: string
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
