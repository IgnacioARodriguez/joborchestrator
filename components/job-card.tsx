"use client"

import {
  Building2,
  MapPin,
  ExternalLink,
  Send,
  Star,
  X,
  Radio,
  FileText,
  Users,
  WalletCards,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { DecisionBadge, ScoreBadge } from "@/components/badges"
import { useStore } from "@/lib/store"
import type { JobPosting } from "@/lib/types"
import {
  applicantLabel,
  applyUrlForJob,
  rankingSummaryText,
  relativeTime,
  salaryLabel,
} from "@/lib/job-ui"

export function JobCard({
  job,
  onOpen,
}: {
  job: JobPosting
  onOpen: (id: string) => void
}) {
  const { setPipelineStatus, markOpened } = useStore()
  const hasMaterials = Boolean(
    job.materials.recruiter_message ||
      job.materials.cover_letter ||
      job.materials.ats_cv_notes ||
      job.materials.autofill_notes,
  )
  const applicants = applicantLabel(job)
  const salary = salaryLabel(job)

  function openExternal(url: string) {
    markOpened(job.id)
    window.open(url, "_blank", "noopener,noreferrer")
  }

  return (
    <Card className="gap-0 overflow-hidden p-0 transition-shadow hover:shadow-[0_1px_2px_rgba(16,24,40,0.05),0_16px_34px_rgba(16,24,40,0.06)]">
      <button
        type="button"
        onClick={() => onOpen(job.id)}
        className="flex w-full flex-col gap-4 p-5 text-left transition-colors hover:bg-accent/30"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <ScoreBadge score={job.ranking.final_score} />
              <DecisionBadge
                decision={job.ranking.decision}
                score={job.ranking.final_score}
              />
              {hasMaterials ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                  <FileText className="size-3" />
                  Kit ready
                </span>
              ) : null}
              {applicants ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                  <Users className="size-3" />
                  {applicants}
                </span>
              ) : null}
              {salary ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                  <WalletCards className="size-3" />
                  {salary}
                </span>
              ) : null}
            </div>
            <h3 className="text-pretty text-base font-semibold leading-snug text-foreground">
              {job.title}
            </h3>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Building2 className="size-3.5" />
            {job.company}
          </span>
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3.5" />
            {job.location}
          </span>
          <span className="inline-flex items-center gap-1">
            <Radio className="size-3.5" />
            {job.source}
          </span>
        </div>

        <p className="line-clamp-2 text-pretty text-xs leading-relaxed text-muted-foreground">
          {rankingSummaryText(
            job.ranking.decision,
            job.ranking.final_score,
            job.ranking.reasoning_summary,
          )}
        </p>
        <span className="text-[11px] text-muted-foreground/80">
          Last seen {relativeTime(job.last_seen_at)}
        </span>
      </button>

      <div className="grid grid-cols-2 gap-1.5 border-t border-border bg-muted/30 p-2 sm:grid-cols-4">
        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-xs"
          onClick={() => openExternal(job.url)}
        >
          <ExternalLink data-icon="inline-start" />
          Open
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-xs"
          onClick={() => openExternal(applyUrlForJob(job))}
        >
          <Send data-icon="inline-start" />
          Apply
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-xs"
          onClick={() => {
            setPipelineStatus(job.id, "shortlisted")
            toast.success("Shortlisted", { description: job.title })
          }}
        >
          <Star data-icon="inline-start" />
          Shortlist
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-xs text-muted-foreground"
          onClick={() => {
            setPipelineStatus(job.id, "discarded")
            toast("Discarded", { description: job.title })
          }}
        >
          <X data-icon="inline-start" />
          Discard
        </Button>
      </div>
    </Card>
  )
}
