"use client"

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import type {
  ImportRecord,
  JobPosting,
  JobRanking,
  PipelineStatus,
} from "./types"
import { MOCK_IMPORTS, MOCK_JOBS } from "./mock-data"

// Client store backed by mock data. Every mutation is isolated here so the
// data layer can later be replaced with Supabase calls without touching the UI.

interface StoreValue {
  jobs: JobPosting[]
  imports: ImportRecord[]
  getJob: (id: string) => JobPosting | undefined
  setPipelineStatus: (id: string, status: PipelineStatus) => void
  markOpened: (id: string) => void
  applyReview: (id: string, ranking: Partial<JobRanking>) => void
  importJobs: (incoming: JobPosting[], mode: "merge" | "replace") => void
  resetToSample: () => void
  addImport: (record: ImportRecord) => void
}

const StoreContext = createContext<StoreValue | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobPosting[]>(MOCK_JOBS)
  const [imports, setImports] = useState<ImportRecord[]>(MOCK_IMPORTS)

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
  }, [])

  const importJobs = useCallback(
    (incoming: JobPosting[], mode: "merge" | "replace") => {
      const now = new Date().toISOString()
      let inserted = incoming.length
      let updated = 0
      let duplicates = 0

      setJobs((prev) => {
        if (mode === "replace") return incoming

        const byId = new Map(prev.map((job) => [job.id, job]))
        for (const job of incoming) {
          if (byId.has(job.id)) {
            updated += 1
            byId.set(job.id, { ...byId.get(job.id), ...job })
          } else {
            byId.set(job.id, job)
          }
        }

        inserted = incoming.length - updated
        duplicates = updated
        return Array.from(byId.values())
      })

      setImports((prev) => [
        {
          id: `imp_${Date.now()}`,
          file_name:
            mode === "replace"
              ? "pasted_json_replace.json"
              : "pasted_json_merge.json",
          imported_at: now,
          rows_detected: incoming.length,
          inserted,
          updated,
          duplicates,
          errors: 0,
        },
        ...prev,
      ])
    },
    [],
  )

  const resetToSample = useCallback(() => {
    setJobs(MOCK_JOBS)
    setImports(MOCK_IMPORTS)
  }, [])

  const addImport = useCallback((record: ImportRecord) => {
    setImports((prev) => [record, ...prev])
  }, [])

  const value = useMemo(
    () => ({
      jobs,
      imports,
      getJob,
      setPipelineStatus,
      markOpened,
      applyReview,
      importJobs,
      resetToSample,
      addImport,
    }),
    [
      jobs,
      imports,
      getJob,
      setPipelineStatus,
      markOpened,
      applyReview,
      importJobs,
      resetToSample,
      addImport,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore() {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error("useStore must be used within StoreProvider")
  return ctx
}
