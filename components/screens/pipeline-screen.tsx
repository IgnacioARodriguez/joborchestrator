"use client"

import { Building2, Inbox } from "lucide-react"
import { toast } from "sonner"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScoreBadge, DecisionBadge } from "@/components/badges"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { PIPELINE_LABELS, relativeTime } from "@/lib/job-ui"
import type { JobPosting, PipelineStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const PIPELINE_COLUMNS: PipelineStatus[] = [
  "new",
  "shortlisted",
  "opened",
  "applied",
  "discarded",
]

function moveMessage(status: PipelineStatus) {
  return `Moved to ${PIPELINE_LABELS[status]}`
}

function PipelineCard({
  job,
  onOpen,
}: {
  job: JobPosting
  onOpen: (id: string) => void
}) {
  const { setPipelineStatus } = useStore()
  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
      <button
        type="button"
        onClick={() => onOpen(job.id)}
        className="w-full text-left"
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
        <p className="mt-1 flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
          <Building2 className="size-3.5 shrink-0" />
          <span className="truncate">{job.company}</span>
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground/80">
          {job.source} · {relativeTime(job.last_seen_at)}
        </p>
      </button>
      <div className="mt-3 flex flex-wrap gap-1">
        {PIPELINE_COLUMNS.filter((status) => status !== job.pipeline_status).map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => {
              setPipelineStatus(job.id, status)
              toast.success(moveMessage(status), { description: job.title })
            }}
            className="rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {PIPELINE_LABELS[status]}
          </button>
        ))}
      </div>
    </article>
  )
}

export function PipelineScreen({
  onOpenJob,
}: {
  onOpenJob: (id: string) => void
}) {
  const { jobs } = useStore()

  const byStatus = (status: PipelineStatus) =>
    jobs
      .filter((j) => j.pipeline_status === status)
      .sort((a, b) => b.ranking.final_score - a.ranking.final_score)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Pipeline"
        title="Application pipeline"
        description="Move opportunities through fixed workflow lanes."
      />

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {PIPELINE_COLUMNS.map((status) => {
            const items = byStatus(status)
            return (
              <section
                key={status}
                aria-labelledby={`pipeline-${status}`}
                className={cn(
                  "flex h-[min(72dvh,500px)] min-h-0 flex-col rounded-lg border border-border bg-muted/25 xl:h-[34dvh] xl:min-h-[300px]",
                  status === "discarded" && "opacity-90",
                )}
              >
                <div className="shrink-0 border-b border-border bg-card px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <h2
                      id={`pipeline-${status}`}
                      className="text-sm font-semibold text-foreground"
                    >
                      {PIPELINE_LABELS[status]}
                    </h2>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                      {items.length}
                    </span>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
                  {items.length === 0 ? (
                    <Empty className="h-full border border-dashed bg-background/70">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <Inbox />
                        </EmptyMedia>
                        <EmptyTitle>Empty lane</EmptyTitle>
                        <EmptyDescription>
                          Jobs moved to {PIPELINE_LABELS[status].toLowerCase()} appear here.
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {items.map((job) => (
                        <PipelineCard key={job.id} job={job} onOpen={onOpenJob} />
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
