"use client"

import { Building2, ExternalLink, MapPin } from "lucide-react"
import { DecisionBadge, ScoreBadge } from "@/components/badges"
import { Button } from "@/components/ui/button"
import type { JobPosting } from "@/lib/types"
import { rankingSummaryText, relativeTime } from "@/lib/job-ui"
import { cn } from "@/lib/utils"

export function JobCompactCard({
  job,
  onOpen,
  className,
}: {
  job: JobPosting
  onOpen: (id: string) => void
  className?: string
}) {
  return (
    <article
      className={cn(
        "rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)]",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onOpen(job.id)}
          className="min-w-0 flex-1 text-left"
        >
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <ScoreBadge score={job.ranking.final_score} />
            <DecisionBadge
              decision={job.ranking.decision}
              score={job.ranking.final_score}
            />
          </div>
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
            {job.title}
          </h3>
        </button>
        <Button
          aria-label={`Open ${job.title}`}
          size="icon-sm"
          variant="ghost"
          onClick={() => window.open(job.url, "_blank", "noopener,noreferrer")}
        >
          <ExternalLink className="size-3.5" />
        </Button>
      </div>
      <div className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
        <span className="flex min-w-0 items-center gap-1">
          <Building2 className="size-3.5 shrink-0" />
          <span className="truncate">{job.company}</span>
        </span>
        <span className="flex min-w-0 items-center gap-1">
          <MapPin className="size-3.5 shrink-0" />
          <span className="truncate">{job.location}</span>
        </span>
      </div>
      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
        {rankingSummaryText(
          job.ranking.decision,
          job.ranking.final_score,
          job.ranking.reasoning_summary,
        )}
      </p>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground/80">
        <span>{job.source}</span>
        <span>{relativeTime(job.last_seen_at)}</span>
      </div>
    </article>
  )
}
