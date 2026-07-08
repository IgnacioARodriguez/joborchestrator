import type {
  CompanySource,
  JobPosting,
  PipelineStatus,
  RankingJobRecord,
  ScanResult,
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
  async getJobs() {
    return request<{ jobs: JobPosting[]; ranking_versions: string[] }>("/api/jobs")
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

  async generateMaterials(id: string, useLlm = false) {
    return request<{ job: JobPosting }>(`/api/jobs/${id}/materials`, {
      method: "POST",
      body: JSON.stringify({ use_llm: useLlm, shortlist: true }),
    })
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
    location: string
    remote: boolean
    max_pages: number
  }) {
    return request<{ results: ScanResult[] }>("/api/scans/search", {
      method: "POST",
      body: JSON.stringify(input),
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

  async runRankingJobOnce(id: number) {
    return request<{ processed: boolean }>(`/api/ranking/jobs/${id}/run-once`, {
      method: "POST",
      body: JSON.stringify({}),
    })
  },
}
