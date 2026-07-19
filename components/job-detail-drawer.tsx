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
  UserRoundSearch,
  ClipboardCheck,
  FileSearch,
  Play,
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
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
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
import type { ApplicationSession, JobContact, JobPosting } from "@/lib/types"
import type { LLMFeedbackAction, LLMFeedbackArtifact } from "@/lib/types"
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

function materialReviewReasonLabel(reason: string): string {
  if (reason === "materials_missing") return "Application materials have not been generated yet."
  if (reason === "ranking_requires_review") return "The ranking was flagged for review."
  if (reason === "ranking_low_confidence") return "Ranking confidence is low."
  if (reason === "ranking_not_actionable") return "Ranking decision is not an apply decision."
  if (reason === "recruiter_message_missing") return "Recruiter message is missing."
  if (reason === "ats_cv_missing") return "Optimized ATS CV is missing."
  if (reason === "ats_cv_too_short") return "Optimized ATS CV looks too short."
  if (reason === "autofill_notes_missing") return "Autofill notes are missing."
  if (reason.startsWith("ats_cv_contains_avoid_overclaiming_terms:")) {
    return `ATS CV includes avoid-overclaiming terms: ${reason.split(":", 2)[1]}`
  }
  return reason.replaceAll("_", " ")
}

function MaterialsReviewPanel({ job }: { job: JobPosting }) {
  const review = job.materials.review
  if (!review?.requires_review || review.status === "missing") return null
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs leading-relaxed text-warning-foreground">
      <div className="mb-1.5 flex items-center gap-1.5 font-semibold">
        <CircleAlert className="size-4" />
        Review generated materials before using them
      </div>
      <ul className="flex flex-col gap-1 pl-5">
        {review.reasons.map((reason) => (
          <li key={reason} className="list-disc">
            {materialReviewReasonLabel(reason)}
          </li>
        ))}
      </ul>
    </div>
  )
}

function MaterialsGenerationMeta({ job }: { job: JobPosting }) {
  const generation = job.materials.generation
  if (!generation?.provider && !generation?.model && !generation?.generated_at) return null
  const promptVersions = Object.entries(generation.prompt_versions || {})
  return (
    <div className="flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
      {generation.provider ? (
        <span className="rounded-md border border-border bg-muted/40 px-2 py-0.5">
          {generation.provider}
        </span>
      ) : null}
      {generation.model ? (
        <span className="rounded-md border border-border bg-muted/40 px-2 py-0.5">
          {generation.model}
        </span>
      ) : null}
      {generation.generated_at ? (
        <span className="rounded-md border border-border bg-muted/40 px-2 py-0.5">
          {generation.generated_at}
        </span>
      ) : null}
      {generation.validation_attempts && generation.validation_attempts > 1 ? (
        <span
          className="rounded-md border border-warning/30 bg-warning/10 px-2 py-0.5 text-warning-foreground"
          title={generation.validation_errors.join(" | ")}
        >
          {generation.validation_attempts} validation attempts
        </span>
      ) : null}
      {generation.candidate_profile_hash ? (
        <span className="rounded-md border border-border bg-muted/40 px-2 py-0.5">
          profile {generation.candidate_profile_hash.slice(0, 8)}
        </span>
      ) : null}
      {promptVersions.map(([target, version]) => (
        <span key={target} className="rounded-md border border-border bg-muted/40 px-2 py-0.5">
          {target.split("/").slice(-1)[0]} {version}
        </span>
      ))}
    </div>
  )
}

function FeedbackButtons({
  onFeedback,
}: {
  onFeedback: (action: LLMFeedbackAction) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <Button size="sm" variant="ghost" onClick={() => onFeedback("accepted")}>
        <CheckCircle2 data-icon="inline-start" />
        Good
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onFeedback("edited")}>
        <FileSearch data-icon="inline-start" />
        Edited
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onFeedback("rejected")}>
        <X data-icon="inline-start" />
        Wrong
      </Button>
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

function detectProvider(job: JobPosting) {
  const url = `${job.apply_url} ${job.external_apply_url ?? ""} ${job.url} ${job.source_raw ?? ""}`.toLowerCase()
  if (url.includes("greenhouse") || url.includes("grnh.se")) return "greenhouse"
  if (url.includes("lever.co")) return "lever"
  if (url.includes("ashbyhq")) return "ashby"
  if (url.includes("workday")) return "workday"
  return "generic"
}

function primaryActionLabel(session: ApplicationSession | null, job: JobPosting) {
  if (!session) return job.materials.ats_cv_notes ? "Prepare application" : "Prepare materials"
  if (session.state === "needs_user_input") return `Resolve ${session.unknown_fields_json.length || "missing"} fields`
  if (session.state === "ready_for_review") return "Review and apply"
  if (["created", "preflight", "preparing_materials", "ready_to_fill", "filling"].includes(session.state)) {
    return "Continue application"
  }
  if (session.state === "submitted") return "Verify submission"
  return "Continue application"
}

function SessionReview({
  session,
  onContinue,
  busy,
}: {
  session: ApplicationSession
  onContinue: () => void
  busy: boolean
}) {
  const unknown = session.unknown_fields_json ?? []
  const answers = Array.isArray(session.mapped_answers_json?.answers)
    ? session.mapped_answers_json.answers
    : []
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <ClipboardCheck className="size-4 text-primary" />
          Application session
        </h3>
        <Badge variant="outline">{session.state.replaceAll("_", " ")}</Badge>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-md border border-border bg-background/70 p-2">
          <span className="block text-muted-foreground">Provider</span>
          <span className="font-semibold text-foreground">{session.provider}</span>
        </div>
        <div className="rounded-md border border-border bg-background/70 p-2">
          <span className="block text-muted-foreground">Fields</span>
          <span className="font-semibold text-foreground">{session.fields_autofilled}/{session.fields_detected}</span>
        </div>
        <div className="rounded-md border border-border bg-background/70 p-2">
          <span className="block text-muted-foreground">Clicks</span>
          <span className="font-semibold text-foreground">{session.user_clicks}</span>
        </div>
      </div>
      {unknown.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold text-foreground">Needs input</p>
          <div className="flex flex-wrap gap-1.5">
            {unknown.map((field, index) => (
              <Badge key={`${String(field.name ?? field.label ?? "field")}-${index}`} variant="destructive">
                {String(field.label ?? field.name ?? "Unknown field")}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
      {answers.length > 0 ? (
        <details className="rounded-md border border-border bg-background/70 p-2">
          <summary className="cursor-pointer text-xs font-semibold text-foreground">Mapped answers</summary>
          <div className="mt-2 flex flex-col gap-1.5">
            {answers.slice(0, 8).map((answer, index) => (
              <div key={`${String(answer.field_name ?? index)}`} className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                <span className="font-medium text-foreground">{String(answer.field_name ?? "field")}</span>
                <span className="text-muted-foreground"> - {answer.requires_confirmation ? "needs review" : "ready"}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {session.state === "needs_user_input" ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background/70 p-2">
          <p className="text-xs text-muted-foreground">
            Resolve the manual step in the company page, then continue the same session.
          </p>
          <Button size="sm" variant="outline" disabled={busy} onClick={onContinue}>
            <Play data-icon="inline-start" />
            Continue after manual step
          </Button>
        </div>
      ) : null}
    </section>
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
  const [applicationOperationId, setApplicationOperationId] = useState<number | null>(null)
  const [contacts, setContacts] = useState<JobContact[]>([])
  const [sessions, setSessions] = useState<ApplicationSession[]>([])
  const [sessionBusy, setSessionBusy] = useState(false)
  const [dryRunHtml, setDryRunHtml] = useState("")
  const [showDryRunInput, setShowDryRunInput] = useState(false)
  const { evidence } = job.ranking
  const applicants = applicantLabel(job)
  const salary = salaryLabel(job)
  const [showAllHiringContacts, setShowAllHiringContacts] = useState(false)
  const hiringContacts = job.hiring_contacts ?? []
  const visibleHiringContacts = showAllHiringContacts ? hiringContacts : hiringContacts.slice(0, 3)
  const companyHistory = applications.filter(
    (application) => application.company?.toLowerCase() === job.company.toLowerCase(),
  )
  const jobContacts = contacts.filter((contact) => {
    const sameJob = contact.job_id === Number(job.id)
    const sameCompany = (contact.company || "").toLowerCase() === job.company.toLowerCase()
    return sameJob || sameCompany
  })
  const recruiterCandidates = [
    ...(job.recruiter_name
      ? [{
          id: -1,
          name: job.recruiter_name,
          role: "Job poster",
          linkedin_url: job.recruiter_profile_url,
          source: "linkedin_scraper" as const,
        }]
      : []),
    ...jobContacts,
  ]
  const latestSession = sessions[0] ?? null
  const provider = detectProvider(job)

  async function recordFeedback(artifact: LLMFeedbackArtifact, action: LLMFeedbackAction) {
    try {
      await api.recordLlmFeedback(job.id, {
        artifact_type: artifact,
        action,
        metadata: { ui_surface: "job_detail_drawer" },
      })
      toast.success("Feedback recorded", {
        description: `${artifact.replaceAll("_", " ")} marked ${action}.`,
      })
    } catch (e) {
      toast.error("Could not record feedback", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    }
  }

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

  useEffect(() => {
    if (!applicationOperationId) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const response = await api.getOperation(applicationOperationId)
        if (stopped) return
        if (response.operation.status === "completed") {
          const sessionsResponse = await api.getApplicationSessions(job.id)
          if (!stopped) {
            setSessions(sessionsResponse.sessions)
            setApplicationOperationId(null)
            toast.success("Application dry-run ready", { description: job.title })
          }
          return
        }
        if (response.operation.status === "failed") {
          setApplicationOperationId(null)
          toast.error("Application dry-run failed", {
            description: response.operation.error ?? "Check local worker logs.",
          })
          return
        }
        timer = window.setTimeout(poll, 2500)
      } catch (e) {
        if (!stopped) {
          setApplicationOperationId(null)
          toast.error("Could not check application dry-run", {
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
  }, [applicationOperationId, job.id, job.title])

  useEffect(() => {
    let cancelled = false
    async function loadContacts() {
      try {
        const response = await api.getContacts()
        if (!cancelled) setContacts(response.contacts)
      } catch {
        if (!cancelled) setContacts([])
      }
    }
    void loadContacts()
    return () => {
      cancelled = true
    }
  }, [job.id])

  useEffect(() => {
    let cancelled = false
    async function loadSessions() {
      try {
        const response = await api.getApplicationSessions(job.id)
        if (!cancelled) setSessions(response.sessions)
      } catch {
        if (!cancelled) setSessions([])
      }
    }
    void loadSessions()
    return () => {
      cancelled = true
    }
  }, [job.id])

  async function prepareApplication(html?: string) {
    if (latestSession && !html) {
      if (latestSession.state === "needs_user_input") {
        setShowDryRunInput(true)
        toast("Resolve missing fields", { description: `${latestSession.unknown_fields_json.length} fields need review.` })
        return
      }
      toast("Application session loaded", { description: latestSession.state.replaceAll("_", " ") })
      return
    }
    setSessionBusy(true)
    try {
      if (!job.materials.ats_cv_notes) {
        const result = await generateMaterials(job.id, "heuristic")
        if (result.operation_id) setMaterialsOperationId(result.operation_id)
      }
      const response = await api.createApplicationSession(job.id, {
        provider,
        mode: "review_before_submit",
        html,
        dry_run: true,
      })
      if (response.operation_id) {
        setApplicationOperationId(response.operation_id)
        toast.success("Browser dry-run queued", { description: "Keep the local worker running; the API can stay on v0." })
      }
      setSessions((prev) => [response.session, ...prev.filter((item) => item.id !== response.session.id)])
      if (response.session.state === "needs_user_input") {
        toast.warning("Application needs input", { description: `${response.session.unknown_fields_json.length} fields need review.` })
      } else {
        toast.success("Application session ready", { description: response.session.state.replaceAll("_", " ") })
      }
      await refresh()
    } catch (e) {
      toast.error("Could not prepare application", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setSessionBusy(false)
    }
  }

  async function continueApplicationSession() {
    if (!latestSession) return
    setSessionBusy(true)
    try {
      const response = await api.continueApplicationSession(latestSession.id)
      if (response.operation_id) {
        setApplicationOperationId(response.operation_id)
        toast.success("Continuation queued", { description: "The local worker will inspect the page again." })
      }
      setSessions((prev) => [response.session, ...prev.filter((item) => item.id !== response.session.id)])
    } catch (e) {
      toast.error("Could not continue session", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setSessionBusy(false)
    }
  }

  function openExternal(url: string) {
    markOpened(job.id)
    window.open(url, "_blank", "noopener,noreferrer")
  }

  async function copyRecruiterMessage() {
    await navigator.clipboard.writeText(job.materials.recruiter_message)
    toast.success("Recruiter message copied")
  }

  function openRecruiterSearch(spainOnly: boolean) {
    const query = spainOnly
      ? `site:linkedin.com/in recruiter ${job.company} Spain`
      : `site:linkedin.com/in recruiter ${job.company}`
    window.open(`https://www.google.com/search?q=${encodeURIComponent(query)}`, "_blank", "noopener,noreferrer")
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
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-foreground">{primaryActionLabel(latestSession, job)}</p>
              <p className="text-xs text-muted-foreground">
                {provider === "greenhouse" ? "Greenhouse dry-run supported." : "Assisted mode for this provider."}
              </p>
            </div>
            <Button size="sm" disabled={sessionBusy} onClick={() => void prepareApplication()}>
              <Play data-icon="inline-start" />
              {primaryActionLabel(latestSession, job)}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => openExternal(job.url)}>
              <ExternalLink data-icon="inline-start" />
              Open posting
            </Button>
            <Button size="sm" variant="outline" onClick={() => openExternal(applyUrlForJob(job))}>
              <Send data-icon="inline-start" />
              Open apply page
            </Button>
            <Button size="sm" variant="outline" onClick={() => setShowDryRunInput((value) => !value)}>
              <FileSearch data-icon="inline-start" />
              Greenhouse dry-run
            </Button>
          </div>
          {showDryRunInput ? (
            <div className="flex flex-col gap-2">
              <Textarea
                value={dryRunHtml}
                onChange={(event) => setDryRunHtml(event.target.value)}
                placeholder="Paste Greenhouse form HTML here for a local dry-run review."
                className="min-h-28 text-xs"
              />
              <Button
                size="sm"
                disabled={sessionBusy || dryRunHtml.trim().length < 20}
                onClick={() => void prepareApplication(dryRunHtml)}
              >
                <FileSearch data-icon="inline-start" />
                Run dry-run review
              </Button>
            </div>
          ) : null}
        </div>

        {latestSession ? (
          <SessionReview
            session={latestSession}
            busy={sessionBusy}
            onContinue={() => void continueApplicationSession()}
          />
        ) : null}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">
              Recommendation
            </h3>
            <FeedbackButtons onFeedback={(action) => void recordFeedback("ranking", action)} />
          </div>
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
              title="Review reasons"
              items={evidence.llm_escalation_reasons}
              icon={CircleAlert}
              tone="text-warning-foreground"
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

        {hiringContacts.length > 0 ? (
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-foreground">Hiring team</h3>
              {hiringContacts.length > 3 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAllHiringContacts((value) => !value)}
                >
                  {showAllHiringContacts ? "Show less" : "Show all"}
                </Button>
              ) : null}
            </div>
            <div className="flex flex-col gap-2">
              {visibleHiringContacts.map((contact) => (
                <div
                  key={`${contact.profile_url}-${contact.name}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-3"
                >
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <p className="max-w-full truncate text-xs font-semibold text-foreground">
                        {contact.name}
                      </p>
                      {contact.is_primary ? (
                        <span className="rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground">
                          Primary contact
                        </span>
                      ) : null}
                    </div>
                    {contact.headline ? (
                      <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {contact.headline}
                      </p>
                    ) : null}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() => window.open(contact.profile_url, "_blank", "noopener,noreferrer")}
                  >
                    <ExternalLink data-icon="inline-start" />
                    LinkedIn
                  </Button>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">Recruiter contact strategy</h3>
          <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs leading-relaxed text-muted-foreground">
            <p className="font-medium text-foreground">
              Best path: apply with the least friction, then message the job poster. If there is no poster, contact a company recruiter, preferably Spain-based for Spain roles.
            </p>
            <p className="mt-2">
              CV emphasis: {job.ranking.cv_keywords_to_emphasize.slice(0, 6).join(", ") || "No keyword guidance available."}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => openRecruiterSearch(true)}>
                <UserRoundSearch data-icon="inline-start" />
                Spain recruiters
              </Button>
              <Button variant="outline" size="sm" onClick={() => openRecruiterSearch(false)}>
                <UserRoundSearch data-icon="inline-start" />
                Company recruiters
              </Button>
              {job.materials.recruiter_message ? (
                <Button variant="outline" size="sm" onClick={() => void copyRecruiterMessage()}>
                  <Copy data-icon="inline-start" />
                  Copy recruiter note
                </Button>
              ) : null}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {recruiterCandidates.length ? recruiterCandidates.map((contact) => (
              <div key={`${contact.id}-${contact.name}`} className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 p-3">
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-foreground">{contact.name || "Recruiter"}</p>
                  <p className="truncate text-xs text-muted-foreground">{contact.role || "Recruiter"}{contact.source === "linkedin_scraper" ? " - scraped" : ""}</p>
                </div>
                {contact.linkedin_url ? (
                  <Button variant="outline" size="sm" onClick={() => window.open(contact.linkedin_url || "", "_blank", "noopener,noreferrer")}>
                    <UserRoundSearch data-icon="inline-start" />
                    LinkedIn
                  </Button>
                ) : null}
              </div>
            )) : (
              <div className="rounded-lg border border-dashed border-border bg-muted/20 p-3 text-xs text-muted-foreground">
                No recruiter saved yet. After applying, search LinkedIn for a recruiter at {job.company}; for Spain roles, prioritize Spain-based recruiters.
              </div>
            )}
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
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground">
                  Application materials
                </h3>
                <FeedbackButtons onFeedback={(action) => void recordFeedback("application_materials", action)} />
              </div>
              <MaterialsGenerationMeta job={job} />
              <MaterialsReviewPanel job={job} />
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
