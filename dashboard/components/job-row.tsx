"use client"

import { ChevronRight } from "lucide-react"
import { ScoreBadge, DecisionBadge, ReviewBadge } from "@/components/badges"
import type { JobPosting } from "@/lib/types"
import { relativeTime } from "@/lib/job-ui"

export function JobRow({
  job,
  onOpen,
  showReview = false,
}: {
  job: JobPosting
  onOpen: (id: string) => void
  showReview?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(job.id)}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent/50"
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
      {showReview && job.review.requires_llm_review ? (
        <ReviewBadge />
      ) : (
        <DecisionBadge decision={job.ranking.decision} />
      )}
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
    </button>
  )
}
