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
import { JobCard } from "@/components/job-card"
import { cn } from "@/lib/utils"
import { useStore } from "@/lib/store"
import type { JobPosting } from "@/lib/types"

type FilterKey =
  | "apply"
  | "maybe"
  | "remote"
  | "linkedin"
  | "ats"

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "apply", label: "Apply" },
  { key: "maybe", label: "Maybe" },
  { key: "remote", label: "Remote" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "ats", label: "ATS" },
]

type SortKey = "score" | "newest" | "lastseen"

const ATS_SOURCES = ["Greenhouse", "Lever", "Ashby"]

function rankingVersionLabel(version: string): string {
  const normalized = version.toLowerCase()
  if (normalized.includes("nvidia")) return "NVIDIA"
  if (normalized.includes("openai") || normalized.includes("+llm:")) {
    const model = version.split(":").pop()?.replaceAll("_", "/")
    return model ? `OpenAI ${model}` : "OpenAI"
  }
  return version
}

function matchesFilter(job: JobPosting, key: FilterKey): boolean {
  switch (key) {
    case "apply":
      return (
        job.ranking.decision === "APPLY_NOW" ||
        job.ranking.decision === "APPLY_WITH_TAILORED_CV"
      )
    case "maybe":
      return job.ranking.decision === "MAYBE"
    case "remote":
      return job.remote
    case "linkedin":
      return job.source === "LinkedIn"
    case "ats":
      return ATS_SOURCES.includes(job.source)
  }
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

  const results = useMemo(() => {
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

    list = [...list].sort((a, b) => {
      if (sort === "score") return b.ranking.final_score - a.ranking.final_score
      if (sort === "newest")
        return (
          new Date(b.first_seen_at).getTime() -
          new Date(a.first_seen_at).getTime()
        )
      return (
        new Date(b.last_seen_at).getTime() -
        new Date(a.last_seen_at).getTime()
      )
    })

    return list
  }, [jobs, query, active, sort])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, company, location"
            className="pl-9"
            aria-label="Search jobs"
          />
        </div>
        <Select
          value={selectedRankingVersion ?? ""}
          onValueChange={(version) => {
            if (version) setSelectedRankingVersion(version)
          }}
          disabled={rankingVersions.length === 0}
        >
          <SelectTrigger className="w-full sm:w-52">
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
          <SelectTrigger className="w-full sm:w-40">
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

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const on = active.has(f.key)
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => toggleFilter(f.key)}
              aria-pressed={on}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                on
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-accent",
              )}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        {results.length} {results.length === 1 ? "job" : "jobs"}
        {selectedRankingVersion
          ? ` ranked with ${rankingVersionLabel(selectedRankingVersion)}`
          : " without an LLM ranking yet"}
      </p>

      {results.length === 0 ? (
        <Empty className="border border-dashed">
          <EmptyHeader>
            <EmptyTitle>No matching jobs</EmptyTitle>
            <EmptyDescription>
              Try clearing filters or adjusting your search.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {results.map((job) => (
            <JobCard key={job.id} job={job} onOpen={onOpenJob} />
          ))}
        </div>
      )}
    </div>
  )
}
