"use client"

import { useMemo, useState } from "react"
import { Search, SlidersHorizontal } from "lucide-react"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { JobCompactCard } from "@/components/job-compact-card"
import { PageHeader } from "@/components/page-chrome"
import { cn } from "@/lib/utils"
import { useStore } from "@/lib/store"
import type { Decision, JobPosting } from "@/lib/types"
import { DECISION_STYLES, isActionableApplyDecision } from "@/lib/job-ui"

type FilterKey = "remote" | "linkedin" | "ats" | "review"
type SortKey = "score" | "newest" | "lastseen"

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "remote", label: "Remote" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "ats", label: "ATS" },
  { key: "review", label: "Needs review" },
]

const ATS_SOURCES = ["Greenhouse", "Lever", "Ashby"]
const DECISION_COLUMNS: Decision[] = [
  "APPLY_NOW",
  "APPLY_WITH_TAILORED_CV",
  "MAYBE",
  "SKIP",
  "AVOID",
]

function rankingVersionLabel(version: string): string {
  const normalized = version.toLowerCase()
  if (normalized.includes("nvidia")) return "NVIDIA"
  if (normalized.includes("openai") || normalized.includes("+llm:")) {
    const model = version.split(":").pop()?.replaceAll("_", "/")
    return model ? `OpenAI ${model}` : "OpenAI"
  }
  return version
}

function needsReview(job: JobPosting): boolean {
  return (
    (job.ranking.decision === "APPLY_NOW" ||
      job.ranking.decision === "APPLY_WITH_TAILORED_CV") &&
    !isActionableApplyDecision(job.ranking.decision, job.ranking.final_score)
  )
}

function matchesFilter(job: JobPosting, key: FilterKey): boolean {
  switch (key) {
    case "remote":
      return job.remote
    case "linkedin":
      return job.source === "LinkedIn"
    case "ats":
      return ATS_SOURCES.includes(job.source)
    case "review":
      return needsReview(job)
  }
}

function sortJobs(list: JobPosting[], sort: SortKey): JobPosting[] {
  return [...list].sort((a, b) => {
    if (sort === "score") return b.ranking.final_score - a.ranking.final_score
    if (sort === "newest") {
      return new Date(b.first_seen_at).getTime() - new Date(a.first_seen_at).getTime()
    }
    return new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime()
  })
}

function averageScore(jobs: JobPosting[]): number {
  if (jobs.length === 0) return 0
  return Math.round(jobs.reduce((sum, job) => sum + job.ranking.final_score, 0) / jobs.length)
}

export function RankingScreen({
  onOpenJob,
}: {
  onOpenJob: (id: string) => void
}) {
  const {
    jobs,
    rankingVersions,
    selectedRankingVersion,
    setSelectedRankingVersion,
  } = useStore()
  const [query, setQuery] = useState("")
  const [active, setActive] = useState<Set<FilterKey>>(new Set())
  const [sort, setSort] = useState<SortKey>("score")

  function toggleFilter(key: FilterKey) {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = jobs.filter((j) => j.pipeline_status !== "discarded")

    if (q) {
      list = list.filter(
        (j) =>
          j.title.toLowerCase().includes(q) ||
          j.company.toLowerCase().includes(q) ||
          j.location.toLowerCase().includes(q),
      )
    }

    for (const key of active) {
      list = list.filter((j) => matchesFilter(j, key))
    }

    return sortJobs(list, sort)
  }, [jobs, query, active, sort])

  const grouped = useMemo(() => {
    const map = new Map<Decision, JobPosting[]>()
    for (const decision of DECISION_COLUMNS) map.set(decision, [])
    for (const job of filtered) {
      map.get(job.ranking.decision)?.push(job)
    }
    return map
  }, [filtered])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Ranking"
        title="Prioritized opportunities"
        description="Review ranked jobs by recommendation. Each decision lane has its own scroll, so the board stays stable while you triage."
      />

      <section
        aria-label="Ranking controls"
        className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.04)]"
      >
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-[1fr_13rem_10rem]">
          <label className="relative block">
            <span className="sr-only">Search jobs</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search title, company, location"
              className="pl-9"
            />
          </label>
          <Select
            value={selectedRankingVersion ?? ""}
            onValueChange={(version) => {
              if (version) setSelectedRankingVersion(version)
            }}
            disabled={rankingVersions.length === 0}
          >
            <SelectTrigger aria-label="Ranking version">
              <SelectValue placeholder="No LLM ranking" />
            </SelectTrigger>
            <SelectContent>
              {rankingVersions.map((version) => (
                <SelectItem key={version} value={version}>
                  {rankingVersionLabel(version)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
            <SelectTrigger aria-label="Sort jobs">
              <SlidersHorizontal className="size-4 text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="score">Score</SelectItem>
              <SelectItem value="newest">Newest</SelectItem>
              <SelectItem value="lastseen">Last seen</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {FILTERS.map((filter) => {
            const on = active.has(filter.key)
            return (
              <button
                key={filter.key}
                type="button"
                onClick={() => toggleFilter(filter.key)}
                aria-pressed={on}
                className={cn(
                  "rounded-md border px-3 py-1 text-xs font-medium transition-colors",
                  on
                    ? "border-primary/20 bg-primary/10 text-primary"
                    : "border-border bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {filter.label}
              </button>
            )
          })}
          <span className="ml-auto text-xs font-medium text-muted-foreground">
            {filtered.length} visible
          </span>
        </div>
      </section>

      <div className="min-h-0 flex-1 overflow-x-auto pb-1">
        <div className="grid h-full min-w-[1120px] grid-cols-5 gap-3">
          {DECISION_COLUMNS.map((decision) => {
            const laneJobs = grouped.get(decision) ?? []
            return (
              <section
                key={decision}
                aria-labelledby={`ranking-lane-${decision}`}
                className="flex min-h-0 flex-col rounded-lg border border-border bg-muted/25"
              >
                <div className="shrink-0 border-b border-border bg-card px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <h2
                      id={`ranking-lane-${decision}`}
                      className="text-sm font-semibold text-foreground"
                    >
                      {DECISION_STYLES[decision].label}
                    </h2>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                      {laneJobs.length}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Avg score {averageScore(laneJobs)}
                  </p>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-2">
                  {laneJobs.length === 0 ? (
                    <Empty className="h-full border border-dashed bg-background/70">
                      <EmptyHeader>
                        <EmptyTitle>No jobs</EmptyTitle>
                        <EmptyDescription>
                          Matching roles for this decision appear here.
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {laneJobs.map((job) => (
                        <JobCompactCard key={job.id} job={job} onOpen={onOpenJob} />
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}
