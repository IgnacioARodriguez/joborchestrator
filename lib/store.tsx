"use client"

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import type {
  ApplyQueuePipeline,
  ApplicationRecord,
  ApplicationStatus,
  JobDetail,
  JobListItem,
  JobsMeta,
  PipelineStatus,
} from "./types"
import { api } from "./api"

type ApplyQueueFreshness = "active" | "all" | "stale"
type JobsPipelineFilter = Exclude<ApplyQueuePipeline, "apply">
type ResourceStatus = "idle" | "loading" | "refreshing" | "success" | "empty" | "error"
type JobsSnapshot = Awaited<ReturnType<typeof api.getApplyQueue>>

interface PendingJobChanges {
  added: number
  updated: number
  removed: number
}

interface PendingJobsSnapshot {
  data: JobsSnapshot
  changes: PendingJobChanges
}

interface JobDetailEntry {
  status: ResourceStatus
  job?: JobDetail
  error?: string
  requestedAt?: number
}

interface StoreValue {
  jobs: JobListItem[]
  preparationJobs: JobListItem[]
  applications: ApplicationRecord[]
  loading: boolean
  preparationLoading: boolean
  jobsStatus: ResourceStatus
  preparationJobsStatus: ResourceStatus
  applicationsStatus: ResourceStatus
  backendOnline: boolean
  applyQueuePage: number
  applyQueuePageSize: number
  applyQueueFreshness: ApplyQueueFreshness
  applyQueueQuery: string
  jobsMeta: JobsMeta | null
  jobsPipelineFilter: JobsPipelineFilter
  preparationQueuePage: number
  preparationJobsMeta: JobsMeta | null
  rankingVersions: string[]
  selectedRankingVersion: string | null
  pendingJobChanges: PendingJobChanges | null
  setApplyQueuePage: (page: number) => void
  setApplyQueueFreshness: (freshness: ApplyQueueFreshness) => void
  setApplyQueueQuery: (query: string) => void
  setJobsPipelineFilter: (filter: JobsPipelineFilter) => void
  setPreparationQueuePage: (page: number) => void
  setSelectedRankingVersion: (version: string) => void
  refresh: (rankingVersion?: string | null) => Promise<void>
  stageJobUpdates: (rankingVersion?: string | null) => Promise<PendingJobChanges | null>
  applyPendingJobChanges: () => void
  refreshPreparationQueue: (rankingVersion?: string | null) => Promise<void>
  refreshApplications: () => Promise<void>
  recordApplication: (application: ApplicationRecord) => void
  getJob: (id: string) => JobDetail | undefined
  getJobSummary: (id: string) => JobListItem | undefined
  getJobDetailEntry: (id: string) => JobDetailEntry
  loadJobDetail: (id: string, options?: { force?: boolean }) => Promise<JobDetail | undefined>
  setPipelineStatus: (id: string, status: PipelineStatus) => Promise<boolean>
  setApplicationStatus: (id: number, status: ApplicationStatus, note?: string) => Promise<boolean>
  markOpened: (id: string) => void
  generateMaterials: (
    id: string,
    provider?: "heuristic" | "openai" | "nvidia",
    targets?: Array<"ats_cv" | "cover_letter" | "recruiter_message" | "autofill">,
  ) => Promise<{ job?: JobDetail; operation_id?: number; status?: string }>
}

const StoreContext = createContext<StoreValue | null>(null)
const APPLY_QUEUE_PAGE_SIZE = 50
const DETAIL_CACHE_LIMIT = 25
const DETAIL_CACHE_TTL_MS = 5 * 60 * 1000
const SUBMITTED_APPLICATION_STATUSES = new Set<ApplicationStatus>([
  "submitted",
  "submitted_manually",
  "submission_verified",
])

function isSubmittedApplication(status: ApplicationStatus) {
  return SUBMITTED_APPLICATION_STATUSES.has(status)
}

function withoutJobId(jobs: JobListItem[], jobId: string) {
  return jobs.filter((job) => String(job.id) !== jobId)
}

function decrementJobsMetaTotal(current: JobsMeta | null) {
  return current ? { ...current, total: Math.max(0, current.total - 1) } : current
}

function getPendingJobChanges(
  currentJobs: JobListItem[],
  currentMeta: JobsMeta | null,
  next: JobsSnapshot,
): PendingJobChanges {
  const currentById = new Map(currentJobs.map((job) => [job.id, job]))
  const nextById = new Map(next.jobs.map((job) => [job.id, job]))
  const added = next.jobs.filter((job) => !currentById.has(job.id)).length
  const removed = currentJobs.filter((job) => !nextById.has(job.id)).length
  let updated = next.jobs.filter((job) => {
    const current = currentById.get(job.id)
    return current ? JSON.stringify(current) !== JSON.stringify(job) : false
  }).length

  const rowsChanged = added + updated + removed > 0
  const metadataChanged = JSON.stringify(currentMeta) !== JSON.stringify(next.meta ?? null)
  if (!rowsChanged && metadataChanged) updated = 1

  return { added, updated, removed }
}

function hasPendingJobChanges(changes: PendingJobChanges) {
  return changes.added + changes.updated + changes.removed > 0
}

function upsertDetail(current: Record<string, JobDetailEntry>, id: string, entry: JobDetailEntry) {
  const next = { ...current, [id]: entry }
  const cached = Object.entries(next)
    .filter(([, value]) => value.job)
    .sort(([, a], [, b]) => (b.requestedAt ?? 0) - (a.requestedAt ?? 0))
  for (const [evictId] of cached.slice(DETAIL_CACHE_LIMIT)) {
    delete next[evictId]
  }
  return next
}

function mergeDetailIntoSummary(summary: JobListItem, detail: JobDetail): JobListItem {
  return {
    ...summary,
    title: detail.title,
    company: detail.company,
    location: detail.location,
    remote: detail.remote,
    source: detail.source,
    source_raw: detail.source_raw,
    apply_type: detail.apply_type,
    first_seen_at: detail.first_seen_at,
    last_seen_at: detail.last_seen_at,
    status: detail.status,
    pipeline_status: detail.pipeline_status,
    ranking: {
      final_score: detail.ranking.final_score,
      decision: detail.ranking.decision,
      confidence: detail.ranking.confidence,
      evidence: {
        strong_matches: detail.ranking.evidence.strong_matches.slice(0, 3),
        missing_requirements: detail.ranking.evidence.missing_requirements.slice(0, 2),
        requires_llm_review: detail.ranking.evidence.requires_llm_review,
        llm_escalation_reasons: detail.ranking.evidence.llm_escalation_reasons.slice(0, 3),
        red_flags: detail.ranking.evidence.red_flags.slice(0, 3),
      },
      reasoning_summary: detail.ranking.reasoning_summary.slice(0, 280),
      ranking_version: detail.ranking.ranking_version,
      review: detail.ranking.review,
    },
    priority: {
      priority_score: detail.priority.priority_score,
      fit_score: detail.priority.fit_score,
      eligibility_score: detail.priority.eligibility_score,
      freshness_score: detail.priority.freshness_score,
      freshness_bucket: detail.priority.freshness_bucket,
      freshness_age_days: detail.priority.freshness_age_days,
      application_effort_score: detail.priority.application_effort_score,
      recruiter_advantage_score: detail.priority.recruiter_advantage_score,
      estimated_minutes: detail.priority.estimated_minutes,
      next_action: detail.priority.next_action,
      blocker: detail.priority.blocker,
    },
    has_materials: Boolean(
      detail.materials.recruiter_message ||
        detail.materials.cover_letter ||
        detail.materials.ats_cv_notes ||
        detail.materials.autofill_notes,
    ),
    materials_review: detail.materials.review,
    has_recruiter_contact: Boolean(detail.recruiter_name || detail.recruiter_profile_url || detail.hiring_contacts_count),
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobListItem[]>([])
  const [preparationJobs, setPreparationJobs] = useState<JobListItem[]>([])
  const [applications, setApplications] = useState<ApplicationRecord[]>([])
  const [jobsStatus, setJobsStatus] = useState<ResourceStatus>("idle")
  const [preparationJobsStatus, setPreparationJobsStatus] = useState<ResourceStatus>("idle")
  const [applicationsStatus, setApplicationsStatus] = useState<ResourceStatus>("idle")
  const [backendOnline, setBackendOnline] = useState(false)
  const [applyQueuePage, setApplyQueuePageState] = useState(1)
  const [applyQueueFreshness, setApplyQueueFreshnessState] = useState<ApplyQueueFreshness>("active")
  const [applyQueueQuery, setApplyQueueQueryState] = useState("")
  const [jobsMeta, setJobsMeta] = useState<JobsMeta | null>(null)
  const [jobsPipelineFilter, setJobsPipelineFilterState] = useState<JobsPipelineFilter>("all")
  const [preparationQueuePage, setPreparationQueuePageState] = useState(1)
  const [preparationJobsMeta, setPreparationJobsMeta] = useState<JobsMeta | null>(null)
  const [rankingVersions, setRankingVersions] = useState<string[]>([])
  const [selectedRankingVersion, setSelectedRankingVersionState] = useState<string | null>(null)
  const [jobDetails, setJobDetails] = useState<Record<string, JobDetailEntry>>({})
  const [pendingJobsSnapshot, setPendingJobsSnapshot] = useState<PendingJobsSnapshot | null>(null)
  const selectedRankingVersionRef = useRef<string | null>(null)
  const applyQueuePageRef = useRef(1)
  const applyQueueFreshnessRef = useRef<ApplyQueueFreshness>("active")
  const applyQueueQueryRef = useRef("")
  const jobsPipelineFilterRef = useRef<JobsPipelineFilter>("all")
  const preparationQueuePageRef = useRef(1)
  const listRequestSeq = useRef(0)
  const preparationRequestSeq = useRef(0)
  const applicationRequestSeq = useRef(0)
  const submittedJobIdsRef = useRef(new Set<string>())
  const detailRequests = useRef(new Map<string, Promise<JobDetail | undefined>>())

  const loadJobsSnapshot = useCallback((rankingVersion?: string | null) => {
    const version = rankingVersion === undefined ? selectedRankingVersionRef.current : rankingVersion
    const offset = (applyQueuePageRef.current - 1) * APPLY_QUEUE_PAGE_SIZE
    return api.getApplyQueue(
      version,
      APPLY_QUEUE_PAGE_SIZE,
      offset,
      applyQueueFreshnessRef.current,
      applyQueueQueryRef.current,
      jobsPipelineFilterRef.current,
    )
  }, [])

  const applyJobsSnapshot = useCallback((data: JobsSnapshot) => {
    const nextRankingVersion = data.selected_ranking_version ?? data.ranking_versions[0] ?? null
    setJobs(data.jobs)
    setRankingVersions(data.ranking_versions)
    selectedRankingVersionRef.current = nextRankingVersion
    setSelectedRankingVersionState(nextRankingVersion)
    setJobsMeta(data.meta ?? null)
    setJobsStatus(data.jobs.length ? "success" : "empty")
    setPendingJobsSnapshot(null)
    setBackendOnline(true)
  }, [])

  const refresh = useCallback(
    async (rankingVersion?: string | null) => {
      const requestId = ++listRequestSeq.current
      setPendingJobsSnapshot(null)
      setJobsStatus((current) =>
        current === "success" || current === "empty" ? "refreshing" : "loading",
      )
      try {
        const data = await loadJobsSnapshot(rankingVersion)
        if (requestId !== listRequestSeq.current) return
        applyJobsSnapshot(data)
      } catch {
        if (requestId === listRequestSeq.current) {
          setBackendOnline(false)
          setJobsStatus("error")
        }
      }
    },
    [applyJobsSnapshot, loadJobsSnapshot],
  )

  const stageJobUpdates = useCallback(
    async (rankingVersion?: string | null) => {
      const requestId = ++listRequestSeq.current
      try {
        const data = await loadJobsSnapshot(rankingVersion)
        if (requestId !== listRequestSeq.current) return { added: 0, updated: 0, removed: 0 }
        const changes = getPendingJobChanges(jobs, jobsMeta, data)
        setPendingJobsSnapshot(hasPendingJobChanges(changes) ? { data, changes } : null)
        setBackendOnline(true)
        return changes
      } catch {
        if (requestId === listRequestSeq.current) setBackendOnline(false)
        return null
      }
    },
    [jobs, jobsMeta, loadJobsSnapshot],
  )

  const applyPendingJobChanges = useCallback(() => {
    if (!pendingJobsSnapshot) return
    listRequestSeq.current += 1
    applyJobsSnapshot(pendingJobsSnapshot.data)
  }, [applyJobsSnapshot, pendingJobsSnapshot])

  const refreshPreparationQueue = useCallback(async (rankingVersion?: string | null) => {
    const requestId = ++preparationRequestSeq.current
    setPreparationJobsStatus((current) =>
      current === "success" || current === "empty" ? "refreshing" : "loading",
    )
    try {
      const version = rankingVersion === undefined ? selectedRankingVersionRef.current : rankingVersion
      const offset = (preparationQueuePageRef.current - 1) * APPLY_QUEUE_PAGE_SIZE
      const data = await api.getApplyQueue(
        version,
        APPLY_QUEUE_PAGE_SIZE,
        offset,
        "active",
        undefined,
        "apply",
        false,
      )
      if (requestId !== preparationRequestSeq.current) return
      setPreparationJobs(data.jobs)
      setPreparationJobsMeta(data.meta ?? null)
      setPreparationJobsStatus(data.jobs.length ? "success" : "empty")
      setRankingVersions(data.ranking_versions)
      const nextRankingVersion = data.selected_ranking_version ?? data.ranking_versions[0] ?? null
      selectedRankingVersionRef.current = nextRankingVersion
      setSelectedRankingVersionState(nextRankingVersion)
      setBackendOnline(true)
    } catch {
      if (requestId === preparationRequestSeq.current) {
        setBackendOnline(false)
        setPreparationJobsStatus("error")
      }
    }
  }, [])

  const refreshApplications = useCallback(async () => {
    const requestId = ++applicationRequestSeq.current
    setApplicationsStatus((current) => (current === "success" || current === "empty" ? "refreshing" : "loading"))
    try {
      const data = await api.getApplications()
      if (requestId !== applicationRequestSeq.current) return
      setApplications(data.applications)
      submittedJobIdsRef.current = new Set(
        data.applications
          .filter((application) => isSubmittedApplication(application.status))
          .map((application) => String(application.job_id)),
      )
      setApplicationsStatus(data.applications.length ? "success" : "empty")
      setBackendOnline(true)
    } catch {
      if (requestId === applicationRequestSeq.current) {
        setBackendOnline(false)
        setApplicationsStatus("error")
      }
    }
  }, [])

  const recordApplication = useCallback((application: ApplicationRecord) => {
    setApplications((current) => [application, ...current.filter((item) => item.id !== application.id)])
    if (!isSubmittedApplication(application.status)) return

    setPendingJobsSnapshot(null)
    const jobId = String(application.job_id)
    const alreadySubmitted = submittedJobIdsRef.current.has(jobId)
    submittedJobIdsRef.current.add(jobId)
    setJobs((current) => withoutJobId(current, jobId))
    setPreparationJobs((current) => withoutJobId(current, jobId))
    if (!alreadySubmitted) {
      setJobsMeta(decrementJobsMetaTotal)
      setPreparationJobsMeta(decrementJobsMetaTotal)
    }
  }, [])


  const setSelectedRankingVersion = useCallback((version: string) => {
    selectedRankingVersionRef.current = version
    applyQueuePageRef.current = 1
    preparationQueuePageRef.current = 1
    setApplyQueuePageState(1)
    setPreparationQueuePageState(1)
    setSelectedRankingVersionState(version)
    setJobDetails({})
    detailRequests.current.clear()
    void refresh(version)
    void refreshPreparationQueue(version)
  }, [refresh, refreshPreparationQueue])

  const setApplyQueuePage = useCallback((page: number) => {
    const next = Math.max(1, page)
    applyQueuePageRef.current = next
    setApplyQueuePageState(next)
    void refresh()
  }, [refresh])

  const setApplyQueueFreshness = useCallback((freshness: ApplyQueueFreshness) => {
    applyQueueFreshnessRef.current = freshness
    applyQueuePageRef.current = 1
    setApplyQueueFreshnessState(freshness)
    setApplyQueuePageState(1)
    void refresh()
  }, [refresh])

  const setApplyQueueQuery = useCallback((query: string) => {
    applyQueueQueryRef.current = query
    applyQueuePageRef.current = 1
    setApplyQueueQueryState(query)
    setApplyQueuePageState(1)
    void refresh()
  }, [refresh])

  const setJobsPipelineFilter = useCallback((filter: JobsPipelineFilter) => {
    jobsPipelineFilterRef.current = filter
    applyQueuePageRef.current = 1
    setJobsPipelineFilterState(filter)
    setApplyQueuePageState(1)
    void refresh()
  }, [refresh])

  const setPreparationQueuePage = useCallback((page: number) => {
    const next = Math.max(1, page)
    preparationQueuePageRef.current = next
    setPreparationQueuePageState(next)
    void refreshPreparationQueue()
  }, [refreshPreparationQueue])

  const getJob = useCallback((id: string) => jobDetails[id]?.job, [jobDetails])

  const getJobSummary = useCallback(
    (id: string) => jobs.find((job) => job.id === id) ?? preparationJobs.find((job) => job.id === id),
    [jobs, preparationJobs],
  )

  const getJobDetailEntry = useCallback(
    (id: string) => jobDetails[id] ?? { status: "idle" },
    [jobDetails],
  )

  const loadJobDetail = useCallback(async (id: string, options?: { force?: boolean }) => {
    const cached = jobDetails[id]
    const isFresh = cached?.job && cached.requestedAt && Date.now() - cached.requestedAt < DETAIL_CACHE_TTL_MS
    if (!options?.force && isFresh) return cached.job

    const existing = detailRequests.current.get(id)
    if (!options?.force && existing) return existing

    setJobDetails((current) => upsertDetail(current, id, { ...current[id], status: "loading", error: undefined }))
    const request = api
      .getJob(id, selectedRankingVersionRef.current)
      .then((response) => {
        const entry = { status: "success" as const, job: response.job, requestedAt: Date.now() }
        setJobDetails((current) => upsertDetail(current, id, entry))
        setJobs((current) => current.map((job) => (job.id === id ? mergeDetailIntoSummary(job, response.job) : job)))
        setPreparationJobs((current) =>
          current.map((job) => (job.id === id ? mergeDetailIntoSummary(job, response.job) : job)),
        )
        setBackendOnline(true)
        return response.job
      })
      .catch((error) => {
        setBackendOnline(false)
        setJobDetails((current) =>
          upsertDetail(current, id, {
            ...current[id],
            status: "error",
            error: error instanceof Error ? error.message : "Could not load job detail.",
          }),
        )
        return undefined
      })
      .finally(() => {
        detailRequests.current.delete(id)
      })
    detailRequests.current.set(id, request)
    return request
  }, [jobDetails])

  const setPipelineStatus = useCallback(async (id: string, status: PipelineStatus) => {
    setPendingJobsSnapshot(null)
    const previousStatus =
      jobs.find((job) => job.id === id)?.pipeline_status ??
      preparationJobs.find((job) => job.id === id)?.pipeline_status
    setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, pipeline_status: status } : job)))
    setPreparationJobs((prev) => prev.map((job) => (job.id === id ? { ...job, pipeline_status: status } : job)))
    setJobDetails((prev) => {
      const entry = prev[id]
      if (!entry?.job) return prev
      return upsertDetail(prev, id, { ...entry, job: { ...entry.job, pipeline_status: status } })
    })
    try {
      await api.setPipelineStatus(id, status)
      setBackendOnline(true)
      void refresh()
      void refreshPreparationQueue()
      return true
    } catch {
      setBackendOnline(false)
      if (previousStatus) {
        setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, pipeline_status: previousStatus } : job)))
        setPreparationJobs((prev) =>
          prev.map((job) => (job.id === id ? { ...job, pipeline_status: previousStatus } : job)),
        )
      }
      setJobDetails((prev) => {
        const entry = prev[id]
        if (!entry?.job || !previousStatus) return upsertDetail(prev, id, { ...entry, status: "idle" })
        return upsertDetail(prev, id, { ...entry, status: "idle", job: { ...entry.job, pipeline_status: previousStatus } })
      })
      return false
    }
  }, [jobs, preparationJobs, refresh, refreshPreparationQueue])

  const setApplicationStatus = useCallback(async (id: number, status: ApplicationStatus, note?: string) => {
    try {
      const response = await api.patchApplication(id, { status, note })
      recordApplication(response.application)
      setBackendOnline(true)
      return true
    } catch {
      setBackendOnline(false)
      return false
    }
  }, [recordApplication])

  const markOpened = useCallback((id: string) => {
    const lastSeen = new Date().toISOString()
    setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, last_seen_at: lastSeen } : job)))
    setPreparationJobs((prev) => prev.map((job) => (job.id === id ? { ...job, last_seen_at: lastSeen } : job)))
    setJobDetails((prev) => {
      const entry = prev[id]
      if (!entry?.job) return prev
      return upsertDetail(prev, id, { ...entry, job: { ...entry.job, last_seen_at: lastSeen } })
    })
    void api.markOpened(id).catch(() => {
      setBackendOnline(false)
    })
  }, [])

  const generateMaterials = useCallback(async (
    id: string,
    provider: "heuristic" | "openai" | "nvidia" = "openai",
    targets?: Array<"ats_cv" | "cover_letter" | "recruiter_message" | "autofill">,
  ) => {
    const result = await api.generateMaterials(id, provider, targets)
    setBackendOnline(true)
    if (result.job) {
      const entry = { status: "success" as const, job: result.job, requestedAt: Date.now() }
      setJobDetails((prev) => upsertDetail(prev, id, entry))
      setJobs((prev) => prev.map((job) => (job.id === id ? mergeDetailIntoSummary(job, result.job!) : job)))
      setPreparationJobs((prev) =>
        prev.map((job) => (job.id === id ? mergeDetailIntoSummary(job, result.job!) : job)),
      )
    } else {
      setJobDetails((prev) => upsertDetail(prev, id, { ...prev[id], status: "idle" }))
    }
    return result
  }, [])

  const value = useMemo(
    () => ({
      jobs,
      preparationJobs,
      applications,
      loading: jobsStatus === "loading",
      preparationLoading: preparationJobsStatus === "loading",
      jobsStatus,
      preparationJobsStatus,
      applicationsStatus,
      backendOnline,
      applyQueuePage,
      applyQueuePageSize: APPLY_QUEUE_PAGE_SIZE,
      applyQueueFreshness,
      applyQueueQuery,
      jobsMeta,
      jobsPipelineFilter,
      preparationQueuePage,
      preparationJobsMeta,
      rankingVersions,
      selectedRankingVersion,
      pendingJobChanges: pendingJobsSnapshot?.changes ?? null,
      setApplyQueuePage,
      setApplyQueueFreshness,
      setApplyQueueQuery,
      setJobsPipelineFilter,
      setPreparationQueuePage,
      setSelectedRankingVersion,
      refresh,
      stageJobUpdates,
      applyPendingJobChanges,
      refreshPreparationQueue,
      refreshApplications,
      recordApplication,
      getJob,
      getJobSummary,
      getJobDetailEntry,
      loadJobDetail,
      setPipelineStatus,
      setApplicationStatus,
      markOpened,
      generateMaterials,
    }),
    [
      jobs,
      preparationJobs,
      applications,
      jobsStatus,
      preparationJobsStatus,
      applicationsStatus,
      backendOnline,
      applyQueuePage,
      applyQueueFreshness,
      applyQueueQuery,
      jobsMeta,
      jobsPipelineFilter,
      preparationQueuePage,
      preparationJobsMeta,
      rankingVersions,
      selectedRankingVersion,
      pendingJobsSnapshot,
      setApplyQueuePage,
      setApplyQueueFreshness,
      setApplyQueueQuery,
      setJobsPipelineFilter,
      setPreparationQueuePage,
      setSelectedRankingVersion,
      refresh,
      stageJobUpdates,
      applyPendingJobChanges,
      refreshPreparationQueue,
      refreshApplications,
      recordApplication,
      getJob,
      getJobSummary,
      getJobDetailEntry,
      loadJobDetail,
      setPipelineStatus,
      setApplicationStatus,
      markOpened,
      generateMaterials,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore() {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error("useStore must be used within StoreProvider")
  return ctx
}
