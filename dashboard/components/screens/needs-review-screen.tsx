"use client"

import { Building2, MapPin, CheckCircle2, ChevronRight } from "lucide-react"
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScoreBadge, DecisionBadge } from "@/components/badges"
import { ManualReviewPanel } from "@/components/manual-review-panel"
import { useStore } from "@/lib/store"

export function NeedsReviewScreen({
  onOpenJob,
}: {
  onOpenJob: (id: string) => void
}) {
  const { jobs } = useStore()
  const queue = jobs.filter((j) => j.review.requires_llm_review)

  if (queue.length === 0) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <CheckCircle2 />
          </EmptyMedia>
          <EmptyTitle>Review queue is clear</EmptyTitle>
          <EmptyDescription>
            No jobs currently require a manual ChatGPT review. New low-confidence
            rankings will show up here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        {queue.length} {queue.length === 1 ? "job needs" : "jobs need"} a manual
        ChatGPT review. Copy the prompt, run it, then paste the JSON back.
      </p>

      {queue.map((job) => {
        const coverage =
          job.ranking.evidence.central_requirements.length > 0
            ? `${job.ranking.evidence.strong_matches.length}/${job.ranking.evidence.central_requirements.length} central reqs matched`
            : null
        return (
          <Card key={job.id} className="gap-3">
            <CardHeader className="gap-2 pb-0">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <ScoreBadge score={job.ranking.final_score} />
                    <DecisionBadge decision={job.ranking.decision} />
                    <span className="rounded-md border border-border bg-muted/50 px-1.5 py-0.5 text-xs text-muted-foreground">
                      {Math.round(job.ranking.confidence * 100)}% conf.
                    </span>
                  </div>
                  <h3 className="text-pretty text-sm font-semibold leading-snug text-foreground">
                    {job.title}
                  </h3>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <Building2 className="size-3.5" />
                      {job.company}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="size-3.5" />
                      {job.location}
                    </span>
                  </div>
                  {coverage && (
                    <span className="text-xs text-muted-foreground">
                      {coverage}
                    </span>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 px-2 text-xs"
                  onClick={() => onOpenJob(job.id)}
                >
                  Detail
                  <ChevronRight data-icon="inline-end" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <ManualReviewPanel job={job} />
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
