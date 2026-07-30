"use client"

import { useEffect, useMemo, useState } from "react"
import {
  ArchiveRestore,
  Bookmark,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  MapPin,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { DecisionBadge } from "@/components/badges"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import type { JobListItem, PipelineStatus } from "@/lib/types"
import { PIPELINE_LABELS, rankingSummaryText, relativeTime } from "@/lib/job-ui"
import { cn } from "@/lib/utils"

type JobsFilter = "new" | "saved" | "discarded"
type SearchState = "idle" | "searching" | "success" | "empty" | "error"

const FILTERS: Array<{ id: JobsFilter; label: string; description: string }> = [
  { id: "new", label: "Nuevos", description: "Pendientes de decisión" },
  { id: "saved", label: "Guardados", description: "Interesantes o listos para preparar" },
  { id: "discarded", label: "Descartados", description: "Fuera del flujo principal" },
]

function statusForFilter(job: JobListItem, filter: JobsFilter) {
  if (filter === "new") return job.pipeline_status === "new"
  if (filter === "saved") return job.pipeline_status === "shortlisted" || job.pipeline_status === "ready_to_apply"
  return job.pipeline_status === "discarded"
}

function primaryAction(job: JobListItem): { label: string; status?: PipelineStatus } {
  if (job.pipeline_status === "new") return { label: "Preparar aplicación", status: "ready_to_apply" }
  if (job.pipeline_status === "shortlisted") return { label: "Continuar preparación", status: "ready_to_apply" }
  if (job.pipeline_status === "ready_to_apply") return { label: "Ver detalle" }
  if (job.pipeline_status === "discarded") return { label: "Restaurar", status: "new" }
  return { label: "Ver detalle" }
}

function matchSummary(job: JobListItem) {
  const firstMatch = job.ranking.evidence.strong_matches[0]
  if (firstMatch) return firstMatch
  return rankingSummaryText(job.ranking.decision, job.ranking.final_score, job.ranking.reasoning_summary)
}

function JobListCard({
  job,
  pending,
  onOpen,
  onMove,
}: {
  job: JobListItem
  pending: boolean
  onOpen: (id: string) => void
  onMove: (job: JobListItem, status: PipelineStatus) => void
}) {
  const action = primaryAction(job)
  const details = [
    job.company,
    job.location,
    job.remote ? "Remote" : null,
    relativeTime(job.first_seen_at),
  ].filter(Boolean)

  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)] transition-colors hover:border-primary/25 sm:p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <button
          type="button"
          onClick={() => onOpen(job.id)}
          className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
        >
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <DecisionBadge decision={job.ranking.decision} score={job.ranking.final_score} />
            {job.pipeline_status !== "new" ? (
              <span className="rounded-md border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {PIPELINE_LABELS[job.pipeline_status]}
              </span>
            ) : null}
          </div>
          <h2 className="line-clamp-2 text-base font-semibold leading-snug text-foreground">
            {job.title}
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {details.map((item) => (
              <span key={item} className="inline-flex min-w-0 items-center gap-1">
                {item === job.location ? <MapPin className="size-3.5 shrink-0" /> : null}
                <span className="truncate">{item}</span>
              </span>
            ))}
          </p>
          <p className="mt-2 line-clamp-2 text-sm leading-6 text-muted-foreground">
            {matchSummary(job)}
          </p>
        </button>

        <div className="flex shrink-0 flex-wrap gap-2 md:justify-end">
          <Button
            size="sm"
            disabled={pending}
            onClick={() => {
              if (action.status) onMove(job, action.status)
              else onOpen(job.id)
            }}
          >
            {pending ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Check data-icon="inline-start" />}
            {action.label}
          </Button>
          <Button size="icon-sm" variant="outline" aria-label={`Ver detalle de ${job.title}`} onClick={() => onOpen(job.id)}>
            <ExternalLink className="size-4" />
          </Button>
          {job.pipeline_status !== "discarded" ? (
            <>
              <Button
                size="icon-sm"
                variant="outline"
                aria-label={`Guardar ${job.title}`}
                disabled={pending || job.pipeline_status === "shortlisted"}
                onClick={() => onMove(job, "shortlisted")}
              >
                <Bookmark className="size-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Descartar ${job.title}`}
                disabled={pending}
                onClick={() => onMove(job, "discarded")}
              >
                <Trash2 className="size-4" />
              </Button>
            </>
          ) : (
            <Button
              size="icon-sm"
              variant="outline"
              aria-label={`Restaurar ${job.title}`}
              disabled={pending}
              onClick={() => onMove(job, "new")}
            >
              <ArchiveRestore className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </article>
  )
}

export function JobsScreen({
  onOpenJob,
  onSearchNewJobs,
  searchState = "idle",
  searchMessage,
}: {
  onOpenJob: (id: string) => void
  onSearchNewJobs?: () => void
  searchState?: SearchState
  searchMessage?: string | null
}) {
  const {
    applyQueuePage,
    applyQueuePageSize,
    applyQueueQuery,
    jobs,
    jobsMeta,
    jobsStatus,
    loading,
    setApplyQueuePage,
    setApplyQueueQuery,
    setPipelineStatus,
  } = useStore()
  const [filter, setFilter] = useState<JobsFilter>("new")
  const [query, setQuery] = useState(applyQueueQuery)
  const [pendingJobId, setPendingJobId] = useState<string | null>(null)
  const activeJobsTotal = jobsMeta?.total ?? jobs.length
  const offset = jobsMeta?.offset ?? (applyQueuePage - 1) * applyQueuePageSize
  const returnedJobs = jobsMeta?.returned ?? jobs.length
  const rangeStart = activeJobsTotal === 0 ? 0 : offset + 1
  const rangeEnd = Math.min(offset + returnedJobs, activeJobsTotal)
  const canPagePrevious = Boolean(jobsMeta?.has_previous) || applyQueuePage > 1
  const canPageNext = Boolean(jobsMeta?.has_next)

  const counts = useMemo(
    () => ({
      new: jobs.filter((job) => statusForFilter(job, "new")).length,
      saved: jobs.filter((job) => statusForFilter(job, "saved")).length,
      discarded: jobs.filter((job) => statusForFilter(job, "discarded")).length,
    }),
    [jobs],
  )

  const visible = useMemo(() => {
    return jobs
      .filter((job) => statusForFilter(job, filter))
      .sort((a, b) => b.priority.priority_score - a.priority.priority_score)
  }, [filter, jobs])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const trimmed = query.trim()
      if (trimmed !== applyQueueQuery) {
        setApplyQueueQuery(trimmed)
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [applyQueueQuery, query, setApplyQueueQuery])

  async function moveJob(job: JobListItem, status: PipelineStatus) {
    if (pendingJobId) return
    const previous = job.pipeline_status
    setPendingJobId(job.id)
    const ok = await setPipelineStatus(job.id, status)
    setPendingJobId(null)
    if (!ok) {
      toast.error("No se pudo actualizar el job", { description: job.title })
      return
    }
    const undoable = status === "discarded" || status === "shortlisted" || status === "ready_to_apply"
    toast.success(status === "discarded" ? "Job descartado" : status === "new" ? "Job restaurado" : "Job guardado", {
      description: job.title,
      action: undoable
        ? {
            label: "Undo",
            onClick: () => {
              void setPipelineStatus(job.id, previous)
            },
          }
        : undefined,
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Jobs"
        description={`${activeJobsTotal.toLocaleString()} oportunidades activas para revisar, guardar o descartar.`}
        actions={
          <Button onClick={onSearchNewJobs} disabled={!onSearchNewJobs || searchState === "searching"}>
            {searchState === "searching" ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Sparkles data-icon="inline-start" />}
            {searchState === "searching" ? "Buscando..." : "Buscar nuevos jobs"}
          </Button>
        }
      />

      {searchMessage ? (
        <div className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground" role="status" aria-live="polite">
          {searchMessage}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3">
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1" role="tablist" aria-label="Filtros de jobs">
          {FILTERS.map((item) => {
            const active = filter === item.id
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(item.id)}
                className={cn(
                  "flex min-h-14 flex-col items-center justify-center rounded-md px-2 py-2 text-center text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/40 sm:min-h-11 sm:flex-row sm:gap-2",
                  active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span>{item.label}</span>
                <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] tabular-nums text-muted-foreground">
                  {counts[item.id]}
                </span>
              </button>
            )
          })}
        </div>
        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar por puesto, empresa o ubicación"
            className="pl-9"
            aria-label="Buscar jobs por puesto, empresa o ubicación"
          />
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {jobsStatus === "error" ? (
          <Empty className="min-h-[360px] border border-dashed bg-card">
            <EmptyHeader>
              <EmptyMedia variant="icon"><RotateCcw /></EmptyMedia>
              <EmptyTitle>No se pudieron cargar los jobs</EmptyTitle>
              <EmptyDescription>Revisa la conexión con la API e intenta sincronizar de nuevo.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : visible.length === 0 && !loading ? (
          <Empty className="min-h-[360px] border border-dashed bg-card">
            <EmptyHeader>
              <EmptyMedia variant="icon"><Search /></EmptyMedia>
              <EmptyTitle>No hay jobs en {FILTERS.find((item) => item.id === filter)?.label.toLowerCase()}</EmptyTitle>
              <EmptyDescription>Cambia el filtro o busca nuevas oportunidades.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-2">
            {visible.map((job) => (
              <JobListCard
                key={job.id}
                job={job}
                pending={pendingJobId === job.id}
                onOpen={onOpenJob}
                onMove={moveJob}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col gap-2 border-t border-border pt-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>
          {activeJobsTotal === 0 ? "0 jobs" : `${rangeStart}-${rangeEnd} de ${activeJobsTotal} jobs`}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={loading || !canPagePrevious}
            onClick={() => setApplyQueuePage(applyQueuePage - 1)}
          >
            <ChevronLeft data-icon="inline-start" />
            Anterior
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={loading || !canPageNext}
            onClick={() => setApplyQueuePage(applyQueuePage + 1)}
          >
            Siguiente
            <ChevronRight data-icon="inline-end" />
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ReviewScreen(props: Parameters<typeof JobsScreen>[0]) {
  return <JobsScreen {...props} />
}
