"use client"

import { useState } from "react"
import { Building2, ChevronRight, Inbox } from "lucide-react"
import { toast } from "sonner"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { ScoreBadge, DecisionBadge } from "@/components/badges"
import { useStore } from "@/lib/store"
import { PIPELINE_LABELS, relativeTime } from "@/lib/job-ui"
import type { JobPosting, PipelineStatus } from "@/lib/types"

const TABS: PipelineStatus[] = ["shortlisted", "applied", "discarded", "opened"]
const STATUS_OPTIONS: PipelineStatus[] = [
  "new",
  "shortlisted",
  "applied",
  "opened",
  "discarded",
]

function PipelineItem({
  job,
  onOpen,
}: {
  job: JobPosting
  onOpen: (id: string) => void
}) {
  const { setPipelineStatus } = useStore()
  return (
    <Card className="flex-row items-center gap-2 p-3">
      <ScoreBadge score={job.ranking.final_score} />
      <button
        type="button"
        onClick={() => onOpen(job.id)}
        className="flex min-w-0 flex-1 flex-col gap-1 text-left"
      >
        <span className="truncate text-sm font-medium text-foreground">
          {job.title}
        </span>
        <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          <Building2 className="size-3.5" />
          {job.company}
          <span aria-hidden>·</span>
          {relativeTime(job.last_seen_at)}
        </span>
        <DecisionBadge decision={job.ranking.decision} className="mt-0.5 w-fit" />
      </button>
      <Select
        value={job.pipeline_status}
        onValueChange={(v) => {
          setPipelineStatus(job.id, v as PipelineStatus)
          toast.success(`Moved to ${PIPELINE_LABELS[v as PipelineStatus]}`, {
            description: job.title,
          })
        }}
      >
        <SelectTrigger
          size="sm"
          className="w-32 shrink-0"
          aria-label="Change status"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STATUS_OPTIONS.map((s) => (
            <SelectItem key={s} value={s}>
              {PIPELINE_LABELS[s]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Card>
  )
}

export function PipelineScreen({
  onOpenJob,
}: {
  onOpenJob: (id: string) => void
}) {
  const { jobs } = useStore()
  const [tab, setTab] = useState<PipelineStatus>("shortlisted")

  const byStatus = (status: PipelineStatus) =>
    jobs
      .filter((j) => j.pipeline_status === status)
      .sort((a, b) => b.ranking.final_score - a.ranking.final_score)

  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as PipelineStatus)}>
      <TabsList className="w-full">
        {TABS.map((t) => {
          const count = jobs.filter((j) => j.pipeline_status === t).length
          return (
            <TabsTrigger key={t} value={t} className="flex-1 gap-1.5 text-xs">
              {PIPELINE_LABELS[t]}
              <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums text-muted-foreground">
                {count}
              </span>
            </TabsTrigger>
          )
        })}
      </TabsList>

      {TABS.map((t) => {
        const items = byStatus(t)
        return (
          <TabsContent key={t} value={t} className="mt-3 flex flex-col gap-2">
            {items.length === 0 ? (
              <Empty className="border border-dashed">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Inbox />
                  </EmptyMedia>
                  <EmptyTitle>Nothing here yet</EmptyTitle>
                  <EmptyDescription>
                    Jobs marked {PIPELINE_LABELS[t].toLowerCase()} will appear in
                    this tab.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              items.map((job) => (
                <PipelineItem key={job.id} job={job} onOpen={onOpenJob} />
              ))
            )}
          </TabsContent>
        )
      })}
    </Tabs>
  )
}
