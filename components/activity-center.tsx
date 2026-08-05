"use client"

import { useEffect, useState } from "react"
import { Activity, AlertCircle, CheckCircle2, LoaderCircle, RotateCcw, Timer, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { OperationRun } from "@/lib/types"

function operationLabel(operation: OperationRun) {
  const labels: Record<string, string> = {
    cv_profile_import: "Importacion de CV",
    linkedin_scan: "Busqueda de oportunidades en LinkedIn",
    job_scan: "Busqueda en portales ATS y fuentes publicas",
    materials_generation: "Generacion de materiales",
    application_session: "Preparacion de candidatura",
  }
  return labels[operation.type] ?? operation.type.replaceAll("_", " ")
}

function operationDescription(operation: OperationRun) {
  if (operation.progress_message) return operation.progress_message
  if (operation.type === "linkedin_scan") return "Buscando oportunidades en LinkedIn y guardandolas a medida que aparecen."
  if (operation.type === "job_scan") return "Consultando portales ATS, APIs y fuentes publicas configuradas."
  return "Procesando la operacion y sincronizando resultados."
}

function statusLabel(status: OperationRun["status"]) {
  if (status === "queued") return "En cola"
  if (status === "running") return "En curso"
  if (status === "completed") return "Completada"
  if (status === "cancelled") return "Cancelada"
  return "Con error"
}

function OperationItem({ operation, onRetry }: { operation: OperationRun; onRetry?: (operation: OperationRun) => void }) {
  const active = ["queued", "running"].includes(operation.status)
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!active) return
    const origin = Date.parse(operation.started_at || operation.created_at)
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - (Number.isFinite(origin) ? origin : Date.now())) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [active, operation.created_at, operation.started_at])
  const icon = operation.status === "completed" ? <CheckCircle2 className="size-4" /> : operation.status === "failed" ? <AlertCircle className="size-4" /> : operation.status === "cancelled" ? <XCircle className="size-4" /> : <LoaderCircle className="size-4 animate-spin" />
  return <li className="rounded-lg border border-border/80 p-2.5"><div className="flex items-start gap-2"><span className={cn("mt-0.5", operation.status === "completed" ? "text-success-foreground" : operation.status === "failed" ? "text-destructive" : operation.status === "cancelled" ? "text-muted-foreground" : "text-primary")}>{icon}</span><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><p className="text-xs font-medium">{operationLabel(operation)}</p>{active ? <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><Timer className="size-3" />{elapsed}s</span> : null}</div><p className="text-[11px] text-muted-foreground">{statusLabel(operation.status)} · {operationDescription(operation)}</p>{active ? <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-primary/10"><div className="h-full w-1/2 animate-pulse rounded-full bg-primary" /></div> : null}{["failed", "cancelled"].includes(operation.status) && onRetry ? <Button size="sm" variant="ghost" className="mt-1 h-7 px-2 text-xs" onClick={() => onRetry(operation)}><RotateCcw data-icon="inline-start" />Reintentar</Button> : null}</div></div></li>
}

export function ActivityCenter({ operations, onRetry }: { operations: OperationRun[]; onRetry?: (operation: OperationRun) => void }) {
  const [open, setOpen] = useState(false)
  const active = operations.filter((operation) => ["queued", "running"].includes(operation.status))
  const attention = operations.filter((operation) => ["failed", "cancelled"].includes(operation.status))
  const badgeCount = active.length + attention.length
  return <div className="relative"><Button variant="outline" size="sm" className={cn(badgeCount > 0 && "border-primary/50 bg-primary/10 text-primary shadow-[0_0_0_3px_rgba(59,130,246,0.12)]")} aria-expanded={open} aria-controls="activity-center-panel" onClick={() => setOpen((value) => !value)}>{active.length > 0 ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Activity data-icon="inline-start" />}Actividad{badgeCount > 0 ? <span className="ml-1 inline-flex min-w-5 items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[11px] font-bold text-primary-foreground animate-pulse">{badgeCount}</span> : null}</Button>{open ? <section id="activity-center-panel" role="region" aria-label="Centro de actividad" className="absolute right-0 top-11 z-50 w-[min(23rem,calc(100vw-2rem))] rounded-xl border border-border bg-card p-3 shadow-lg"><div className="mb-2 flex items-center justify-between"><p className="text-sm font-semibold">Actividad reciente</p><button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setOpen(false)}>Cerrar</button></div>{operations.length === 0 ? <p className="py-5 text-center text-xs text-muted-foreground" role="status">No hay operaciones recientes.</p> : <ul className="max-h-80 space-y-2 overflow-auto" aria-live="polite">{operations.slice(0, 8).map((operation) => <OperationItem key={operation.id} operation={operation} onRetry={onRetry} />)}</ul>}</section> : null}</div>
}
