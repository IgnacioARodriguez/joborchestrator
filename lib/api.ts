import type {
  CompanySource,
  CandidateProfile,
  ApplicationRecord,
  ApplicationStatus,
  AnswerDefinition,
  ResumeVariant,
  JobContact,
  FollowUp,
  JobPosting,
  JobsResponse,
  LinkedInProfileSetting,
  OperationRun,
  PipelineStatus,
  RankingJobRecord,
  ScanResult,
  DuplicateRateSummary,
  SkillCatalogItem,
} from "./types"

const API_BASE =
  process.env.NEXT_PUBLIC_JOB_API_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000")

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // Keep HTTP status detail.
    }
    throw new Error(String(detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  async getJobs(rankingVersion?: string | null) {
    const query = rankingVersion ? `?ranking_version=${encodeURIComponent(rankingVersion)}` : ""
    return request<JobsResponse>(`/api/jobs${query}`)
  },

  async getProfile() {
    return request<{ profile: CandidateProfile | null }>("/api/profile")
  },

  async saveProfile(profile: CandidateProfile) {
    return request<{ profile: CandidateProfile }>("/api/profile", {
      method: "PUT",
      body: JSON.stringify({ profile }),
    })
  },

  async getSkillCatalog() {
    return request<{ skills: SkillCatalogItem[] }>("/api/profile/skill-catalog")
  },

  async addSkillCatalogItem(input: { category: string; name: string }) {
    return request<{ skill: SkillCatalogItem; skills: SkillCatalogItem[] }>("/api/profile/skill-catalog", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async importProfileCv(file: File) {
    const formData = new FormData()
    formData.append("file", file)
    return request<{ operation_id: number; status: string }>("/api/profile/import-cv", {
      method: "POST",
      body: formData,
    })
  },

  async getOperation(id: number) {
    return request<{ operation: OperationRun }>(`/api/operations/${id}`)
  },

  async getLatestOperation(type?: string) {
    const query = type ? `?type=${encodeURIComponent(type)}` : ""
    return request<{ operation: OperationRun | null }>(`/api/operations/latest${query}`)
  },

  async getOperations(limit = 10) {
    return request<{ operations: OperationRun[] }>(`/api/operations?limit=${limit}`)
  },

  async setPipelineStatus(id: string, status: PipelineStatus) {
    return request<{ ok: boolean }>(`/api/jobs/${id}/pipeline`, {
      method: "POST",
      body: JSON.stringify({ status }),
    })
  },

  async markOpened(id: string) {
    return request<{ ok: boolean }>(`/api/jobs/${id}/opened`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },

  async createJob(input: {
    title: string
    company: string
    url: string
    apply_url?: string
    source?: string
    description_text?: string
  }) {
    return request<{ job: JobPosting }>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async generateMaterials(id: string, provider: "heuristic" | "openai" | "nvidia" = "openai") {
    return request<{ job?: JobPosting; operation_id?: number; status?: string }>(`/api/jobs/${id}/materials`, {
      method: "POST",
      body: JSON.stringify({ provider, use_llm: provider !== "heuristic", shortlist: true }),
    })
  },

  materialDownloadUrl(id: string, format: "docx" | "pdf") {
    return `${API_BASE}/api/jobs/${id}/materials/ats-cv.${format}`
  },

  async getSources() {
    return request<{
      sources: CompanySource[]
      providers: string[]
      search_providers: string[]
    }>("/api/sources")
  },

  async addSource(input: {
    provider: string
    company_name: string
    company_ref: string
    enabled: boolean
  }) {
    return request<{ id: number }>("/api/sources", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async scanAts(sourceIds?: number[]) {
    return request<{ results: ScanResult[] }>("/api/scans/ats", {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds }),
    })
  },

  async scanSearch(input: {
    providers: string[]
    queries: string[]
    application_targets?: Array<{ label: string; location: string; work_modes: string[] }>
    location: string
    remote: boolean
    max_pages: number
  }) {
    return request<{ results: ScanResult[]; duplicate_rates: DuplicateRateSummary[] }>("/api/scans/search", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getApplications() {
    return request<{ applications: ApplicationRecord[] }>("/api/applications")
  },

  async getResumes() {
    return request<{ resumes: ResumeVariant[] }>("/api/resumes")
  },

  async createResume(input: Pick<ResumeVariant, "label"> & Partial<ResumeVariant>) {
    return request<{ resume: ResumeVariant }>("/api/resumes", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getAnswers() {
    return request<{ answers: AnswerDefinition[] }>("/api/answers")
  },

  async saveAnswer(input: AnswerDefinition) {
    return request<{ answer: AnswerDefinition }>("/api/answers", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async patchApplication(id: number, input: Partial<{ status: ApplicationStatus }>) {
    return request<{ application: ApplicationRecord }>(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    })
  },

  async previewGmailRules(input: { sender: string; subject: string; body: string }) {
    return request<{
      signal: null | { event_type: string; confidence: number; note: string }
    }>("/api/gmail/rules/preview", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getContacts() {
    return request<{ contacts: JobContact[] }>("/api/contacts")
  },

  async createContact(input: Partial<JobContact>) {
    return request<{ contact: JobContact }>("/api/contacts", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getFollowUps() {
    return request<{ follow_ups: FollowUp[] }>("/api/follow-ups")
  },

  async createFollowUp(input: Pick<FollowUp, "application_id" | "due_at"> & Partial<FollowUp>) {
    return request<{ follow_up: FollowUp }>("/api/follow-ups", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async scanAll(input: {
    include_ats: boolean
    include_search: boolean
    include_linkedin?: boolean
    linkedin_limit?: number
    search_providers: string[]
    queries: string[]
    application_targets?: Array<{ label: string; location: string; work_modes: string[] }>
    location: string
    remote: boolean
    max_pages: number
  }) {
    return request<{
      operation_id: number
      status: string
    }>("/api/scans/all", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getLinkedInProfile() {
    return request<{ linkedin_profile: LinkedInProfileSetting }>("/api/linkedin/profile")
  },

  async setLinkedInProfile(profileName: string) {
    return request<{ linkedin_profile: LinkedInProfileSetting }>("/api/linkedin/profile", {
      method: "PUT",
      body: JSON.stringify({ profile_name: profileName }),
    })
  },

  async importLatestLinkedIn() {
    return request<{
      file: string
      filter_stats: Record<string, number>
      import_stats: Record<string, number>
    }>("/api/linkedin/import-latest", { method: "POST", body: JSON.stringify({}) })
  },

  async importLinkedInExcel(file: File) {
    const formData = new FormData()
    formData.append("file", file)
    return request<{
      file: string
      filter_stats: Record<string, number>
      import_stats: Record<string, number>
    }>("/api/linkedin/import-excel", { method: "POST", body: formData })
  },

  async createRankingJob(input: {
    limit: number
    run_once: boolean
    request_batch_size: number
    max_concurrency: number
  }) {
    return request<{
      ranking_job_id: number | null
      queued: number
      processed_once?: boolean
    }>("/api/ranking/jobs", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async getRankingJobs() {
    return request<{ jobs: RankingJobRecord[] }>("/api/ranking/jobs")
  },

  async cancelRankingJob(id: number) {
    return request<{ job: RankingJobRecord }>(`/api/ranking/jobs/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },

  async requeueFailedRankingItems(id: number) {
    return request<{ requeued: number; job: RankingJobRecord }>(`/api/ranking/jobs/${id}/requeue-failed`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },

  async requeueStaleRankingItems(id: number) {
    return request<{ requeued: number; job: RankingJobRecord }>(`/api/ranking/jobs/${id}/requeue-stale`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },

  async runRankingJobOnce(id: number) {
    return request<{ processed: boolean }>(`/api/ranking/jobs/${id}/run-once`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },
}
