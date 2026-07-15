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
  OpsStatus,
  WorkerStatus,
  AutomationAccount,
  PipelineStatus,
  RankingJobRecord,
  ScanResult,
  DuplicateRateSummary,
  SkillCatalogItem,
  ApplicationSession,
  ApplicationSessionResponse,
} from "./types"

const API_BASE =
  process.env.NEXT_PUBLIC_JOB_API_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000")

type ApiRequestInit = RequestInit & {
  fresh?: boolean
}

async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData
  const method = init?.method ?? "GET"
  const fresh = Boolean(init?.fresh)
  const url =
    method === "GET" && fresh
      ? `${API_BASE}${path}${path.includes("?") ? "&" : "?"}_=${Date.now()}`
      : `${API_BASE}${path}`
  const { fresh: _fresh, ...fetchInit } = init ?? {}
  const res = await fetch(url, {
    ...fetchInit,
    ...(fresh ? { cache: "no-store" as RequestCache } : {}),
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(fresh ? { "Cache-Control": "no-store", Pragma: "no-cache" } : {}),
      ...(init?.headers ?? {}),
    },
    ...(method === "GET" ? { method: "GET" } : {}),
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
  async getJobs(rankingVersion?: string | null, limit = 100) {
    const params = new URLSearchParams()
    params.set("limit", String(limit))
    if (rankingVersion) {
      params.set("ranking_version", rankingVersion)
    }
    const query = `?${params.toString()}`
    return request<JobsResponse>(`/api/jobs${query}`)
  },

  async getApplyQueue(rankingVersion?: string | null, limit = 50, offset = 0, freshness = "active") {
    const params = new URLSearchParams()
    params.set("limit", String(limit))
    params.set("offset", String(offset))
    params.set("freshness", freshness)
    if (rankingVersion) {
      params.set("ranking_version", rankingVersion)
    }
    return request<JobsResponse>(`/api/apply-queue?${params.toString()}`, { fresh: true })
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
    return request<{ operation: OperationRun }>(`/api/operations/${id}`, { fresh: true })
  },

  async getLatestOperation(type?: string) {
    const query = type ? `?type=${encodeURIComponent(type)}` : ""
    return request<{ operation: OperationRun | null }>(`/api/operations/latest${query}`, { fresh: true })
  },

  async getOperations(limit = 10) {
    return request<{ operations: OperationRun[] }>(`/api/operations?limit=${limit}`, { fresh: true })
  },

  async getWorkerStatus() {
    return request<WorkerStatus>("/api/workers/status", { fresh: true })
  },

  async getOpsStatus() {
    return request<OpsStatus>("/api/ops/status", { fresh: true })
  },

  async getAutomationAccounts() {
    return request<{ accounts: AutomationAccount[] }>("/api/automation/accounts", { fresh: true })
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

  async getApplicationSessions(jobId?: string) {
    const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""
    return request<{ sessions: ApplicationSession[] }>(`/api/application-sessions${query}`, { fresh: true })
  },

  async createApplicationSession(
    jobId: string,
    input: {
      provider?: string
      mode?: "assisted" | "review_before_submit" | "auto_submit_approved"
      html?: string
      dry_run?: boolean
    },
  ) {
    return request<ApplicationSessionResponse>(`/api/jobs/${jobId}/application-sessions`, {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async transitionApplicationSession(id: number, state: string, payload: Record<string, unknown> = {}) {
    return request<{ session: ApplicationSession }>(`/api/application-sessions/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ state, payload }),
    })
  },

  async continueApplicationSession(id: number) {
    return request<ApplicationSessionResponse>(`/api/application-sessions/${id}/continue`, {
      method: "POST",
      body: JSON.stringify({}),
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
    auto_rank_new?: boolean
    ranking_limit?: number
    linkedin_limit?: number
    linkedin_resume_from_checkpoint?: boolean
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
      already_running?: boolean
      progress_message?: string | null
    }>("/api/scans/all", {
      method: "POST",
      body: JSON.stringify(input),
    })
  },

  async scanFresh() {
    return request<{
      operation_id: number
      status: string
      already_running?: boolean
      progress_message?: string | null
    }>("/api/scans/fresh", {
      method: "POST",
      body: JSON.stringify({}),
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
    return request<{ jobs: RankingJobRecord[] }>("/api/ranking/jobs", { fresh: true })
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
