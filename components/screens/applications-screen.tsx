"use client"

import { useMemo, useState } from "react"
import {
  ArrowUpRight,
  BriefcaseBusiness,
  CalendarClock,
  Check,
  CircleDot,
  Clock3,
  Inbox,
  LoaderCircle,
  MessageSquarePlus,
  RotateCcw,
  Search,
  Send,
  Trophy,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { api } from "@/lib/api"
import type { ApplicationEvent, ApplicationRecord, ApplicationStatus, FollowUp } from "@/lib/types"
import { cn } from "@/lib/utils"
import { userFacingError } from "@/lib/user-facing-error"

type TrackingFilter = "active" | "action" | "closed" | "all"
type CanonicalTrackingStatus =
  | "submitted"
  | "recruiter_screen"
  | "interview"
  | "technical"
  | "offer"
  | "rejected"
  | "withdrawn"

const TRACKING_STATUSES = new Set<ApplicationStatus>([
  "submitted_manually",
  "submission_verified",
  "submitted",
  "recruiter_screen",
  "interview",
  "technical",
  "offer",
  "rejected",
  "withdrawn",
])

const CLOSED_STATUSES = new Set<ApplicationStatus>(["rejected", "withdrawn"])

const STATUS_OPTIONS: Array<{
  value: CanonicalTrackingStatus
  label: string
  description: string
}> = [
  { value: "submitted", label: "Enviada", description: "Esperando respuesta" },
  { value: "recruiter_screen", label: "Contacto inicial", description: "Conversación con recruiting" },
  { value: "interview", label: "Entrevista", description: "Entrevista agendada o en curso" },
  { value: "technical", label: "Prueba técnica", description: "Take-home, live coding o técnica" },
  { value: "offer", label: "Oferta", description: "Oferta recibida" },
  { value: "rejected", label: "Rechazada", description: "Proceso cerrado por la empresa" },
  { value: "withdrawn", label: "Retirada", description: "Proceso cerrado por decisión propia" },
]

const STATUS_LABELS: Record<CanonicalTrackingStatus, string> = Object.fromEntries(
  STATUS_OPTIONS.map((option) => [option.value, option.label]),
) as Record<CanonicalTrackingStatus, string>

const FILTERS: Array<{ value: TrackingFilter; label: string }> = [
  { value: "active", label: "Activas" },
  { value: "action", label: "Con próxima acción" },
  { value: "closed", label: "Cerradas" },
  { value: "all", label: "Todas" },
]

function canonicalStatus(status: ApplicationStatus): CanonicalTrackingStatus {
  if (status === "submitted_manually" || status === "submission_verified") return "submitted"
  if (TRACKING_STATUSES.has(status)) return status as CanonicalTrackingStatus
  return "submitted"
}

function isTrackingApplication(application: ApplicationRecord) {
  return TRACKING_STATUSES.has(application.status)
}

function pendingFollowUps(application: ApplicationRecord) {
  return (application.follow_ups ?? [])
    .filter((followUp) => !followUp.done_at)
    .sort((a, b) => dateValue(a.due_at) - dateValue(b.due_at))
}

function nextFollowUp(application: ApplicationRecord) {
  return pendingFollowUps(application)[0]
}

function dateValue(value?: string | null) {
  if (!value) return Number.POSITIVE_INFINITY
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY
}

function formatDate(value?: string | null, includeTime = false) {
  if (!value) return "Sin fecha"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("es-ES", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date)
}

function dueLabel(followUp: FollowUp) {
  const due = new Date(followUp.due_at)
  if (Number.isNaN(due.getTime())) return followUp.due_at
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startDue = new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime()
  const diffDays = Math.round((startDue - startToday) / 86_400_000)
  if (diffDays < 0) return `Vencida hace ${Math.abs(diffDays)} día${Math.abs(diffDays) === 1 ? "" : "s"}`
  if (diffDays === 0) return "Para hoy"
  if (diffDays === 1) return "Para mañana"
  return `En ${diffDays} días`
}

function isOverdue(followUp?: FollowUp) {
  return Boolean(followUp && dateValue(followUp.due_at) < Date.now())
}

function recommendedAction(application: ApplicationRecord) {
  const status = canonicalStatus(application.status)
  if (status === "submitted") return "Programar un follow-up si todavía no recibiste respuesta."
  if (status === "recruiter_screen") return "Registrar el próximo contacto o la fecha acordada."
  if (status === "interview") return "Preparar la entrevista y anotar los puntos clave."
  if (status === "technical") return "Registrar la entrega o la próxima instancia técnica."
  if (status === "offer") return "Revisar condiciones y definir una fecha de respuesta."
  return "No hay acciones pendientes para esta candidatura."
}

function defaultFollowUpDateTime() {
  const date = new Date(Date.now() + 3 * 86_400_000)
  date.setMinutes(0, 0, 0)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function eventLabel(event: ApplicationEvent) {
  const labels: Record<string, string> = {
    submitted: "Candidatura enviada",
    submitted_manually: "Candidatura enviada manualmente",
    submission_verified: "Envío verificado",
    status_changed: "Estado actualizado",
    recruiter_reply: "Respuesta de recruiter",
    interview_scheduled: "Entrevista agendada",
    rejection: "Rechazo recibido",
    ghosted: "Sin respuesta",
    follow_up_scheduled: "Follow-up programado",
    follow_up_completed: "Follow-up completado",
    note_added: "Nota agregada",
    opened: "Portal abierto",
    answer_saved: "Información de aplicación guardada",
  }
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ")
}

function statusBadgeClass(status: CanonicalTrackingStatus) {
  if (status === "offer") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
  if (status === "rejected" || status === "withdrawn") return "border-muted-foreground/20 bg-muted text-muted-foreground"
  if (status === "interview" || status === "technical") return "border-primary/30 bg-primary/10 text-primary"
  return "border-border bg-background text-foreground"
}

function ApplicationListCard({
  application,
  selected,
  onSelect,
}: {
  application: ApplicationRecord
  selected: boolean
  onSelect: () => void
}) {
  const followUp = nextFollowUp(application)
  const status = canonicalStatus(application.status)
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "w-full rounded-xl border p-4 text-left transition-colors",
        selected ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-foreground">
            {application.job_title || `Candidatura ${application.id}`}
          </h3>
          <p className="mt-1 truncate text-xs text-muted-foreground">{application.company || "Empresa desconocida"}</p>
        </div>
        <Badge variant="outline" className={statusBadgeClass(status)}>{STATUS_LABELS[status]}</Badge>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>Enviada {formatDate(application.submitted_at || application.created_at)}</span>
        {followUp ? (
          <span className={cn("flex items-center gap-1", isOverdue(followUp) && "font-medium text-destructive")}>
            <Clock3 className="size-3.5" />
            {dueLabel(followUp)}
          </span>
        ) : (
          <span>Sin próxima acción</span>
        )}
      </div>
    </button>
  )
}

export function ApplicationsScreen({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const {
    applications,
    applicationsStatus,
    refreshApplications,
    setApplicationStatus,
  } = useStore()
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<TrackingFilter>("active")
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [followUpDraft, setFollowUpDraft] = useState({ due_at: defaultFollowUpDateTime(), note: "" })
  const [noteDraft, setNoteDraft] = useState("")
  const [busyAction, setBusyAction] = useState<string | null>(null)

  const trackedApplications = useMemo(
    () => applications.filter(isTrackingApplication),
    [applications],
  )

  const visibleApplications = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("es")
    return trackedApplications
      .filter((application) => {
        const closed = CLOSED_STATUSES.has(application.status)
        if (filter === "active" && closed) return false
        if (filter === "closed" && !closed) return false
        if (filter === "action" && (closed || pendingFollowUps(application).length === 0)) return false
        if (!normalizedQuery) return true
        return [application.job_title, application.company]
          .filter(Boolean)
          .some((value) => String(value).toLocaleLowerCase("es").includes(normalizedQuery))
      })
      .sort((a, b) => {
        const aDue = dateValue(nextFollowUp(a)?.due_at)
        const bDue = dateValue(nextFollowUp(b)?.due_at)
        if (aDue !== bDue) return aDue - bDue
        return dateValue(b.updated_at) - dateValue(a.updated_at)
      })
  }, [filter, query, trackedApplications])

  const effectiveSelectedId = visibleApplications.some((application) => application.id === selectedId)
    ? selectedId
    : visibleApplications[0]?.id ?? null
  const selectedApplication = visibleApplications.find((application) => application.id === effectiveSelectedId) ?? null
  const selectedFollowUp = selectedApplication ? nextFollowUp(selectedApplication) : undefined
  const selectedStatus = selectedApplication ? canonicalStatus(selectedApplication.status) : "submitted"
  const timeline = (() => {
    if (!selectedApplication) return []
    const events = [...(selectedApplication.events ?? [])]
    if (events.length === 0 && selectedApplication.submitted_at) {
      events.push({
        id: -selectedApplication.id,
        application_id: selectedApplication.id,
        event_type: "submitted",
        event_at: selectedApplication.submitted_at,
        note: "Candidatura registrada como enviada.",
      })
    }
    return events.sort((a, b) => dateValue(b.event_at) - dateValue(a.event_at))
  })()

  const activeCount = trackedApplications.filter((application) => !CLOSED_STATUSES.has(application.status)).length
  const actionCount = trackedApplications.filter(
    (application) => !CLOSED_STATUSES.has(application.status) && pendingFollowUps(application).length > 0,
  ).length
  const interviewCount = trackedApplications.filter((application) => ["interview", "technical"].includes(canonicalStatus(application.status))).length
  const offerCount = trackedApplications.filter((application) => canonicalStatus(application.status) === "offer").length

  async function changeStatus(status: CanonicalTrackingStatus) {
    if (!selectedApplication || status === selectedStatus) return
    setBusyAction("status")
    const label = STATUS_LABELS[status]
    const ok = await setApplicationStatus(
      selectedApplication.id,
      status,
      `Estado actualizado a ${label}.`,
    )
    setBusyAction(null)
    if (ok) {
      toast.success("Estado actualizado", { description: `${selectedApplication.company || "Candidatura"}: ${label}` })
    } else {
      toast.error("No se pudo actualizar el estado")
    }
  }

  async function scheduleFollowUp() {
    if (!selectedApplication || !followUpDraft.due_at) return
    const due = new Date(followUpDraft.due_at)
    if (Number.isNaN(due.getTime())) {
      toast.error("La fecha del follow-up no es válida")
      return
    }
    setBusyAction("follow-up")
    try {
      await api.createFollowUp({
        application_id: selectedApplication.id,
        due_at: due.toISOString(),
        note: followUpDraft.note.trim() || undefined,
      })
      await refreshApplications()
      setFollowUpDraft({ due_at: defaultFollowUpDateTime(), note: "" })
      toast.success("Follow-up programado", { description: formatDate(due.toISOString(), true) })
    } catch (error) {
      toast.error("No se pudo programar el follow-up", {
        description: userFacingError(error),
      })
    } finally {
      setBusyAction(null)
    }
  }

  async function completeFollowUp(followUp: FollowUp) {
    setBusyAction(`follow-up-${followUp.id}`)
    try {
      await api.patchFollowUp(followUp.id, true)
      await refreshApplications()
      toast.success("Follow-up completado")
    } catch (error) {
      toast.error("No se pudo completar el follow-up", {
        description: userFacingError(error),
      })
    } finally {
      setBusyAction(null)
    }
  }

  async function addNote() {
    if (!selectedApplication || !noteDraft.trim()) return
    setBusyAction("note")
    try {
      await api.createApplicationEvent(selectedApplication.id, {
        event_type: "note_added",
        note: noteDraft.trim(),
      })
      await refreshApplications()
      setNoteDraft("")
      toast.success("Nota agregada")
    } catch (error) {
      toast.error("No se pudo guardar la nota", {
        description: userFacingError(error),
      })
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Aplicaciones"
        title="Seguimiento de candidaturas"
        description="Estados simples, próxima acción, timeline y follow-ups para candidaturas realmente enviadas."
      />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Card className="gap-2 py-4">
          <CardContent className="flex items-center justify-between px-4">
            <div>
              <p className="text-xs text-muted-foreground">Activas</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{activeCount}</p>
            </div>
            <BriefcaseBusiness className="size-5 text-primary" />
          </CardContent>
        </Card>
        <Card className="gap-2 py-4">
          <CardContent className="flex items-center justify-between px-4">
            <div>
              <p className="text-xs text-muted-foreground">Próximas acciones</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{actionCount}</p>
            </div>
            <CalendarClock className="size-5 text-primary" />
          </CardContent>
        </Card>
        <Card className="gap-2 py-4">
          <CardContent className="flex items-center justify-between px-4">
            <div>
              <p className="text-xs text-muted-foreground">Entrevistas / técnica</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{interviewCount}</p>
            </div>
            <CircleDot className="size-5 text-primary" />
          </CardContent>
        </Card>
        <Card className="gap-2 py-4">
          <CardContent className="flex items-center justify-between px-4">
            <div>
              <p className="text-xs text-muted-foreground">Ofertas</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{offerCount}</p>
            </div>
            <Trophy className="size-5 text-primary" />
          </CardContent>
        </Card>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(320px,0.85fr)_minmax(520px,1.15fr)]">
        <Card className="min-h-0 gap-3 overflow-hidden">
          <CardHeader className="shrink-0 gap-3 border-b border-border pb-4">
            <div>
              <CardTitle className="text-base">Candidaturas enviadas</CardTitle>
              <CardDescription className="text-xs">Las preparaciones pendientes continúan en Aplicar.</CardDescription>
            </div>
            <label className="relative block">
              <span className="sr-only">Buscar candidaturas</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar empresa o puesto"
                className="pl-9"
              />
            </label>
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  aria-pressed={filter === item.value}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    filter === item.value
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground hover:bg-muted",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 overflow-y-auto px-4 pb-4" aria-busy={applicationsStatus === "loading" || applicationsStatus === "refreshing"}>
            {applicationsStatus === "refreshing" ? <div className="mb-3 flex items-center gap-2 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2 text-xs text-muted-foreground" role="status"><LoaderCircle className="size-3.5 animate-spin text-primary" />Actualizando candidaturas…</div> : null}
            {applicationsStatus === "loading" ? (
              <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center" role="status"><LoaderCircle className="size-6 animate-spin text-primary" /><p className="text-sm font-medium text-foreground">Cargando candidaturas</p></div>
            ) : applicationsStatus === "error" ? (
              <Empty className="min-h-64 border border-dashed bg-muted/20"><EmptyHeader><EmptyMedia variant="icon"><Inbox /></EmptyMedia><EmptyTitle>No se pudieron cargar las candidaturas</EmptyTitle><EmptyDescription>Comprueba la conexión e intenta nuevamente.</EmptyDescription></EmptyHeader><Button variant="outline" onClick={() => void refreshApplications()}><RotateCcw data-icon="inline-start" />Reintentar</Button></Empty>
            ) : visibleApplications.length === 0 ? (
              <Empty className="min-h-64 border border-dashed bg-muted/20">
                <EmptyHeader>
                  <EmptyMedia variant="icon"><Inbox /></EmptyMedia>
                  <EmptyTitle>No hay candidaturas en esta vista</EmptyTitle>
                  <EmptyDescription>
                    Las candidaturas aparecen cuando confirmás que el envío fue realizado.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="flex flex-col gap-2.5">
                {visibleApplications.map((application) => (
                  <ApplicationListCard
                    key={application.id}
                    application={application}
                    selected={application.id === effectiveSelectedId}
                    onSelect={() => setSelectedId(application.id)}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="min-h-0 gap-0 overflow-hidden">
          {!selectedApplication ? (
            <CardContent className="flex h-full min-h-96 items-center justify-center">
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon"><BriefcaseBusiness /></EmptyMedia>
                  <EmptyTitle>Seleccioná una candidatura</EmptyTitle>
                  <EmptyDescription>Vas a ver su estado, próxima acción y timeline.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            </CardContent>
          ) : (
            <>
              <CardHeader className="shrink-0 border-b border-border pb-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-lg">
                      {selectedApplication.job_title || `Candidatura ${selectedApplication.id}`}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {selectedApplication.company || "Empresa desconocida"} · Enviada {formatDate(selectedApplication.submitted_at || selectedApplication.created_at)}
                    </CardDescription>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => onOpenJob(String(selectedApplication.job_id))}>
                      Ver job
                      <ArrowUpRight data-icon="inline-end" />
                    </Button>
                    <Select
                      value={selectedStatus}
                      onValueChange={(value) => void changeStatus(value as CanonicalTrackingStatus)}
                      disabled={busyAction === "status"}
                    >
                      <SelectTrigger aria-label="Estado de candidatura" className="min-w-40">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent align="end">
                        {STATUS_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            <span className="flex flex-col">
                              <span>{option.label}</span>
                              <span className="text-[11px] text-muted-foreground">{option.description}</span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                  <div className="flex flex-col gap-4">
                    <Card className="gap-3 border-primary/20 bg-primary/5 py-4 shadow-none">
                      <CardHeader className="px-4 pb-0">
                        <CardTitle className="flex items-center gap-2 text-sm">
                          <CalendarClock className="size-4 text-primary" />
                          Próxima acción
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="px-4">
                        {selectedFollowUp ? (
                          <div className="space-y-3">
                            <div>
                              <p className="text-sm font-medium text-foreground">
                                {selectedFollowUp.note || "Hacer seguimiento de la candidatura"}
                              </p>
                              <p className={cn("mt-1 text-xs text-muted-foreground", isOverdue(selectedFollowUp) && "font-medium text-destructive")}>
                                {dueLabel(selectedFollowUp)} · {formatDate(selectedFollowUp.due_at, true)}
                              </p>
                            </div>
                            <Button
                              size="sm"
                              onClick={() => void completeFollowUp(selectedFollowUp)}
                              disabled={busyAction === `follow-up-${selectedFollowUp.id}`}
                            >
                              <Check data-icon="inline-start" />
                              Marcar como completada
                            </Button>
                          </div>
                        ) : (
                          <div>
                            <p className="text-sm font-medium text-foreground">Sin próxima acción programada</p>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                              {recommendedAction(selectedApplication)}
                            </p>
                          </div>
                        )}
                      </CardContent>
                    </Card>

                    {!CLOSED_STATUSES.has(selectedApplication.status) ? (
                      <Card className="gap-3 py-4 shadow-none">
                        <CardHeader className="px-4 pb-0">
                          <CardTitle className="text-sm">Programar follow-up</CardTitle>
                          <CardDescription className="text-xs">Solo crea el recordatorio; no envía mensajes automáticamente.</CardDescription>
                        </CardHeader>
                        <CardContent className="flex flex-col gap-2 px-4">
                          <Input
                            type="datetime-local"
                            value={followUpDraft.due_at}
                            onChange={(event) => setFollowUpDraft((current) => ({ ...current, due_at: event.target.value }))}
                            aria-label="Fecha del follow-up"
                          />
                          <Textarea
                            value={followUpDraft.note}
                            onChange={(event) => setFollowUpDraft((current) => ({ ...current, note: event.target.value }))}
                            placeholder="Ej.: escribir al recruiter por LinkedIn"
                            className="min-h-20 text-sm"
                          />
                          <Button
                            variant="outline"
                            onClick={() => void scheduleFollowUp()}
                            disabled={!followUpDraft.due_at || busyAction === "follow-up"}
                          >
                            <CalendarClock data-icon="inline-start" />
                            Programar
                          </Button>
                        </CardContent>
                      </Card>
                    ) : null}

                    <Card className="gap-3 py-4 shadow-none">
                      <CardHeader className="px-4 pb-0">
                        <CardTitle className="text-sm">Agregar nota</CardTitle>
                      </CardHeader>
                      <CardContent className="flex flex-col gap-2 px-4">
                        <Textarea
                          value={noteDraft}
                          onChange={(event) => setNoteDraft(event.target.value)}
                          placeholder="Entrevista, feedback, contacto o contexto importante"
                          className="min-h-24 text-sm"
                        />
                        <Button
                          variant="outline"
                          onClick={() => void addNote()}
                          disabled={!noteDraft.trim() || busyAction === "note"}
                        >
                          <MessageSquarePlus data-icon="inline-start" />
                          Guardar nota
                        </Button>
                      </CardContent>
                    </Card>
                  </div>

                  <Card className="gap-3 py-4 shadow-none">
                    <CardHeader className="px-4 pb-0">
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <Send className="size-4 text-primary" />
                        Timeline
                      </CardTitle>
                      <CardDescription className="text-xs">Historial de estados, notas y follow-ups.</CardDescription>
                    </CardHeader>
                    <CardContent className="px-4">
                      {timeline.length === 0 ? (
                        <p className="rounded-lg border border-dashed border-border py-10 text-center text-xs text-muted-foreground">
                          Todavía no hay movimientos registrados.
                        </p>
                      ) : (
                        <ol className="relative ml-2 border-l border-border pl-5">
                          {timeline.map((event) => (
                            <li key={event.id} className="relative pb-5 last:pb-0">
                              <span className="absolute -left-[1.55rem] top-1.5 size-2.5 rounded-full border-2 border-background bg-primary" />
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <p className="text-sm font-medium text-foreground">{eventLabel(event)}</p>
                                <time className="text-[11px] text-muted-foreground">{formatDate(event.event_at, true)}</time>
                              </div>
                              {event.note ? (
                                <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{event.note}</p>
                              ) : null}
                            </li>
                          ))}
                        </ol>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
