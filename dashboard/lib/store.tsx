"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import type {
  JobPosting,
  JobRanking,
  PipelineStatus,
} from "./types"
import { api } from "./api"

interface StoreValue {
  jobs: JobPosting[]
  loading: boolean
  backendOnline: boolean
  refresh: () => Promise<void>
  getJob: (id: string) => JobPosting | undefined
  setPipelineStatus: (id: string, status: PipelineStatus) => void
  markOpened: (id: string) => void
  applyReview: (id: string, ranking: Partial<JobRanking>) => void
  generateMaterials: (id: string, useLlm?: boolean) => Promise<void>
}

const StoreContext = createContext<StoreValue | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobPosting[]>([])
  const [loading, setLoading] = useState(true)
  const [backendOnline, setBackendOnline] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getJobs()
      setJobs(data.jobs)
      setBackendOnline(true)
    } catch {
      setBackendOnline(false)
      setJobs([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  const getJob = useCallback(
    (id: string) => jobs.find((j) => j.id === id),
    [jobs],
  )

  const setPipelineStatus = useCallback((id: string, status: PipelineStatus) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.id === id
          ? {
              ...j,
              pipeline_status: status,
              review:
                status === "applied"
                  ? { ...j.review, applied_at: new Date().toISOString() }
                  : j.review,
            }
          : j,
      ),
    )
    void api.setPipelineStatus(id, status).catch(() => {
      setBackendOnline(false)
    })
  }, [])

  const markOpened = useCallback((id: string) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.id === id
          ? {
              ...j,
              last_seen_at: new Date().toISOString(),
              pipeline_status:
                j.pipeline_status === "new" ? "opened" : j.pipeline_status,
            }
          : j,
      ),
    )
    void api.markOpened(id).catch(() => {
      setBackendOnline(false)
    })
  }, [])

  const applyReview = useCallback((id: string, ranking: Partial<JobRanking>) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.id === id
          ? {
              ...j,
              ranking: { ...j.ranking, ...ranking },
              review: {
                ...j.review,
                requires_llm_review: false,
                applied_at: new Date().toISOString(),
              },
            }
          : j,
      ),
    )
    void api.applyManualReview(id, ranking).catch(() => {
      setBackendOnline(false)
    })
  }, [])

  const generateMaterials = useCallback(async (id: string, useLlm = false) => {
    const result = await api.generateMaterials(id, useLlm)
    setBackendOnline(true)
    setJobs((prev) => prev.map((j) => (j.id === id ? result.job : j)))
  }, [])

  const value = useMemo(
    () => ({
      jobs,
      loading,
      backendOnline,
      refresh,
      getJob,
      setPipelineStatus,
      markOpened,
      applyReview,
      generateMaterials,
    }),
    [
      jobs,
      loading,
      backendOnline,
      refresh,
      getJob,
      setPipelineStatus,
      markOpened,
      applyReview,
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
