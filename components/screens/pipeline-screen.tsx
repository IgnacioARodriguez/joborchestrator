"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Inbox,
  LoaderCircle,
  MapPin,
  Play,
  RefreshCw,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DecisionBadge, ScoreRing } from "@/components/badges"
import { ApplicationAssistantDialog } from "@/components/application-assistant-dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PageHeader } from "@/components/page-chrome"
import { api } from "@/lib/api"
import { friendlyApplicationProgress } from "@/lib/application-assistant"
import { userFacingError } from "@/lib/user-facing-error"
import {
  getPreparationViewState,
  isConfirmedApplication,
  matchesPreparationFilter,
  missingMaterialTargets,
  type PreparationAction,
  type PreparationFilter,
  type PreparationStep,
  type PreparationViewState,
} from "@/lib/apply-preparation"
import { relativeTime } from "@/lib/job-ui"
import { useStore } from "@/lib/store"
import type { ApplicationSession, JobListItem } from "@/lib/types"
import { cn } from "@/lib/utils"

const FILTERS: Array<{ id: PreparationFilter; label: string }> = [
  { id: "all", label: "Todos" },
  { id: "review", label: "Necesitan revision" },
  { id: "ready", label: "Listos para aplicar" },
  { id: "blocked", label: "Con problemas" },
]

const STATUS_TONE: Record<PreparationViewState["status"], string> = {
  pending: "border-border bg-muted text-muted-foreground",
  generating: "border-info/25 bg-info/15 text-info-foreground",
  needs_review: "border-warning/30 bg-warning/15 text-warning-foreground",
  ready_to_apply: "border-success/25 bg-success/15 text-success-foreground",
  application_started: "border-primary/25 bg-primary/10 text-primary",
  blocked: "border-destructive/25 bg-destructive/10 text-destructive",
}

function latestSessionForJob(sessions: ApplicationSession[], jobId: string) {
  return sessions.find((session) => String(session.job_id) === String(jobId)) ?? null
}

function withoutKeys<T>(record: Record<string, T>, keys: string[]) {
  if (keys.length === 0) return record
  const next = { ...record }
  for (const key of keys) delete next[key]
  return next
}

function trackedOperationIds(...records: Array<Record<string, number>>) {
  return [...new Set(records.flatMap((record) => Object.values(record)))]
}

function StepIcon({ step }: { step: PreparationStep }) {
  if (step.state === "done") return <Check className="size-3.5" aria-hidden />
  if (step.state === "blocked") return <AlertCircle className="size-3.5" aria-hidden />
  if (step.state === "active") return <Play className="size-3.5" aria-hidden />
  return <Circle className="size-3.5" aria-hidden />
}

function PreparationProgress({ steps }: { steps: PreparationStep[] }) {
  return (
    <ol
      className="grid grid-cols-2 gap-1.5 sm:grid-cols-4"
      aria-label="Progreso de preparacion"
    >
      {steps.map((step, index) => (
        <li
          key={step.id}
          aria-current={step.state === "active" ? "step" : undefined}
          className={cn(
            "flex min-h-9 items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
            step.state === "done" && "border-success/25 bg-success/10 text-success-foreground",
            step.state === "active" && "border-primary/25 bg-primary/10 text-primary",
            step.state === "blocked" && "border-destructive/25 bg-destructive/10 text-destructive",
            step.state === "todo" && "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-background/75 tabular-nums">
            <StepIcon step={step} />
          </span>
          <span className="min-w-0 truncate">
            {index + 1}. {step.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

function MaterialPills({ view }: { view: PreparationViewState }) {
  const applicable = view.materials.filter((material) => material.state !== "not_required")
  const prepared = applicable.filter((material) => material.ready).length
  const stateLabel = (material: PreparationViewState["materials"][number]) => {
    if (material.state === "approved") return "aprobado"
    if (material.state === "warning") return "con advertencias"
    if (material.state === "not_required") return "no requerido"
    if (material.state === "failed") return "falló"
    if (material.state === "generating") return "generando"
    return material.ready ? "listo" : "pendiente"
  }
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Materiales">
      <span className="inline-flex items-center rounded-md border border-border bg-muted/30 px-2 py-1 text-xs text-muted-foreground">
        {prepared} de {applicable.length} preparados
      </span>
      {view.materials.map((material) => (
        <span
          key={material.id}
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
            material.state === "not_required"
              ? "border-border bg-muted/30 text-muted-foreground"
              : material.ready
                ? material.needsReview
                  ? "border-warning/30 bg-warning/10 text-warning-foreground"
                  : "border-success/25 bg-success/10 text-success-foreground"
                : material.state === "failed"
                  ? "border-destructive/25 bg-destructive/10 text-destructive"
                  : "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          {material.ready ? <CheckCircle2 className="size-3" /> : <Circle className="size-3" />}
          {material.label} {stateLabel(material)}
        </span>
      ))}
    </div>
  )
}


function PreparationCard({
  job,
  view,
  busy,
  onPrimary,
  onSecondary,
  onOpenJob,
}: {
  job: JobListItem
  view: PreparationViewState
  busy: boolean
  onPrimary: (action: PreparationAction) => void
  onSecondary: (action: PreparationAction) => void
  onOpenJob: (id: string) => void
}) {
  const busyLabel =
    view.status === "generating"
      ? "Preparando materiales..."
      : view.status === "application_started"
        ? "Completando formulario..."
        : "Procesando..."
  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)] sm:p-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <ScoreRing score={job.ranking.final_score} size={52} />
            <button
              type="button"
              onClick={() => onOpenJob(job.id)}
              className="min-w-0 text-left"
            >
              <h2 className="line-clamp-2 text-base font-semibold leading-snug text-foreground">
                {job.title}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex min-w-0 items-center gap-1">
                  <Building2 className="size-3.5 shrink-0" />
                  <span className="truncate">{job.company}</span>
                </span>
                <span className="inline-flex min-w-0 items-center gap-1">
                  <MapPin className="size-3.5 shrink-0" />
                  <span className="truncate">{job.location || (job.remote ? "Remote" : "Sin ubicacion")}</span>
                </span>
                <span>Actualizado {relativeTime(job.last_seen_at)}</span>
              </div>
            </button>
          </div>
          <div className="flex w-fit shrink-0 items-center gap-2">
            <DecisionBadge
              decision={job.ranking.decision}
              score={job.ranking.final_score}
            />
            <Badge
              variant="outline"
              className={cn("w-fit shrink-0", STATUS_TONE[view.status])}
            >
              {view.label}
            </Badge>
          </div>
        </div>

        <PreparationProgress steps={view.progress} />

        <div className="grid gap-2 lg:grid-cols-[1fr_auto] lg:items-end">
          <div className="flex flex-col gap-2">
            <p className="text-sm text-muted-foreground">{view.description}</p>
            {view.blocker ? (
              <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs leading-relaxed text-warning-foreground">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <span>{view.blocker}</span>
              </div>
            ) : null}
            <MaterialPills view={view} />
          </div>
          <div className="flex flex-col gap-1.5 sm:min-w-52">
            <Button
              className="w-full"
              disabled={busy}
              onClick={() => onPrimary(view.primaryAction.type)}
              aria-live={busy ? "polite" : undefined}
            >
              {busy ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : actionIcon(view.primaryAction.type)}
              {busy ? busyLabel : view.primaryAction.label}
            </Button>
            {view.secondaryActions.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {view.secondaryActions.map((action) => (
                  <Button
                    key={action.type}
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    disabled={busy}
                    onClick={() => onSecondary(action.type)}
                  >
                    {actionIcon(action.type)}
                    {action.label}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  )
}

function localDateTimeValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function SubmissionConfirmation({
  job,
  busy,
  onCancel,
  onConfirm,
}: {
  job: JobListItem
  busy: boolean
  onCancel: () => void
  onConfirm: (input: {
    submittedAt: string
    channel: "portal" | "easy_apply" | "referral" | "direct_contact"
    note: string
    recruiterContacted: boolean
  }) => void
}) {
  const [submittedAt, setSubmittedAt] = useState(() => localDateTimeValue())
  const [channel, setChannel] = useState<"portal" | "easy_apply" | "referral" | "direct_contact">("portal")
  const [note, setNote] = useState("")
  const [recruiterContacted, setRecruiterContacted] = useState(false)
  const dialogRef = useRef<HTMLElement>(null)
  const dateInputRef = useRef<HTMLInputElement>(null)
  const busyRef = useRef(busy)
  const onCancelRef = useRef(onCancel)

  useEffect(() => {
    busyRef.current = busy
    onCancelRef.current = onCancel
  }, [busy, onCancel])

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dateInputRef.current?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault()
        onCancelRef.current()
        return
      }
      if (event.key !== "Tab") return
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("keydown", onKeyDown)
      previousFocus?.focus()
    }
  }, [])

  function submit() {
    const parsed = new Date(submittedAt)
    if (Number.isNaN(parsed.getTime())) return
    onConfirm({ submittedAt: parsed.toISOString(), channel, note, recruiterContacted })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end bg-black/35 p-3 sm:items-center sm:justify-center"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel()
      }}
    >
      <section
        ref={dialogRef}
        aria-describedby="submission-confirmation-description"
        aria-labelledby="submission-confirmation-title"
        aria-modal="true"
        role="dialog"
        className="w-full max-w-md rounded-lg border border-border bg-card p-4 shadow-xl"
      >
        <h2 id="submission-confirmation-title" className="text-base font-semibold text-foreground">
          Confirmar envío
        </h2>
        <p id="submission-confirmation-description" className="mt-1 text-sm text-muted-foreground">
          Confirmá que enviaste la candidatura para {job.title}.
        </p>
        <div className="mt-4 grid gap-3">
          <label className="grid gap-1.5 text-sm font-medium text-foreground">
            Fecha de envío
            <input
              ref={dateInputRef}
              type="datetime-local"
              value={submittedAt}
              onChange={(event) => setSubmittedAt(event.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-foreground">
            Nota opcional
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="min-h-20 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={recruiterContacted}
              onChange={(event) => setRecruiterContacted(event.target.checked)}
            />
            Contacté a un recruiter
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-foreground">
            Canal
            <select
              value={channel}
              onChange={(event) => setChannel(event.target.value as typeof channel)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              <option value="portal">Portal de la empresa</option>
              <option value="easy_apply">Easy Apply</option>
              <option value="referral">Referido</option>
              <option value="direct_contact">Contacto directo</option>
            </select>
          </label>
        </div>
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onCancel} disabled={busy}>Cancelar</Button>
          <Button onClick={submit} disabled={busy || !submittedAt}>
            {busy ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <ClipboardCheck data-icon="inline-start" />}
            Confirmar que apliqué
          </Button>
        </div>
      </section>
    </div>
  )
}


function actionIcon(action: PreparationAction) {
  if (action === "generate_materials") return <Sparkles data-icon="inline-start" />
  if (action === "review_materials" || action === "continue_review") return <FileText data-icon="inline-start" />
  if (action === "open_portal") return <ExternalLink data-icon="inline-start" />
  if (action === "confirm_submitted") return <ClipboardCheck data-icon="inline-start" />
  if (action === "continue_session") return <RefreshCw data-icon="inline-start" />
  return <AlertCircle data-icon="inline-start" />
}

export function PipelineScreen({
  onOpenJob,
  sessionsRevision,
}: {
  onOpenJob: (id: string) => void
  sessionsRevision?: number
}) {
  const {
    preparationJobs: jobs,
    applications,
    preparationJobsStatus: jobsStatus,
    preparationQueuePage: applyQueuePage,
    applyQueuePageSize,
    preparationJobsMeta: jobsMeta,
    refreshPreparationQueue: refresh,
    setPreparationQueuePage,
    recordApplication,
    generateMaterials,
    loadJobDetail,
  } = useStore()
  const [filter, setFilter] = useState<PreparationFilter>("all")
  const [sessions, setSessions] = useState<ApplicationSession[]>([])
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [operationByJob, setOperationByJob] = useState<Record<string, number>>({})
  const [applicationOperationByJob, setApplicationOperationByJob] = useState<Record<string, number>>({})
  const [applicationProgressByJob, setApplicationProgressByJob] = useState<Record<string, string>>({})
  const [operationIssueByJob, setOperationIssueByJob] = useState<Record<string, string>>({})
  const [confirmation, setConfirmation] = useState<{ job: JobListItem; session: ApplicationSession | null } | null>(null)
  const [assistantJob, setAssistantJob] = useState<JobListItem | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadSessions() {
      try {
        const response = await api.getApplicationSessions()
        if (!cancelled) setSessions(response.sessions)
      } catch {
        if (!cancelled) setSessions([])
      }
    }
    void loadSessions()
    return () => {
      cancelled = true
    }
  }, [sessionsRevision])

  useEffect(() => {
    let cancelled = false
    void api.getOperations(100).then((response) => {
      if (cancelled) return
      const recoveredMaterials: Record<string, number> = {}
      const recoveredApplications: Record<string, number> = {}
      const recoveredProgress: Record<string, string> = {}
      for (const operation of response.operations) {
        const jobId = String(operation.input_json?.job_id ?? "")
        if (!jobId || !["queued", "running"].includes(operation.status)) continue
        if (operation.type === "application_materials_generation" && recoveredMaterials[jobId] === undefined) {
          recoveredMaterials[jobId] = operation.id
        }
        if (operation.type === "application_execution" && recoveredApplications[jobId] === undefined) {
          recoveredApplications[jobId] = operation.id
          recoveredProgress[jobId] = friendlyApplicationProgress(operation.progress_message)
        }
      }
      if (Object.keys(recoveredMaterials).length > 0) setOperationByJob(recoveredMaterials)
      if (Object.keys(recoveredApplications).length > 0) setApplicationOperationByJob(recoveredApplications)
      if (Object.keys(recoveredProgress).length > 0) setApplicationProgressByJob(recoveredProgress)
    }).catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const materialEntries = Object.entries(operationByJob)
    const applicationEntries = Object.entries(applicationOperationByJob)
    const operationIds = trackedOperationIds(operationByJob, applicationOperationByJob)
    if (operationIds.length === 0) return

    let stopped = false
    let timer: number | undefined

    async function poll() {
      if (stopped) return
      if (document.visibilityState === "hidden") {
        timer = window.setTimeout(poll, 2500)
        return
      }

      try {
        const response = await api.getOperationsByIds(operationIds)
        if (stopped) return

        const operationsById = new Map(response.operations.map((operation) => [operation.id, operation]))
        const completedMaterials: string[] = []
        const completedApplications: string[] = []
        const resolvedIssues: string[] = []
        const issueUpdates: Record<string, string> = {}
        const progressUpdates: Record<string, string> = {}

        for (const [jobId, operationId] of materialEntries) {
          const operation = operationsById.get(operationId)
          if (!operation) continue

          if (operation.status === "completed") {
            completedMaterials.push(jobId)
            resolvedIssues.push(jobId)
            await loadJobDetail(jobId, { force: true })
            toast.success("Materiales listos")
            continue
          }

          if (["failed", "cancelled"].includes(operation.status)) {
            completedMaterials.push(jobId)
            const issue = "La generación se detuvo antes de completar los materiales. Volvé a intentarlo."
            issueUpdates[jobId] = issue
            toast.error("No se pudieron generar materiales", { description: issue })
            continue
          }

          const updatedAt = Date.parse(operation.updated_at)
          if (Number.isFinite(updatedAt) && Date.now() - updatedAt > 15 * 60_000) {
            completedMaterials.push(jobId)
            const issue = "La generación no mostró progreso durante 15 minutos. Podés reintentarla."
            issueUpdates[jobId] = issue
            toast.error("La generación se detuvo", { description: issue })
          }
        }

        for (const [jobId, operationId] of applicationEntries) {
          const operation = operationsById.get(operationId)
          if (!operation) continue

          progressUpdates[jobId] = friendlyApplicationProgress(operation.progress_message)
          if (operation.status === "completed") {
            try {
              const sessionsResponse = await api.getApplicationSessions(jobId)
              if (stopped) return
              setSessions((current) => [
                ...sessionsResponse.sessions,
                ...current.filter((item) => String(item.job_id) !== String(jobId)),
              ])
              const completedJob = jobs.find((job) => String(job.id) === String(jobId))
              if (completedJob && sessionsResponse.sessions[0]) setAssistantJob(completedJob)
              await loadJobDetail(jobId, { force: true })
              completedApplications.push(jobId)
              resolvedIssues.push(jobId)
              toast.success("Automatización pausada", {
                description: "Revisá las instrucciones para continuar.",
              })
            } catch {
              // Keep polling until the completed session can be read successfully.
            }
            continue
          }

          if (["failed", "cancelled"].includes(operation.status)) {
            completedApplications.push(jobId)
            const issue = "No se pudo completar el formulario. Podes abrir el job y continuar manualmente."
            issueUpdates[jobId] = issue
            toast.error("No se pudo preparar la aplicacion", { description: issue })
          }
        }

        if (stopped) return
        if (resolvedIssues.length > 0 || Object.keys(issueUpdates).length > 0) {
          setOperationIssueByJob((current) => ({
            ...withoutKeys(current, resolvedIssues),
            ...issueUpdates,
          }))
        }
        if (completedMaterials.length > 0) {
          setOperationByJob((current) => withoutKeys(current, completedMaterials))
        }
        if (Object.keys(progressUpdates).length > 0 || completedApplications.length > 0) {
          setApplicationProgressByJob((current) =>
            withoutKeys({ ...current, ...progressUpdates }, completedApplications),
          )
        }
        if (completedApplications.length > 0) {
          setApplicationOperationByJob((current) => withoutKeys(current, completedApplications))
        }
      } catch {
        // Retry transient API failures without losing the active operation state.
      }

      if (!stopped) timer = window.setTimeout(poll, 2500)
    }

    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [applicationOperationByJob, jobs, loadJobDetail, operationByJob])


  const confirmedJobIds = useMemo(
    () => new Set(applications.filter(isConfirmedApplication).map((application) => String(application.job_id))),
    [applications],
  )

  const preparations = useMemo(() => {
    return jobs
      .filter((job) => job.pipeline_status !== "discarded")
      .filter((job) => !confirmedJobIds.has(String(job.id)))
      .map((job) => {
        const session = latestSessionForJob(sessions, job.id)
        const baseView = getPreparationViewState(job, session)
        const operationIssue = operationIssueByJob[job.id]
        const view = applicationOperationByJob[job.id]
          ? {
              ...baseView,
              status: "application_started" as const,
              label: "Completando formulario",
              description: applicationProgressByJob[job.id] || "Preparando el formulario en la ventana de aplicacion...",
              primaryAction: { type: "continue_session" as const, label: "Completando formulario" },
              progress: baseView.progress.map((step) =>
                step.id === "application"
                  ? { ...step, state: "active" as const }
                  : ["materials", "review"].includes(step.id)
                    ? { ...step, state: "done" as const }
                    : step,
              ),
            }
          : operationByJob[job.id]
          ? {
              ...baseView,
              status: "generating" as const,
              label: "Generando",
              description: "Estamos preparando los materiales de la candidatura.",
              primaryAction: { type: "review_materials" as const, label: "Revisar cuando termine" },
              progress: baseView.progress.map((step) =>
                step.id === "materials" ? { ...step, state: "active" as const } : step,
              ),
            }
          : operationIssue
            ? {
                ...baseView,
                status: "blocked" as const,
                label: "Generación detenida",
                description: "La preparación automática no pudo completarse.",
                blocker: operationIssue,
                primaryAction: { type: "generate_materials" as const, label: "Reintentar generación" },
              }
            : baseView
        return { job, session, view }
      })
      .filter(({ view }) => matchesPreparationFilter(view, filter))
  }, [applicationOperationByJob, applicationProgressByJob, confirmedJobIds, filter, jobs, operationByJob, operationIssueByJob, sessions])

  async function handleAction(job: JobListItem, session: ApplicationSession | null, action: PreparationAction) {
    if (action === "review_materials" || action === "continue_review") {
      onOpenJob(job.id)
      return
    }

    if (action === "confirm_submitted") {
      setConfirmation({ job, session })
      return
    }

    setBusyJobId(job.id)
    try {
      if (action === "generate_materials") {
        setOperationIssueByJob((current) => {
          const next = { ...current }
          delete next[job.id]
          return next
        })
        const response = await generateMaterials(job.id, undefined, missingMaterialTargets(job))
        if (response.operation_id) {
          setOperationByJob((current) => ({ ...current, [job.id]: response.operation_id! }))
          toast.success("Generacion iniciada", { description: job.title })
        } else {
          toast.success("Materiales generados", { description: job.title })
        }
        return
      }

      if (action === "open_portal") {
        if (session) {
          onOpenJob(job.id)
          return
        }
        const response = await api.createApplicationSession(job.id, {
          mode: "review_before_submit",
          dry_run: true,
        })
        setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
        if (response.operation_id) {
          setAssistantJob(job)
          setApplicationOperationByJob((current) => ({ ...current, [job.id]: response.operation_id! }))
          setApplicationProgressByJob((current) => ({
            ...current,
            [job.id]: "Abriendo el portal de la empresa...",
          }))
          toast.success("Automatización iniciada", {
            description: "El asistente local intentará abrir el portal y completar los campos seguros.",
          })
        } else {
          onOpenJob(job.id)
        }
        return
      }

      if (action === "continue_session" || action === "resolve_problem") {
        if (session) {
          const response = await api.continueApplicationSession(session.id)
          setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
          setAssistantJob(job)
          if (response.operation_id) {
            setApplicationOperationByJob((current) => ({ ...current, [job.id]: response.operation_id! }))
            setApplicationProgressByJob((current) => ({
              ...current,
              [job.id]: "Revisando nuevamente el formulario...",
            }))
          }
          toast.success("Continuando aplicacion", { description: "La misma sesion del navegador se revisara de nuevo." })
        } else {
          onOpenJob(job.id)
        }
        return
      }

    } catch (error) {
      toast.error("No se pudo completar la accion", {
        description: userFacingError(error),
      })
    } finally {
      setBusyJobId(null)
    }
  }

  async function confirmSubmission(input: {
    submittedAt: string
    channel: "portal" | "easy_apply" | "referral" | "direct_contact"
    note: string
    recruiterContacted: boolean
  }) {
    if (!confirmation) return
    const { job, session } = confirmation
    setBusyJobId(job.id)
    try {
      if (session && ["submit_only", "ready_for_review", "needs_user_input"].includes(session.state)) {
        const response = await api.markApplicationSubmittedManually(session.id, {
          submitted_at: input.submittedAt,
          channel: input.channel,
          note: input.note || undefined,
          recruiter_contacted: input.recruiterContacted,
        })
        setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
        if (response.session.application_id) {
          const application = await api.getApplication(response.session.application_id)
          recordApplication(application.application)
        }
      } else {
        const response = await api.createApplication(job.id, {
          status: "submitted_manually",
          channel: input.channel,
          submitted_at: input.submittedAt,
          note: input.note || undefined,
          recruiter_contacted: input.recruiterContacted,
        })
        recordApplication(response.application)
      }
      setConfirmation(null)
      toast.success("Envio confirmado", { description: "La candidatura salio de Aplicar." })
    } catch (error) {
      toast.error("No se pudo confirmar el envio", {
        description: "La candidatura sigue en la cola. Vuelve a intentarlo.",
      })
    } finally {
      setBusyJobId(null)
    }
  }

  const assistantSession = assistantJob
    ? latestSessionForJob(sessions, assistantJob.id)
    : null
  const total = jobsMeta?.total ?? preparations.length
  const empty = jobsStatus === "empty" || preparations.length === 0
  const offset = jobsMeta?.offset ?? (applyQueuePage - 1) * applyQueuePageSize
  const returnedJobs = jobsMeta?.returned ?? jobs.length
  const rangeStart = total === 0 ? 0 : offset + 1
  const rangeEnd = Math.min(offset + returnedJobs, total)
  const canPagePrevious = Boolean(jobsMeta?.has_previous) || applyQueuePage > 1
  const canPageNext = Boolean(jobsMeta?.has_next)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Aplicar"
        description={`${total.toLocaleString()} jobs listos para preparar y enviar`}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <Tabs value={filter} onValueChange={(value) => setFilter(value as PreparationFilter)}>
            <TabsList className="w-max" aria-label="Filtros de preparacion">
              {FILTERS.map((item) => (
                <TabsTrigger key={item.id} value={item.id}>
                  {item.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refresh()}>
          <RefreshCw data-icon="inline-start" />
          Actualizar cola
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {empty ? (
          <Empty className="min-h-[360px] border border-dashed bg-card">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Inbox />
              </EmptyMedia>
              <EmptyTitle>No hay candidaturas pendientes</EmptyTitle>
              <EmptyDescription>
                Marca un job como Listo para aplicar desde Jobs. Las candidaturas confirmadas aparecen en Aplicaciones.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-3">
            {preparations.map(({ job, session, view }) => (
              <PreparationCard
                key={job.id}
                job={job}
                view={view}
                busy={busyJobId === job.id || Boolean(operationByJob[job.id]) || Boolean(applicationOperationByJob[job.id])}
                onOpenJob={onOpenJob}
                onPrimary={(action) => void handleAction(job, session, action)}
                onSecondary={(action) => void handleAction(job, session, action)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col gap-2 border-t border-border pt-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>
          {total === 0 ? "0 candidaturas" : `${rangeStart}-${rangeEnd} de ${total} candidaturas`}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={jobsStatus === "loading" || jobsStatus === "refreshing" || !canPagePrevious}
            onClick={() => setPreparationQueuePage(applyQueuePage - 1)}
          >
            <ChevronLeft data-icon="inline-start" />
            Anterior
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={jobsStatus === "loading" || jobsStatus === "refreshing" || !canPageNext}
            onClick={() => setPreparationQueuePage(applyQueuePage + 1)}
          >
            Siguiente
            <ChevronRight data-icon="inline-end" />
          </Button>
        </div>
      </div>
      {confirmation ? (
        <SubmissionConfirmation
          job={confirmation.job}
          busy={busyJobId === confirmation.job.id}
          onCancel={() => setConfirmation(null)}
          onConfirm={(input) => void confirmSubmission(input)}
        />
      ) : null}
      {assistantJob ? (
        <ApplicationAssistantDialog
          open
          onOpenChange={(open) => {
            if (!open) setAssistantJob(null)
          }}
          session={assistantSession}
          progressMessage={applicationProgressByJob[assistantJob.id] ?? null}
          busy={busyJobId === assistantJob.id}
          onOpenPortal={(url) => {
            if (url) {
              window.open(url, "_blank", "noopener,noreferrer")
              return
            }
            setAssistantJob(null)
            onOpenJob(assistantJob.id)
          }}
          onResume={() => void handleAction(assistantJob, assistantSession, "continue_session")}
          onMarkSubmitted={() => {
            setAssistantJob(null)
            setConfirmation({ job: assistantJob, session: assistantSession })
          }}
        />
      ) : null}
    </div>
  )
}
