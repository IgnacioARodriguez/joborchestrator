"use client"

import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
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
  Pencil,
  Save,
  LoaderCircle,
} from "lucide-react"
import { toast } from "sonner"
import {
  Dialog,
} from "@base-ui/react/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { DecisionBadge } from "@/components/badges"
import { ScoreRing } from "@/components/badges"
import { AsyncActionButton, TaskProgressCard } from "@/components/task-progress-card"
import { ApplicationAssistantDialog } from "@/components/application-assistant-dialog"
import { useStore } from "@/lib/store"
import { userFacingError } from "@/lib/user-facing-error"
import { api } from "@/lib/api"
import { friendlyApplicationProgress } from "@/lib/application-assistant"
import {
  applicantLabel,
  applyUrlForJob,
  PIPELINE_LABELS,
  rankingSummaryText,
  salaryLabel,
} from "@/lib/job-ui"
import type { ApplicationRecord, ApplicationSession, JobContact, JobPosting, ProviderCapabilities } from "@/lib/types"
import type { LLMFeedbackAction, LLMFeedbackArtifact } from "@/lib/types"
import { cn } from "@/lib/utils"

type DetailActions = Pick<
  ReturnType<typeof useStore>,
  "setPipelineStatus" | "markOpened" | "generateMaterials" | "refreshApplications" | "loadJobDetail"
>

type MaterialKey = "ats_cv" | "cover_letter" | "recruiter_message" | "autofill"

function DeferredSection({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={cn(
        "[content-visibility:auto] [contain-intrinsic-size:auto_300px]",
        className,
      )}
    >
      {children}
    </section>
  )
}

function LazyDetails({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  const [mounted, setMounted] = useState(false)

  return (
    <details
      className="rounded-lg border border-border bg-muted/20 p-3 [content-visibility:auto] [contain-intrinsic-size:auto_260px]"
      onToggle={(event) => {
        if (event.currentTarget.open) setMounted(true)
      }}
    >
      <summary className="cursor-pointer text-sm font-semibold text-foreground">
        {title}
      </summary>
      {mounted ? children : null}
    </details>
  )
}

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
  onSave,
  reviewState,
  onApprove,
}: {
  label: string
  text: string
  actions?: ReactNode
  onSave?: (value: string) => Promise<void>
  reviewState?: string
  onApprove?: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)

  if (!text) return null
  async function copyText() {
    await navigator.clipboard.writeText(text)
    toast.success("Copied", { description: label })
  }
  async function saveText() {
    if (!onSave) return
    setSaving(true)
    try {
      await onSave(draft)
      setEditing(false)
      toast.success("Saved", { description: label })
    } catch (error) {
      toast.error("Could not save", {
        description: userFacingError(error),
      })
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">{label}</p>
        <div className="flex flex-wrap justify-end gap-1">
          {actions}
          {onApprove && reviewState !== "approved" ? (
            <AsyncActionButton variant="ghost" size="sm" pending={approving} pendingLabel="Aprobando…" onClick={async () => { setApproving(true); try { await onApprove() } finally { setApproving(false) } }}>
              <CheckCircle2 data-icon="inline-start" />
              Aprobar
            </AsyncActionButton>
          ) : null}
          {onSave ? (
            editing ? (
              <Button variant="ghost" size="sm" disabled={saving} onClick={() => void saveText()}>
                <Save data-icon="inline-start" />
                Save
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft(text)
                  setEditing(true)
                }}
              >
                <Pencil data-icon="inline-start" />
                Edit
              </Button>
            )
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => void copyText()}>
            <Copy data-icon="inline-start" />
            Copy
          </Button>
        </div>
      </div>
      {editing ? (
        <Textarea
          aria-label={label}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="min-h-36 text-xs leading-relaxed"
        />
      ) : (
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
          {text}
        </p>
      )}
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

function rankingReviewReasonLabel(reason: string): string {
  if (reason === "ranking_missing") return "This job has not been ranked yet."
  if (reason === "ranking_requires_llm_review") return "The ranking model flagged this for review."
  if (reason === "ranking_low_confidence") return "Ranking confidence is low."
  if (reason === "ranking_validation_retry") return "The ranking needed validation retry before saving."
  if (reason === "ranking_thin_positive_evidence") return "Apply recommendation has thin positive evidence."
  if (reason === "ranking_missing_central_requirements") return "Central requirement evidence is missing."
  return reason.replaceAll("_", " ")
}

function RankingReviewPanel({ job }: { job: JobPosting }) {
  const review = job.ranking.review
  if (!review?.requires_review || review.status === "missing") return null
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs leading-relaxed text-warning-foreground">
      <div className="mb-1.5 flex items-center gap-1.5 font-semibold">
        <CircleAlert className="size-4" />
        Review ranking before acting
      </div>
      <ul className="flex flex-col gap-1 pl-5">
        {review.reasons.map((reason) => (
          <li key={reason} className="list-disc">
            {rankingReviewReasonLabel(reason)}
          </li>
        ))}
      </ul>
    </div>
  )
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
    <details className="rounded-md border border-border bg-muted/20 px-2 py-1">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Valorar
      </summary>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => onFeedback("accepted")}>
          <CheckCircle2 data-icon="inline-start" />
          Correcto
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onFeedback("edited")}>
          <FileSearch data-icon="inline-start" />
          Editado
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onFeedback("rejected")}>
          <X data-icon="inline-start" />
          Incorrecto
        </Button>
      </div>
    </details>
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

function AutofillPlanBlock({
  text,
  onSave,
  reviewState,
  onApprove,
}: {
  text: string
  onSave: (value: string) => Promise<void>
  reviewState?: string
  onApprove?: () => Promise<void>
}) {
  const plan = parseAutofillPlan(text)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const [saving, setSaving] = useState(false)
  if (!plan) {
    return (
      <MaterialBlock
        label="Autofill notes"
        text={text}
        onSave={onSave}
        reviewState={reviewState}
        onApprove={onApprove}
      />
    )
  }

  const copyText = async (label: string, value: string) => {
    await navigator.clipboard.writeText(value)
    toast.success("Copied", { description: label })
  }

  async function saveText() {
    setSaving(true)
    try {
      await onSave(draft)
      setEditing(false)
      toast.success("Saved", { description: "Autofill notes" })
    } catch (error) {
      toast.error("Could not save", {
        description: error instanceof Error ? error.message : "Backend request failed.",
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">
          Application workflow
        </p>
        <div className="flex flex-wrap justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraft(text)
              setEditing(true)
            }}
          >
            <Pencil data-icon="inline-start" />
            Edit
          </Button>
          {onApprove && reviewState !== "approved" ? (
            <Button variant="ghost" size="sm" onClick={() => void onApprove()}>
              <CheckCircle2 data-icon="inline-start" />
              Aprobar
            </Button>
          ) : null}
          {editing ? (
            <Button variant="ghost" size="sm" disabled={saving} onClick={() => void saveText()}>
              <Save data-icon="inline-start" />
              Save
            </Button>
          ) : null}
          {plan.copy_paste_block && (
            <Button
              variant="ghost"
              size="sm"
              disabled={saving}
              onClick={() => void copyText("Application answers", plan.copy_paste_block ?? "")}
            >
              <Copy data-icon="inline-start" />
              Copy answers
            </Button>
          )}
        </div>
      </div>
      {editing ? (
        <Textarea
          aria-label="Autofill notes"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="min-h-36 text-xs leading-relaxed"
        />
      ) : null}
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
  if (!session) return job.materials.ats_cv_notes ? "Preparar postulación" : "Preparar materiales"
  if (session.state === "needs_user_input") return session.unknown_fields_json.length ? `Resolver ${session.unknown_fields_json.length} campos` : "Resolver campos pendientes"
  if (session.state === "submit_only") return "Listo para enviar"
  if (session.state === "ready_for_review") return "Listo para revisión final"
  if (["created", "preparing", "preflight", "preparing_materials", "materials_ready", "opened", "ready_to_fill", "filling", "prefilled"].includes(session.state)) {
    return "Continuar preparación"
  }
  if (session.state === "submitted_manually") return "Verificar confirmación"
  if (session.state === "submission_verified") return "Postulación verificada"
  if (session.state === "submitted") return "Verificar confirmación"
  return "Continuar preparación"
}


function compactUnique(items: Array<string | null | undefined>, limit: number) {
  const seen = new Set<string>()
  const values: string[] = []

  for (const item of items) {
    const value = item?.trim()
    if (!value) continue

    const key = value.toLowerCase()
    if (seen.has(key)) continue

    seen.add(key)
    values.push(value)
    if (values.length === limit) break
  }

  return values
}

function fitReasonsFor(job: JobPosting) {
  const { evidence } = job.ranking
  return compactUnique(
    [
      ...evidence.strong_matches,
      ...evidence.partial_matches,
      rankingSummaryText(
        job.ranking.decision,
        job.ranking.final_score,
        job.ranking.reasoning_summary,
      ),
    ],
    4,
  )
}

function recommendationsFor(job: JobPosting) {
  const keywords = job.ranking.cv_keywords_to_emphasize.slice(0, 4)
  return compactUnique(
    [
      ...job.ranking.evidence.missing_requirements.map(
        (item) => `Revisar antes de aplicar: ${item}`,
      ),
      ...job.ranking.evidence.red_flags.map(
        (item) => `Validar antes de aplicar: ${item}`,
      ),
      job.ranking.recommended_application_angle,
      keywords.length ? `Destacar en el CV: ${keywords.join(", ")}` : null,
    ],
    3,
  )
}

function materialStatus(text: string, reviewState?: string) {
  if (!text) {
    return {
      label: "Pendiente",
      tone: "border-border bg-muted text-muted-foreground",
    }
  }
  if (reviewState && reviewState !== "approved") {
    return {
      label: "Revisar",
      tone: "border-warning/30 bg-warning/10 text-warning-foreground",
    }
  }
  return {
    label: "Listo",
    tone: "border-success/25 bg-success/10 text-success-foreground",
  }
}

const CAPABILITY_LABELS: Array<[keyof ProviderCapabilities, string]> = [
  ["can_open_application", "Open application"],
  ["can_follow_apply_redirects", "Follow apply redirects"],
  ["can_detect_fields", "Detect fields"],
  ["can_fill_text_fields", "Fill text fields"],
  ["can_fill_selects", "Fill selects"],
  ["can_fill_radios", "Fill radios"],
  ["can_fill_checkboxes", "Fill checkboxes"],
  ["can_upload_resume", "Upload resume"],
  ["can_prepare_custom_answers", "Prepare custom answers"],
  ["can_resume_browser_session", "Resume browser session"],
  ["can_submit", "Automatic submit"],
]

function ProviderCapabilityList({ capabilities }: { capabilities: ProviderCapabilities | null }) {
  if (!capabilities) return null
  return (
    <div className="grid grid-cols-1 gap-1.5 text-xs sm:grid-cols-2">
      {CAPABILITY_LABELS.map(([key, label]) => {
        const supported = Boolean(capabilities[key])
        return (
          <div key={key} className="flex items-center gap-1.5 rounded-md border border-border bg-background/70 px-2 py-1">
            {supported ? (
              <CheckCircle2 className="size-3.5 text-success" />
            ) : (
              <CircleX className="size-3.5 text-muted-foreground" />
            )}
            <span className={supported ? "text-foreground" : "text-muted-foreground"}>{label}</span>
          </div>
        )
      })}
    </div>
  )
}

function SessionReview({
  session,
  onContinue,
  onMarkSubmitted,
  busy,
  capabilities,
}: {
  session: ApplicationSession
  onContinue: () => void
  onMarkSubmitted: () => void
  busy: boolean
  capabilities: ProviderCapabilities | null
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
      <ProviderCapabilityList capabilities={capabilities} />
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
      {["submit_only", "ready_for_review", "needs_user_input"].includes(session.state) ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background/70 p-2">
          <p className="text-xs text-muted-foreground">
            Review the company page yourself. The app records the outcome only after you confirm it.
          </p>
          <Button size="sm" variant="outline" disabled={busy} onClick={onMarkSubmitted}>
            <ClipboardCheck data-icon="inline-start" />
            Mark submitted manually
          </Button>
        </div>
      ) : null}
    </section>
  )
}


function SimpleApplicationStatus({
  job,
  session,
  busy,
  onOpenAssistant,
  onOpenPortal,
}: {
  job: JobPosting
  session: ApplicationSession
  busy: boolean
  onOpenAssistant: () => void
  onOpenPortal: () => void
}) {
  const needsManualStep = session.state === "needs_user_input"
  const readyForReview = ["submit_only", "ready_for_review"].includes(session.state)
  const completed = ["submitted", "submitted_manually", "submission_verified"].includes(
    session.state,
  )
  const unknownCount = session.unknown_fields_json?.length ?? 0

  let description = "La automatización está preparando la postulación en el portal."
  if (needsManualStep) {
    description = unknownCount
      ? `El portal requiere que revises ${unknownCount} campo${unknownCount === 1 ? "" : "s"} antes de continuar.`
      : "El portal requiere un paso manual, como iniciar sesión o resolver una verificación."
  } else if (readyForReview) {
    description = "El formulario está preparado y requiere tu revisión antes del envío final."
  } else if (completed) {
    description = "La postulación quedó registrada en JobOrchestrator."
  }

  const statusLabel = completed
    ? "Completado"
    : needsManualStep
      ? "Necesita tu intervención"
      : readyForReview
        ? "Revisión final"
        : "En curso"

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <ClipboardCheck className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">
              {completed ? "Postulación registrada" : primaryActionLabel(session, job)}
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {description}
            </p>
          </div>
        </div>
        <Badge variant="outline">{statusLabel}</Badge>
      </div>

      {needsManualStep || readyForReview ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={onOpenAssistant}>
            <CircleAlert data-icon="inline-start" />
            Ver instrucciones
          </Button>
          <Button size="sm" variant="outline" onClick={onOpenPortal}>
            <ExternalLink data-icon="inline-start" />
            Abrir portal
          </Button>
        </div>
      ) : null}
    </section>
  )
}

const DetailBody = memo(function DetailBody({
  job,
  onClose,
  actions,
  companyHistory,
}: {
  job: JobPosting
  onClose: () => void
  actions: DetailActions
  companyHistory: ApplicationRecord[]
}) {
  const { setPipelineStatus, markOpened, generateMaterials, refreshApplications, loadJobDetail } = actions
  const scrollerRef = useRef<HTMLDivElement>(null)
  const [materialsOperationId, setMaterialsOperationId] = useState<number | null>(null)
  const [applicationOperationId, setApplicationOperationId] = useState<number | null>(null)
  const [applicationProgress, setApplicationProgress] = useState("")
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [contacts, setContacts] = useState<JobContact[]>([])
  const [sessions, setSessions] = useState<ApplicationSession[]>([])
  const [providerCapabilities, setProviderCapabilities] = useState<ProviderCapabilities | null>(null)
  const [sessionBusy, setSessionBusy] = useState(false)
  const automationBusy = sessionBusy || Boolean(materialsOperationId) || Boolean(applicationOperationId)
  const [dryRunHtml, setDryRunHtml] = useState("")
  const [showDryRunInput, setShowDryRunInput] = useState(false)
  const [showAiProviders, setShowAiProviders] = useState(false)
  const [activeMaterial, setActiveMaterial] = useState<MaterialKey | null>(null)
  const { evidence } = job.ranking
  const applicants = applicantLabel(job)
  const salary = salaryLabel(job)
  const [showAllHiringContacts, setShowAllHiringContacts] = useState(false)
  const hiringContacts = job.hiring_contacts ?? []
  const visibleHiringContacts = showAllHiringContacts ? hiringContacts : hiringContacts.slice(0, 3)
  const jobContacts = useMemo(
    () =>
      contacts.filter((contact) => {
        const sameJob = contact.job_id === Number(job.id)
        const sameCompany = (contact.company || "").toLowerCase() === job.company.toLowerCase()
        return sameJob || sameCompany
      }),
    [contacts, job.company, job.id],
  )
  const recruiterCandidates = useMemo(
    () => [
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
    ],
    [job.recruiter_name, job.recruiter_profile_url, jobContacts],
  )
  const latestSession = sessions[0] ?? null
  const provider = detectProvider(job)
  const fitReasons = fitReasonsFor(job)
  const recommendations = recommendationsFor(job)
  const applicationFinished = Boolean(
    latestSession &&
      ["submitted", "submitted_manually", "submission_verified"].includes(
        latestSession.state,
      ),
  )
  const materialCards = [
    {
      id: "ats_cv" as const,
      label: "CV ATS adaptado",
      text: job.materials.ats_cv_notes,
      icon: FileSearch,
      reviewState: job.materials.review.materials?.ats_cv,
    },
    {
      id: "cover_letter" as const,
      label: "Cover letter",
      text: job.materials.cover_letter,
      icon: Send,
      reviewState: job.materials.review.materials?.cover_letter,
    },
    {
      id: "recruiter_message" as const,
      label: "Recruiter message",
      text: job.materials.recruiter_message,
      icon: Copy,
      reviewState: job.materials.review.materials?.recruiter_message,
    },
    {
      id: "autofill" as const,
      label: "Autofill notes",
      text: job.materials.autofill_notes,
      icon: ClipboardCheck,
      reviewState: job.materials.review.materials?.autofill,
    },
  ]

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: 0 })
  }, [job.id])

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
          await loadJobDetail(job.id, { force: true })
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
  }, [job.id, job.title, loadJobDetail, materialsOperationId])

  useEffect(() => {
    if (!applicationOperationId) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const response = await api.getOperation(applicationOperationId)
        if (stopped) return
        setApplicationProgress(friendlyApplicationProgress(response.operation.progress_message))
        if (response.operation.status === "completed") {
          const sessionsResponse = await api.getApplicationSessions(job.id)
          if (!stopped) {
            setSessions(sessionsResponse.sessions)
            setApplicationOperationId(null)
            setApplicationProgress("")
            setAssistantOpen(true)
            toast.success("Automatización pausada", { description: "Revisá las instrucciones para continuar." })
          }
          return
        }
        if (response.operation.status === "failed") {
          setApplicationOperationId(null)
          setApplicationProgress("")
          toast.error("No se pudo preparar el formulario", {
            description: response.operation.error ?? "Revisa que el worker local este encendido.",
          })
          return
        }
        timer = window.setTimeout(poll, 2500)
      } catch (e) {
        if (!stopped) {
          setApplicationOperationId(null)
          toast.error("No se pudo consultar la preparacion", {
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
    async function loadCapabilities() {
      try {
        const response = await api.getProviderCapabilities(provider) as { provider: ProviderCapabilities }
        if (!cancelled) setProviderCapabilities(response.provider)
      } catch {
        if (!cancelled) setProviderCapabilities(null)
      }
    }
    void loadCapabilities()
    return () => {
      cancelled = true
    }
  }, [provider])

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
      if (
        ["submitted", "submitted_manually", "submission_verified"].includes(
          latestSession.state,
        )
      ) {
        toast("La postulación ya está registrada", { description: job.title })
        return
      }
      if (["submit_only", "ready_for_review"].includes(latestSession.state)) {
        setAssistantOpen(true)
        return
      }
      if (latestSession.state === "needs_user_input") {
        setAssistantOpen(true)
        return
      }

      await continueApplicationSession()
      return
    }
    setSessionBusy(true)
    try {
      if (!job.materials.ats_cv_notes) {
        const result = await generateMaterials(job.id, "heuristic")
        if (result.operation_id) {
          setMaterialsOperationId(result.operation_id)
          toast.success("Preparando candidatura", {
            description: "Primero generaremos los materiales. Cuando esten listos, volve a comenzar la aplicacion.",
          })
        }
        return
      }
      if (job.pipeline_status !== "ready_to_apply") {
        await setPipelineStatus(job.id, "ready_to_apply")
      }
      const response = await api.createApplicationSession(job.id, {
        provider,
        mode: "review_before_submit",
        html,
        dry_run: true,
      })
      if (response.operation_id) {
        setApplicationOperationId(response.operation_id)
        setApplicationProgress("Abriendo el portal de la empresa...")
        setAssistantOpen(true)
        toast.success("Automatización iniciada", {
          description: "El asistente local intentará abrir el portal y completar los campos seguros.",
        })
      }
      setSessions((prev) => [response.session, ...prev.filter((item) => item.id !== response.session.id)])
      if (response.session.state === "needs_user_input") {
        toast.warning("Necesitamos tu ayuda", {
          description: "Completa el paso pendiente en la ventana de aplicacion y luego continua la misma sesion.",
        })
      }
      await Promise.all([loadJobDetail(job.id, { force: true }), refreshApplications()])
    } catch (e) {
      toast.error("No se pudo preparar la postulación", {
        description: userFacingError(e),
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
        setApplicationProgress("Revisando nuevamente el formulario...")
        setAssistantOpen(true)
        toast.success("Continuando postulación", { description: "El asistente local volverá a revisar la misma sesión." })
      }
      setSessions((prev) => [response.session, ...prev.filter((item) => item.id !== response.session.id)])
    } catch (e) {
      toast.error("No se pudo continuar la sesión", {
        description: userFacingError(e),
      })
    } finally {
      setSessionBusy(false)
    }
  }

  async function markSubmittedManually() {
    if (!latestSession) return
    setSessionBusy(true)
    try {
      const response = await api.markApplicationSubmittedManually(latestSession.id)
      setSessions((prev) => [response.session, ...prev.filter((item) => item.id !== response.session.id)])
      await Promise.all([loadJobDetail(job.id, { force: true }), refreshApplications()])
      toast.success("Manual submission recorded", { description: job.title })
    } catch (e) {
      toast.error("Could not record manual submission", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setSessionBusy(false)
    }
  }

  async function saveMaterial(
    field: "recruiter_message" | "cover_letter" | "ats_cv_notes" | "autofill_notes",
    value: string,
  ) {
    await api.updateMaterials(job.id, { [field]: value })
    await loadJobDetail(job.id, { force: true })
  }

  async function approveMaterial(material: "ats_cv" | "cover_letter" | "recruiter_message" | "autofill") {
    await api.updateMaterialReview(job.id, { material, status: "approved" })
    await loadJobDetail(job.id, { force: true })
    toast.success("Material aprobado")
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
    <div
      ref={scrollerRef}
      data-base-ui-swipe-ignore
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
    >
      <div className="flex flex-col gap-5 bg-white p-5 text-[#17233d] sm:p-8">
        <section className="flex flex-col gap-6 rounded-2xl border-0 bg-white p-0 shadow-none">
          <div className="grid gap-5 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-center">
            <div className="flex flex-col items-center gap-1">
              <ScoreRing score={job.ranking.final_score} size={140} />
              <span className="-mt-10 text-sm font-semibold text-[#269667]">
                Match{" "}
                {job.ranking.final_score >= 85
                  ? "excelente"
                  : job.ranking.final_score >= 70
                    ? "alto"
                    : "moderado"}
              </span>
            </div>

            <div className="min-w-0">
              <h2 className="pr-8 text-pretty text-2xl font-bold leading-tight tracking-[-0.02em] text-[#17233d] sm:text-[30px]">
                {job.title}
              </h2>

              <div className="mt-4 flex flex-wrap gap-2 text-sm text-[#526078]">
                <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5">
                  <Building2 className="size-4 text-[#526078]" />
                  {job.company}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5">
                  <MapPin className="size-4 text-[#526078]" />
                  {job.location}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5">
                  <Radio className="size-4 text-[#526078]" />
                  {job.source}
                </span>
                {applicants ? (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5">
                  <Users className="size-4 text-[#526078]" />
                    {applicants}
                  </span>
                ) : null}
                {salary ? (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5">
                  <WalletCards className="size-4 text-[#526078]" />
                    {salary}
                  </span>
                ) : null}
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <DecisionBadge
                  decision={job.ranking.decision}
                  score={job.ranking.final_score}
                />
                {job.pipeline_status === "ready_to_apply" ? (
                  <Badge
                    variant="outline"
                    className="border-success/25 bg-success/10 text-success-foreground"
                  >
                    <CheckCircle2 className="size-3.5" />
                    Visible en Aplicar
                  </Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={sessionBusy}
                    onClick={async () => {
                      const updated = await setPipelineStatus(
                        job.id,
                        "ready_to_apply",
                      )
                      if (updated) {
                        toast.success("Guardado para aplicar", {
                          description: job.title,
                        })
                      } else {
                        toast.error("No se pudo guardar para aplicar")
                      }
                    }}
                  >
                    <CheckCircle2 data-icon="inline-start" />
                    Guardar para aplicar
                  </Button>
                )}
              </div>
            </div>
          </div>

          {automationBusy ? <TaskProgressCard title={applicationOperationId ? "Preparando la postulación" : "Generando materiales"} description={applicationOperationId ? "Revisando el portal y preparando el formulario." : "Preparando los materiales de la candidatura."} steps={[{ label: "Preparando datos y materiales", state: materialsOperationId ? "active" : "done" }, { label: "Revisando el portal y el formulario", state: applicationOperationId ? "active" : "pending" }, { label: "Preparando la revisión final", state: "pending" }]} /> : null}

          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Button
              className="h-14 rounded-lg bg-[#315bea] text-base font-semibold shadow-[0_5px_12px_rgba(49,91,234,.18)] hover:bg-[#264dcc]"
              disabled={automationBusy || applicationFinished}
              onClick={() => void prepareApplication()}
            >
              <Sparkles data-icon="inline-start" />
              {applicationFinished
                ? "Postulación completada"
                : "Aplicar automáticamente"}
            </Button>
            <Button
              className="h-14 rounded-lg border-[#d8dee9] bg-white text-base font-semibold text-[#17233d] hover:bg-[#f7f9fc]"
              variant="outline"
              onClick={() => openExternal(job.url)}
            >
              <ExternalLink data-icon="inline-start" />
              Ver oferta
            </Button>
            <Button
              className="h-14 rounded-lg px-4 text-base font-semibold text-[#315bea] hover:bg-[#eef3ff]"
              variant="ghost"
              onClick={() => openExternal(applyUrlForJob(job))}
            >
              <Send data-icon="inline-start" />
              Abrir manualmente
            </Button>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <section className="rounded-2xl border border-[#dfe5ee] bg-white p-5">
              <div className="flex items-center gap-2">
                <Target className="size-6 text-[#2aa574]" />
                <h3 className="text-base font-bold text-[#17233d]">
                  Por qué encaja
                </h3>
              </div>
              <ul className="mt-3 flex flex-col gap-2">
                {fitReasons.map((reason) => (
                  <li
                    key={reason}
                    className="flex items-start gap-2 text-sm leading-relaxed text-[#526078]"
                  >
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 rounded-full bg-[#dff4eb] p-0.5 text-[#2aa574]" />
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="rounded-2xl border border-[#dfe5ee] bg-white p-5">
              <div className="flex items-center gap-2">
                <Lightbulb className="size-6 text-[#315bea]" />
                <h3 className="text-base font-bold text-[#17233d]">
                  Recomendaciones
                </h3>
              </div>
              <ul className="mt-3 flex flex-col gap-2">
                {recommendations.map((recommendation) => (
                  <li
                    key={recommendation}
                    className="flex items-start gap-2 text-sm leading-relaxed text-[#526078]"
                  >
                    <CircleDot className="mt-1 size-2 shrink-0 fill-[#315bea] text-[#315bea]" />
                    <span>{recommendation}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="rounded-2xl border border-[#dfe5ee] bg-white p-5">
            <div className="flex items-center gap-2">
              <FileSearch className="size-6 text-[#315bea]" />
              <h3 className="text-base font-bold text-[#17233d]">
                Materiales generados
              </h3>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {materialCards.map((material) => {
                const Icon = material.icon
                const status = materialStatus(material.text, material.reviewState)
                const selected = activeMaterial === material.id
                return (
                  <button
                    key={material.id}
                    type="button"
                    disabled={!material.text}
                    aria-pressed={selected}
                    onClick={() =>
                      setActiveMaterial((current) =>
                        current === material.id ? null : material.id,
                      )
                    }
                    className={cn(
                      "flex min-h-20 flex-col items-start justify-between gap-3 rounded-lg border border-border bg-card p-3 text-left transition-colors",
                      material.text &&
                        "hover:border-primary/40 hover:bg-primary/5",
                      selected && "border-primary/40 bg-primary/5",
                      !material.text && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <span className="flex items-center gap-2 text-xs font-semibold text-foreground">
                      <Icon className="size-4 text-primary" />
                      {material.label}
                    </span>
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                        status.tone,
                      )}
                    >
                      {status.label}
                    </span>
                  </button>
                )
              })}
            </div>

            {activeMaterial ? (
              <div className="mt-3">
                {activeMaterial === "ats_cv" ? (
                  <MaterialBlock
                    label="CV ATS adaptado"
                    text={job.materials.ats_cv_notes}
                    onSave={(value) => saveMaterial("ats_cv_notes", value)}
                    reviewState={job.materials.review.materials?.ats_cv}
                    onApprove={() => approveMaterial("ats_cv")}
                    actions={
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            window.open(
                              api.materialDownloadUrl(job.id, "docx"),
                              "_blank",
                            )
                          }
                        >
                          DOCX
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            window.open(
                              api.materialDownloadUrl(job.id, "pdf"),
                              "_blank",
                            )
                          }
                        >
                          PDF
                        </Button>
                      </>
                    }
                  />
                ) : null}
                {activeMaterial === "cover_letter" ? (
                  <MaterialBlock
                    label="Cover letter"
                    text={job.materials.cover_letter}
                    onSave={(value) => saveMaterial("cover_letter", value)}
                    reviewState={job.materials.review.materials?.cover_letter}
                    onApprove={() => approveMaterial("cover_letter")}
                  />
                ) : null}
                {activeMaterial === "recruiter_message" ? (
                  <MaterialBlock
                    label="Recruiter message"
                    text={job.materials.recruiter_message}
                    onSave={(value) => saveMaterial("recruiter_message", value)}
                    reviewState={
                      job.materials.review.materials?.recruiter_message
                    }
                    onApprove={() => approveMaterial("recruiter_message")}
                  />
                ) : null}
                {activeMaterial === "autofill" ? (
                  <AutofillPlanBlock
                    text={job.materials.autofill_notes}
                    onSave={(value) => saveMaterial("autofill_notes", value)}
                    reviewState={job.materials.review.materials?.autofill}
                    onApprove={() => approveMaterial("autofill")}
                  />
                ) : null}
              </div>
            ) : null}
          </section>

          <div className="flex items-start gap-2 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2.5">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-primary" />
            <p className="text-xs leading-relaxed text-muted-foreground">
              El asistente local intenta abrir el portal, completa los campos seguros
              y te muestra instrucciones concretas cuando necesita tu intervención.
            </p>
          </div>
        </section>

        {applicationOperationId ? (
          <section className="flex items-start gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4" aria-live="polite">
            <LoaderCircle className="mt-0.5 size-5 shrink-0 animate-spin text-primary" />
            <div>
              <h3 className="text-sm font-semibold text-foreground">Completando formulario</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {applicationProgress || "Preparando el formulario con el asistente local..."}
              </p>
            </div>
          </section>
        ) : null}

        {latestSession ? (
          <SimpleApplicationStatus
            job={job}
            session={latestSession}
            busy={sessionBusy}
            onOpenAssistant={() => setAssistantOpen(true)}
            onOpenPortal={() => openExternal(applyUrlForJob(job))}
          />
        ) : null}

        <ApplicationAssistantDialog
          open={assistantOpen}
          onOpenChange={setAssistantOpen}
          session={latestSession}
          progressMessage={applicationOperationId ? applicationProgress : null}
          fallbackPortalUrl={applyUrlForJob(job)}
          busy={sessionBusy}
          onOpenPortal={(url) => openExternal(url || applyUrlForJob(job))}
          onResume={() => void continueApplicationSession()}
          onMarkSubmitted={() => void markSubmittedManually()}
        />

        <details className="rounded-xl border border-border bg-muted/10 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-muted-foreground">
            Ver información y controles avanzados
          </summary>
          <div className="mt-4 flex flex-col gap-5">
            {latestSession ? (
              <SessionReview
                session={latestSession}
                busy={sessionBusy}
                capabilities={providerCapabilities}
                onContinue={() => void continueApplicationSession()}
                onMarkSubmitted={() => void markSubmittedManually()}
              />
            ) : null}

            <details className="rounded-lg border border-border bg-muted/20 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-foreground">
                Compatibilidad técnica y prueba de formulario
              </summary>
              <div className="mt-3 flex flex-col gap-3">
                <ProviderCapabilityList capabilities={providerCapabilities} />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowDryRunInput((value) => !value)}
                >
                  <FileSearch data-icon="inline-start" />
                  Probar formulario Greenhouse
                </Button>
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
            </details>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Button
            className="order-1"
            size="sm"
            variant="outline"
            onClick={() => {
              setPipelineStatus(job.id, "shortlisted")
              toast.success("Guardado", { description: job.title })
            }}
          >
            <Star data-icon="inline-start" />
            Guardar
          </Button>
          <Button
            className={cn("order-4", !showAiProviders && "hidden")}
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
            NVIDIA
          </Button>
          <Button
            className={cn("order-5", !showAiProviders && "hidden")}
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
            OpenAI
          </Button>
          <Button
            className="order-2"
            size="sm"
            variant="outline"
            onClick={() => {
              setPipelineStatus(job.id, "ready_to_apply")
              toast.success("Listo para aplicar", { description: job.title })
            }}
          >
            <CheckCircle2 data-icon="inline-start" />
            Listo para aplicar
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="order-3 text-muted-foreground"
            onClick={() => {
              setPipelineStatus(job.id, "discarded")
              toast("Descartado", { description: job.title })
              onClose()
            }}
          >
            <X data-icon="inline-start" />
            Descartar
          </Button>
        </div>
        <Button
          className="self-end"
          size="sm"
          variant="ghost"
          aria-expanded={showAiProviders}
          onClick={() => setShowAiProviders((value) => !value)}
        >
          <Sparkles data-icon="inline-start" />
          {showAiProviders ? "Ocultar proveedores IA" : "Elegir proveedor IA"}
        </Button>

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
            {(job.ranking.generation.provider ||
              job.ranking.generation.model ||
              job.ranking.generation.candidate_profile_hash) ? (
              <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                {job.ranking.generation.provider ? (
                  <span className="rounded-md border border-border bg-background/70 px-2 py-0.5">
                    {job.ranking.generation.provider}
                  </span>
                ) : null}
                {job.ranking.generation.model ? (
                  <span className="rounded-md border border-border bg-background/70 px-2 py-0.5">
                    {job.ranking.generation.model}
                  </span>
                ) : null}
                {job.ranking.generation.validation_attempts && job.ranking.generation.validation_attempts > 1 ? (
                  <span className="rounded-md border border-warning/30 bg-warning/10 px-2 py-0.5 text-warning-foreground">
                    {job.ranking.generation.validation_attempts} validation attempts
                  </span>
                ) : null}
                {job.ranking.generation.candidate_profile_hash ? (
                  <span className="rounded-md border border-border bg-background/70 px-2 py-0.5">
                    profile {job.ranking.generation.candidate_profile_hash.slice(0, 8)}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
          <RankingReviewPanel job={job} />
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
        <LazyDetails title="Por qué encaja (y qué falta)">
          <div className="mt-3 flex flex-col gap-3">
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
        </LazyDetails>

        {hiringContacts.length > 0 ? (
          <DeferredSection className="flex flex-col gap-2">
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
          </DeferredSection>
        ) : null}

        <DeferredSection className="flex flex-col gap-2">
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
        </DeferredSection>

        <DeferredSection className="flex flex-col gap-2">
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
        </DeferredSection>

        <LazyDetails title="Job description">
          <p className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
            {job.description_text}
          </p>
        </LazyDetails>

        <LazyDetails title="Ranking technical detail">
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            {Object.entries(job.ranking.scores).map(([key, value]) => (
              <div key={key} className="rounded-md border border-border bg-background/60 px-2 py-1">
                <span className="block text-[11px] uppercase text-muted-foreground/70">{key.replaceAll("_", " ")}</span>
                <span className="font-semibold text-foreground">{String(value)}</span>
              </div>
            ))}
          </div>
        </LazyDetails>

        {/* Application materials */}
        {(job.materials.recruiter_message ||
          job.materials.cover_letter ||
          job.materials.ats_cv_notes ||
          job.materials.autofill_notes) && (
          <>
            <Separator />
            <DeferredSection className="flex flex-col gap-2">
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
                  onSave={(value) => saveMaterial("recruiter_message", value)}
                  reviewState={job.materials.review.materials?.recruiter_message}
                  onApprove={() => approveMaterial("recruiter_message")}
                />
                <MaterialBlock
                  label="Cover letter"
                  text={job.materials.cover_letter}
                  onSave={(value) => saveMaterial("cover_letter", value)}
                  reviewState={job.materials.review.materials?.cover_letter}
                  onApprove={() => approveMaterial("cover_letter")}
                />
                <MaterialBlock
                  label="Optimized ATS CV"
                  text={job.materials.ats_cv_notes}
                  onSave={(value) => saveMaterial("ats_cv_notes", value)}
                  reviewState={job.materials.review.materials?.ats_cv}
                  onApprove={() => approveMaterial("ats_cv")}
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
                <AutofillPlanBlock
                  text={job.materials.autofill_notes}
                  onSave={(value) => saveMaterial("autofill_notes", value)}
                  reviewState={job.materials.review.materials?.autofill}
                  onApprove={() => approveMaterial("autofill")}
                />
              </div>
            </DeferredSection>
          </>
        )}
          </div>
        </details>
      </div>
    </div>
  )
})

export function JobDetailDrawer({
  jobId,
  onClose,
}: {
  jobId: string | null
  onClose: () => void
}) {
  const {
    applications,
    generateMaterials,
    getJob,
    getJobDetailEntry,
    getJobSummary,
    loadJobDetail,
    markOpened,
    refreshApplications,
    setPipelineStatus,
  } = useStore()
  const job = jobId ? getJob(jobId) : undefined
  const summary = jobId ? getJobSummary(jobId) : undefined
  const detailEntry = jobId ? getJobDetailEntry(jobId) : { status: "idle" as const }
  const actions = useMemo(
    () => ({ generateMaterials, loadJobDetail, markOpened, refreshApplications, setPipelineStatus }),
    [generateMaterials, loadJobDetail, markOpened, refreshApplications, setPipelineStatus],
  )
  useEffect(() => {
    if (!jobId) return
    void loadJobDetail(jobId)
  }, [jobId, loadJobDetail])
  const companyHistory = useMemo(() => {
    if (!job) return []
    return applications.filter(
      (application) => application.company?.toLowerCase() === job.company.toLowerCase(),
    )
  }, [applications, job])

  return (
    <Dialog.Root
      open={jobId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Viewport className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
          <Dialog.Popup className="relative flex h-[min(92dvh,820px)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl outline-none transition duration-200 data-ending-style:scale-[.98] data-ending-style:opacity-0 data-starting-style:scale-[.98] data-starting-style:opacity-0">
          <div className="absolute right-4 top-4 z-20">
            <Dialog.Title className="sr-only">
            {job?.title ?? summary?.title ?? "Job detail"}
            </Dialog.Title>
            <Dialog.Description className="sr-only">
            Ranking, description, and application materials for this job.
            </Dialog.Description>
            <Dialog.Close
            aria-label="Close job detail"
            className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"
          >
            <X className="size-4" />
            </Dialog.Close>
          </div>
        {job ? (
          <DetailBody
            job={job}
            onClose={onClose}
            actions={actions}
            companyHistory={companyHistory}
          />
        ) : (
          <div className="flex min-h-[360px] flex-col gap-4 px-4 pb-6">
            {detailEntry.status === "error" ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4">
                <div className="flex items-start gap-3">
                  <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">Could not load job detail</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {detailEntry.error ?? "The backend request failed."}
                    </p>
                    {jobId ? (
                      <Button className="mt-3" size="sm" variant="outline" onClick={() => void loadJobDetail(jobId, { force: true })}>
                        Retry
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="h-6 w-40 animate-pulse rounded-md bg-muted" />
                <div className="h-20 animate-pulse rounded-lg bg-muted" />
                <div className="h-28 animate-pulse rounded-lg bg-muted" />
                <div className="h-36 animate-pulse rounded-lg bg-muted" />
              </div>
            )}
          </div>
        )}
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
