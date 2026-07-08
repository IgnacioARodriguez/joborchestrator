"use client"

import {
  Building2,
  MapPin,
  Radio,
  ExternalLink,
  Send,
  Star,
  CheckCircle2,
  X,
  CircleCheck,
  CircleDot,
  CircleAlert,
  CircleX,
  Target,
  Lightbulb,
} from "lucide-react"
import { toast } from "sonner"
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from "@/components/ui/drawer"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import { DecisionBadge } from "@/components/badges"
import { ScoreRing } from "@/components/badges"
import { ManualReviewPanel } from "@/components/manual-review-panel"
import { useStore } from "@/lib/store"
import { PIPELINE_LABELS } from "@/lib/job-ui"
import type { JobPosting } from "@/lib/types"
import { cn } from "@/lib/utils"

function EvidenceList({
  title,
  items,
  icon: Icon,
  tone,
}: {
  title: string
  items: string[]
  icon: typeof CircleCheck
  tone: string
}) {
  if (items.length === 0) return null
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <Icon className={cn("size-4", tone)} />
        <h4 className="text-xs font-semibold text-foreground">{title}</h4>
      </div>
      <ul className="flex flex-wrap gap-1.5 pl-5.5">
        {items.map((item) => (
          <li
            key={item}
            className="rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

function MaterialBlock({ label, text }: { label: string; text: string }) {
  if (!text) return null
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-xs font-semibold text-foreground">{label}</p>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
        {text}
      </p>
    </div>
  )
}

function DetailBody({
  job,
  onClose,
}: {
  job: JobPosting
  onClose: () => void
}) {
  const { setPipelineStatus, markOpened } = useStore()
  const { evidence } = job.ranking

  function openExternal(url: string) {
    markOpened(job.id)
    window.open(url, "_blank", "noopener,noreferrer")
  }

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="flex flex-col gap-5 p-4">
        {/* Header block */}
        <div className="flex items-start gap-3">
          <ScoreRing score={job.ranking.final_score} />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <DecisionBadge decision={job.ranking.decision} />
              <span className="rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {PIPELINE_LABELS[job.pipeline_status]}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
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
          </div>
        </div>

        {/* Primary actions */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Button size="sm" variant="outline" onClick={() => openExternal(job.url)}>
            <ExternalLink data-icon="inline-start" />
            Open posting
          </Button>
          <Button size="sm" onClick={() => openExternal(job.apply_url)}>
            <Send data-icon="inline-start" />
            Open apply
          </Button>
          <Button
            size="sm"
            variant="outline"
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
            variant="outline"
            onClick={() => {
              setPipelineStatus(job.id, "applied")
              toast.success("Marked applied", { description: job.title })
            }}
          >
            <CheckCircle2 data-icon="inline-start" />
            Mark applied
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-muted-foreground"
            onClick={() => {
              setPipelineStatus(job.id, "discarded")
              toast("Discarded", { description: job.title })
              onClose()
            }}
          >
            <X data-icon="inline-start" />
            Discard
          </Button>
        </div>

        <Separator />

        {/* Ranking explanation */}
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-foreground">
            Ranking explanation
          </h3>
          <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
            <p className="text-xs leading-relaxed text-foreground">
              {job.ranking.reasoning_summary}
            </p>
          </div>
          <div className="flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3">
            <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" />
            <div className="flex flex-col gap-0.5">
              <p className="text-xs font-semibold text-foreground">
                Recommended angle
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {job.ranking.recommended_application_angle}
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-3 pt-1">
            <EvidenceList
              title="Strong matches"
              items={evidence.strong_matches}
              icon={CircleCheck}
              tone="text-success"
            />
            <EvidenceList
              title="Partial matches"
              items={evidence.partial_matches}
              icon={CircleDot}
              tone="text-info"
            />
            <EvidenceList
              title="Missing requirements"
              items={evidence.missing_requirements}
              icon={CircleAlert}
              tone="text-warning-foreground"
            />
            <EvidenceList
              title="Red flags"
              items={evidence.red_flags}
              icon={CircleX}
              tone="text-destructive"
            />
            <EvidenceList
              title="Central requirements"
              items={evidence.central_requirements}
              icon={Target}
              tone="text-muted-foreground"
            />
          </div>
        </section>

        {/* Needs review inline */}
        {job.review.requires_llm_review && (
          <>
            <Separator />
            <section className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-foreground">
                Manual review
              </h3>
              <ManualReviewPanel job={job} />
            </section>
          </>
        )}

        <Separator />

        {/* Description */}
        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Job description
          </h3>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
            {job.description_text}
          </p>
        </section>

        {/* Application materials */}
        {(job.materials.recruiter_message ||
          job.materials.cover_letter ||
          job.materials.ats_cv_notes ||
          job.materials.autofill_notes) && (
          <>
            <Separator />
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-foreground">
                Application materials
              </h3>
              <div className="flex flex-col gap-2">
                <MaterialBlock
                  label="Recruiter message"
                  text={job.materials.recruiter_message}
                />
                <MaterialBlock
                  label="Cover letter"
                  text={job.materials.cover_letter}
                />
                <MaterialBlock
                  label="ATS CV notes"
                  text={job.materials.ats_cv_notes}
                />
                <MaterialBlock
                  label="Autofill notes"
                  text={job.materials.autofill_notes}
                />
              </div>
            </section>
          </>
        )}
      </div>
    </ScrollArea>
  )
}

export function JobDetailDrawer({
  jobId,
  onClose,
}: {
  jobId: string | null
  onClose: () => void
}) {
  const { getJob } = useStore()
  const job = jobId ? getJob(jobId) : undefined

  return (
    <Drawer
      open={jobId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      showSwipeHandle
    >
      <DrawerContent className="data-[swipe-axis=y]:[--drawer-content-max-height:calc(100dvh-3rem)] data-[swipe-axis=y]:[--drawer-height:88dvh]">
        <DrawerHeader className="text-left">
          <DrawerTitle className="text-pretty leading-snug">
            {job?.title ?? "Job detail"}
          </DrawerTitle>
          <DrawerDescription className="sr-only">
            Ranking, description, and application materials for this job.
          </DrawerDescription>
        </DrawerHeader>
        {job && <DetailBody job={job} onClose={onClose} />}
      </DrawerContent>
    </Drawer>
  )
}
