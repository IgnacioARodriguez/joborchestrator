"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
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
import {
  getPreparationViewState,
  isConfirmedApplication,
  matchesPreparationFilter,
  type PreparationAction,
  type PreparationFilter,
  type PreparationStep,
  type PreparationViewState,
} from "@/lib/apply-preparation"
import { applyUrlForJob, relativeTime } from "@/lib/job-ui"
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
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Materiales">
      {view.materials.map((material) => (
        <span
          key={material.id}
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
            material.ready
              ? material.needsReview
                ? "border-warning/30 bg-warning/10 text-warning-foreground"
                : "border-success/25 bg-success/10 text-success-foreground"
              : "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          {material.ready ? <CheckCircle2 className="size-3" /> : <Circle className="size-3" />}
          {material.label}
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
  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)] sm:p-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
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
          <Badge variant="outline" className={cn("w-fit shrink-0", STATUS_TONE[view.status])}>
            {view.label}
          </Badge>
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
              {busy ? "Trabajando..." : view.primaryAction.label}
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
}: {
  onOpenJob: (id: string) => void
}) {
  const {
    jobs,
    applications,
    jobsStatus,
    applyQueuePage,
    applyQueuePageSize,
    jobsMeta,
    refresh,
    refreshApplications,
    generateMaterials,
    loadJobDetail,
    markOpened,
  } = useStore()
  const [filter, setFilter] = useState<PreparationFilter>("all")
  const [sessions, setSessions] = useState<ApplicationSession[]>([])
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [operationByJob, setOperationByJob] = useState<Record<string, number>>({})

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
  }, [jobs.length])

  useEffect(() => {
    const entries = Object.entries(operationByJob)
    if (entries.length === 0) return
    let stopped = false
    const timer = window.setTimeout(async () => {
      const completed: string[] = []
      await Promise.all(
        entries.map(async ([jobId, operationId]) => {
          try {
            const response = await api.getOperation(operationId)
            if (response.operation.status === "completed") {
              completed.push(jobId)
              await loadJobDetail(jobId, { force: true })
              toast.success("Materiales listos")
            }
            if (response.operation.status === "failed") {
              completed.push(jobId)
              toast.error("No se pudieron generar materiales", {
                description: "Revisa el problema y vuelve a intentar.",
              })
            }
          } catch {
            completed.push(jobId)
          }
        }),
      )
      if (!stopped && completed.length > 0) {
        setOperationByJob((current) => {
          const next = { ...current }
          for (const jobId of completed) delete next[jobId]
          return next
        })
        void refresh()
      }
    }, 2500)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [loadJobDetail, operationByJob, refresh])

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
        const view = operationByJob[job.id]
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
          : baseView
        return { job, session, view }
      })
      .filter(({ view }) => matchesPreparationFilter(view, filter))
  }, [confirmedJobIds, filter, jobs, operationByJob, sessions])

  async function handleAction(job: JobListItem, session: ApplicationSession | null, action: PreparationAction) {
    if (action === "review_materials" || action === "continue_review") {
      onOpenJob(job.id)
      return
    }

    setBusyJobId(job.id)
    try {
      if (action === "generate_materials") {
        const response = await generateMaterials(job.id)
        if (response.operation_id) {
          setOperationByJob((current) => ({ ...current, [job.id]: response.operation_id! }))
          toast.success("Generacion iniciada", { description: job.title })
        } else {
          toast.success("Materiales generados", { description: job.title })
        }
        return
      }

      if (action === "open_portal") {
        const detail = await loadJobDetail(job.id, { force: true })
        const url = detail ? applyUrlForJob(detail) : null
        const response = await api.createApplicationSession(job.id, {
          mode: "review_before_submit",
          dry_run: true,
        })
        setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
        if (response.operation_id) {
          toast.success("Sesion iniciada", { description: "La aplicacion se preparo sin marcar envio." })
        }
        if (url) {
          markOpened(job.id)
          window.open(url, "_blank", "noopener,noreferrer")
        }
        await Promise.all([refresh(), refreshApplications()])
        return
      }

      if (action === "continue_session" || action === "resolve_problem") {
        if (session) {
          const response = await api.continueApplicationSession(session.id)
          setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
          toast.success("Sesion reanudada", { description: "Continua la revision en el portal." })
        } else {
          onOpenJob(job.id)
        }
        return
      }

      if (action === "confirm_submitted") {
        if (!window.confirm(`Confirmas que enviaste la candidatura para ${job.title}?`)) return
        if (session && ["submit_only", "ready_for_review", "needs_user_input"].includes(session.state)) {
          const response = await api.markApplicationSubmittedManually(session.id)
          setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
        } else {
          await api.createApplication(job.id, {
            status: "submitted_manually",
            channel: "portal",
            submitted_at: new Date().toISOString(),
          })
        }
        await Promise.all([refresh(), refreshApplications()])
        toast.success("Envio confirmado", { description: "La candidatura salio de Aplicar." })
      }
    } catch (error) {
      toast.error("No se pudo completar la accion", {
        description: error instanceof Error ? error.message : "Intenta nuevamente.",
      })
    } finally {
      setBusyJobId(null)
    }
  }

  const total = jobsMeta?.total ?? preparations.length
  const empty = jobsStatus === "empty" || preparations.length === 0

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Aplicar"
        description={`${total.toLocaleString()} candidaturas pendientes de preparacion`}
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
                Guarda o selecciona jobs desde Jobs. Las candidaturas confirmadas aparecen en Aplicaciones.
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
                busy={busyJobId === job.id || Boolean(operationByJob[job.id])}
                onOpenJob={onOpenJob}
                onPrimary={(action) => void handleAction(job, session, action)}
                onSecondary={(action) => void handleAction(job, session, action)}
              />
            ))}
          </div>
        )}
      </div>

      {jobsMeta?.has_next || jobsMeta?.has_previous ? (
        <div className="flex shrink-0 items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
          <span>
            Pagina {applyQueuePage} de la cola
          </span>
          <span>
            Mostrando hasta {applyQueuePageSize} candidaturas
          </span>
        </div>
      ) : null}
    </div>
  )
}
