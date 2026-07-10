"use client"

import { ChevronRight } from "lucide-react"
import { ScoreBadge, DecisionBadge } from "@/components/badges"
import type { JobPosting } from "@/lib/types"
import { relativeTime } from "@/lib/job-ui"

export function JobRow({
  job,
  onOpen,
}: {
  job: JobPosting
  onOpen: (id: string) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(job.id)}
      className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-accent/50"
    >
      <ScoreBadge score={job.ranking.final_score} />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-medium text-foreground">
          {job.title}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {job.company} · {relativeTime(job.last_seen_at)}
        </span>
      </div>
      <DecisionBadge
        decision={job.ranking.decision}
        score={job.ranking.final_score}
      />
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
    </button>
  )
}
