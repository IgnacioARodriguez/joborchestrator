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
  JobsMeta,
  PipelineStatus,
} from "./types"
import { api } from "./api"

interface StoreValue {
  jobs: JobPosting[]
  loading: boolean
  backendOnline: boolean
  jobsMeta: JobsMeta | null
  rankingVersions: string[]
  selectedRankingVersion: string | null
  setSelectedRankingVersion: (version: string) => void
  refresh: (rankingVersion?: string | null) => Promise<void>
  getJob: (id: string) => JobPosting | undefined
  setPipelineStatus: (id: string, status: PipelineStatus) => void
  markOpened: (id: string) => void
  generateMaterials: (id: string, provider?: "heuristic" | "openai" | "nvidia") => Promise<void>
}

const StoreContext = createContext<StoreValue | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobPosting[]>([])
  const [loading, setLoading] = useState(true)
  const [backendOnline, setBackendOnline] = useState(false)
  const [jobsMeta, setJobsMeta] = useState<JobsMeta | null>(null)
  const [rankingVersions, setRankingVersions] = useState<string[]>([])
  const [selectedRankingVersion, setSelectedRankingVersionState] =
    useState<string | null>(null)

  const refresh = useCallback(async (rankingVersion?: string | null) => {
    setLoading(true)
    try {
      const data = await api.getJobs(rankingVersion ?? selectedRankingVersion)
      setJobs(data.jobs)
      setRankingVersions(data.ranking_versions)
      setSelectedRankingVersionState(
        data.selected_ranking_version ?? data.ranking_versions[0] ?? null,
      )
      setJobsMeta(data.meta ?? null)
      setBackendOnline(true)
    } catch {
      setBackendOnline(false)
      setJobs([])
      setJobsMeta(null)
    } finally {
      setLoading(false)
    }
  }, [selectedRankingVersion])

  const setSelectedRankingVersion = useCallback((version: string) => {
    setSelectedRankingVersionState(version)
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

  const generateMaterials = useCallback(async (id: string, provider: "heuristic" | "openai" | "nvidia" = "openai") => {
    const result = await api.generateMaterials(id, provider)
    setBackendOnline(true)
    setJobs((prev) => prev.map((j) => (j.id === id ? result.job : j)))
  }, [])

  const value = useMemo(
    () => ({
      jobs,
      loading,
      backendOnline,
      jobsMeta,
      rankingVersions,
      selectedRankingVersion,
      setSelectedRankingVersion,
      refresh,
      getJob,
      setPipelineStatus,
      markOpened,
      generateMaterials,
    }),
    [
      jobs,
      loading,
      backendOnline,
      jobsMeta,
      rankingVersions,
      selectedRankingVersion,
      setSelectedRankingVersion,
      refresh,
      getJob,
      setPipelineStatus,
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
