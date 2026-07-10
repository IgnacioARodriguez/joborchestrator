"use client"

import { useEffect, useState, type ReactNode } from "react"
import {
  Building2,
  Copy,
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
  Sparkles,
  Users,
  WalletCards,
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
import { useStore } from "@/lib/store"
import { api } from "@/lib/api"
import {
  applicantLabel,
  applyUrlForJob,
  PIPELINE_LABELS,
  rankingSummaryText,
  salaryLabel,
} from "@/lib/job-ui"
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

function MaterialBlock({
  label,
  text,
  actions,
}: {
  label: string
  text: string
  actions?: ReactNode
}) {
  if (!text) return null
  async function copyText() {
    await navigator.clipboard.writeText(text)
    toast.success("Copied", { description: label })
  }
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">{label}</p>
        <div className="flex flex-wrap justify-end gap-1">
          {actions}
          <Button variant="ghost" size="sm" onClick={() => void copyText()}>
            <Copy data-icon="inline-start" />
            Copy
          </Button>
        </div>
      </div>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
        {text}
      </p>
    </div>
  )
}

function parseAutofillPlan(text: string) {
  try {
    const parsed = JSON.parse(text) as {
      preflight_checklist?: string[]
      browser_steps?: string[]
      copy_paste_block?: string
      form_responses?: Array<{
        field?: string
        question?: string
        answer?: string
        confidence?: string
        needs_review?: boolean
      }>
    }
    return parsed && typeof parsed === "object" ? parsed : null
  } catch {
    return null
  }
}

function AutofillPlanBlock({ text }: { text: string }) {
  const plan = parseAutofillPlan(text)
  if (!plan) return <MaterialBlock label="Autofill notes" text={text} />

  const copyText = async (label: string, value: string) => {
    await navigator.clipboard.writeText(value)
    toast.success("Copied", { description: label })
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">
          Application workflow
        </p>
        {plan.copy_paste_block && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void copyText("Application answers", plan.copy_paste_block ?? "")}
          >
            <Copy data-icon="inline-start" />
            Copy answers
          </Button>
        )}
      </div>
      {plan.preflight_checklist && plan.preflight_checklist.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-foreground">Preflight</p>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {plan.preflight_checklist.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {plan.browser_steps && plan.browser_steps.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-foreground">Browser steps</p>
          <ol className="list-decimal space-y-1 pl-4 text-xs text-muted-foreground">
            {plan.browser_steps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
      )}
      {plan.form_responses && plan.form_responses.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-foreground">Prepared answers</p>
          {plan.form_responses.map((response) => (
            <div
              key={`${response.field}-${response.question}`}
              className="rounded-md border border-border bg-background/60 p-2"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs font-medium text-foreground">
                  {response.question || response.field}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void copyText(response.field || "Answer", response.answer || "")}
                >
                  <Copy data-icon="inline-start" />
                  Copy
                </Button>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                {response.answer}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                confidence {response.confidence || "medium"}
                {response.needs_review ? " - review before using" : ""}
              </p>
            </div>
          ))}
        </div>
      )}
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
  const { setPipelineStatus, markOpened, generateMaterials, refresh, applications } = useStore()
  const [materialsOperationId, setMaterialsOperationId] = useState<number | null>(null)
  const { evidence } = job.ranking
  const applicants = applicantLabel(job)
  const salary = salaryLabel(job)
  const companyHistory = applications.filter(
    (application) => application.company?.toLowerCase() === job.company.toLowerCase(),
  )

  useEffect(() => {
    if (!materialsOperationId) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const response = await api.getOperation(materialsOperationId)
        if (stopped) return
        if (response.operation.status === "completed") {
          await refresh()
          if (!stopped) {
            setMaterialsOperationId(null)
            toast.success("Application kit ready", { description: job.title })
          }
          return
        }
        if (response.operation.status === "failed") {
          setMaterialsOperationId(null)
          toast.error("Application kit failed", {
            description: response.operation.error ?? "Check local worker logs.",
          })
          return
        }
        timer = window.setTimeout(poll, 2500)
      } catch (e) {
        if (!stopped) {
          setMaterialsOperationId(null)
          toast.error("Could not check materials generation", {
            description: e instanceof Error ? e.message : "Backend request failed.",
          })
        }
      }
    }
    timer = window.setTimeout(poll, 1000)
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [job.title, materialsOperationId, refresh])

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
              <DecisionBadge
                decision={job.ranking.decision}
                score={job.ranking.final_score}
              />
              <span className="rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {PIPELINE_LABELS[job.pipeline_status]}
              </span>
              {applicants ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  <Users className="size-3" />
                  {applicants}
                </span>
              ) : null}
              {salary ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  <WalletCards className="size-3" />
                  {salary}
                </span>
              ) : null}
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
              {job.recruiter_name ? (
                <a
                  href={job.recruiter_profile_url || undefined}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(
                    "inline-flex items-center gap-1",
                    job.recruiter_profile_url && "text-primary hover:underline",
                  )}
                >
                  <ExternalLink className="size-3.5" />
                  {job.recruiter_name}
                </a>
              ) : null}
            </div>
          </div>
        </div>

        {/* Primary actions */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Button size="sm" variant="outline" onClick={() => openExternal(job.url)}>
            <ExternalLink data-icon="inline-start" />
            Open posting
          </Button>
          <Button size="sm" onClick={() => openExternal(applyUrlForJob(job))}>
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
            onClick={async () => {
              try {
                const result = await generateMaterials(job.id, "nvidia")
                if (result.operation_id) {
                  setMaterialsOperationId(result.operation_id)
                  toast.success("NVIDIA kit queued", { description: job.title })
                } else {
                  toast.success("NVIDIA kit generated", { description: job.title })
                }
              } catch (e) {
                toast.error("Could not generate NVIDIA kit", {
                  description:
                    e instanceof Error ? e.message : "Backend request failed.",
                })
              }
            }}
          >
            <Sparkles data-icon="inline-start" />
            NVIDIA kit
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                const result = await generateMaterials(job.id, "openai")
                if (result.operation_id) {
                  setMaterialsOperationId(result.operation_id)
                  toast.success("OpenAI kit queued", { description: job.title })
                } else {
                  toast.success("OpenAI kit generated", { description: job.title })
                }
              } catch (e) {
                toast.error("Could not generate OpenAI kit", {
                  description:
                    e instanceof Error ? e.message : "Backend request failed.",
                })
              }
            }}
          >
            <Sparkles data-icon="inline-start" />
            OpenAI kit
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setPipelineStatus(job.id, "ready_to_apply")
              toast.success("Ready to apply", { description: job.title })
            }}
          >
            <CheckCircle2 data-icon="inline-start" />
            Ready to apply
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

        {/* Recommendation */}
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-foreground">
            Recommendation
          </h3>
          <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
            <p className="text-xs leading-relaxed text-foreground">
              {rankingSummaryText(
                job.ranking.decision,
                job.ranking.final_score,
                job.ranking.reasoning_summary,
              )}
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
        </section>

        {/* Constraints and evidence */}
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-foreground">
            Constraints and evidence
          </h3>
          <div className="flex flex-col gap-3">
            <EvidenceList
              title="Hard constraints and dealbreakers"
              items={[...evidence.dealbreakers, ...evidence.red_flags]}
              icon={CircleX}
              tone="text-destructive"
            />
            <EvidenceList
              title="Must-haves with evidence"
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
              title="Gaps"
              items={evidence.missing_requirements}
              icon={CircleAlert}
              tone="text-warning-foreground"
            />
            <EvidenceList
              title="Central requirements"
              items={evidence.central_requirements}
              icon={Target}
              tone="text-muted-foreground"
            />
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Job data
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {salary ? <span className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">Salary {salary}</span> : null}
            {applicants ? <span className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">{applicants}</span> : null}
            <span className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">Source {job.source}</span>
            <span className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">Pipeline {PIPELINE_LABELS[job.pipeline_status]}</span>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Strategy
          </h3>
          <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
            {job.recruiter_name ? (
              <p>
                Contact {job.recruiter_name}
                {job.recruiter_profile_url ? " before or after applying." : "."}
              </p>
            ) : (
              <p>
                Apply through the available link, then look for a recruiter or referral path if the score stays strong.
              </p>
            )}
            <p className="mt-2">
              Recommended CV emphasis: {job.ranking.cv_keywords_to_emphasize.slice(0, 6).join(", ") || "No keyword guidance available."}
            </p>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Company history
          </h3>
          {companyHistory.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              No previous applications recorded for {job.company}.
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {companyHistory.slice(0, 4).map((application) => (
                <div key={application.id} className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  {application.job_title || "Application"} - {application.status.replace("_", " ")}
                </div>
              ))}
            </div>
          )}
        </section>

        <details className="rounded-lg border border-border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            Job description
          </summary>
          <p className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
            {job.description_text}
          </p>
        </details>

        <details className="rounded-lg border border-border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            Ranking technical detail
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            {Object.entries(job.ranking.scores).map(([key, value]) => (
              <div key={key} className="rounded-md border border-border bg-background/60 px-2 py-1">
                <span className="block text-[11px] uppercase text-muted-foreground/70">{key.replaceAll("_", " ")}</span>
                <span className="font-semibold text-foreground">{String(value)}</span>
              </div>
            ))}
          </div>
        </details>

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
                  label="Optimized ATS CV"
                  text={job.materials.ats_cv_notes}
                  actions={
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => window.open(api.materialDownloadUrl(job.id, "docx"), "_blank")}
                      >
                        DOCX
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => window.open(api.materialDownloadUrl(job.id, "pdf"), "_blank")}
                      >
                        PDF
                      </Button>
                    </>
                  }
                />
                <AutofillPlanBlock text={job.materials.autofill_notes} />
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
