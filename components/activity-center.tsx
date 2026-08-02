"use client"

import { useState } from "react"
import { Activity, AlertCircle, CheckCircle2, LoaderCircle, RotateCcw, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { OperationRun } from "@/lib/types"

function operationLabel(operation: OperationRun) {
  const labels: Record<string, string> = {
    cv_profile_import: "Importación de CV",
    linkedin_scan: "Búsqueda de oportunidades",
    materials_generation: "Generación de materiales",
    application_session: "Preparación de candidatura",
  }
  return labels[operation.type] ?? operation.type.replaceAll("_", " ")
}

function statusLabel(status: OperationRun["status"]) {
  if (status === "queued") return "En cola"
  if (status === "running") return "En curso"
  if (status === "completed") return "Completada"
  if (status === "cancelled") return "Cancelada"
  return "Con error"
}

export function ActivityCenter({ operations, onRetry }: { operations: OperationRun[]; onRetry?: (operation: OperationRun) => void }) {
  const [open, setOpen] = useState(false)
  const active = operations.filter((operation) => ["queued", "running"].includes(operation.status))
  const attention = operations.filter((operation) => ["failed", "cancelled"].includes(operation.status))
  const badgeCount = active.length + attention.length
  return <div className="relative">
    <Button variant="outline" size="sm" aria-expanded={open} aria-controls="activity-center-panel" onClick={() => setOpen((value) => !value)}>
      {active.length > 0 ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Activity data-icon="inline-start" />}
      Actividad{badgeCount > 0 ? <span className="ml-1 rounded-full bg-primary/10 px-1.5 text-[11px] tabular-nums">{badgeCount}</span> : null}
    </Button>
    {open ? <section id="activity-center-panel" role="region" aria-label="Centro de actividad" className="absolute right-0 top-11 z-50 w-[min(23rem,calc(100vw-2rem))] rounded-xl border border-border bg-card p-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between"><p className="text-sm font-semibold">Actividad reciente</p><button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setOpen(false)}>Cerrar</button></div>
      {operations.length === 0 ? <p className="py-5 text-center text-xs text-muted-foreground" role="status">No hay operaciones recientes.</p> : <ul className="max-h-80 space-y-2 overflow-auto" aria-live="polite">{operations.slice(0, 8).map((operation) => <li key={operation.id} className="rounded-lg border border-border/80 p-2.5"><div className="flex items-start gap-2"><span className={cn("mt-0.5", operation.status === "completed" ? "text-success-foreground" : operation.status === "failed" ? "text-destructive" : operation.status === "cancelled" ? "text-muted-foreground" : "text-primary")}>{operation.status === "completed" ? <CheckCircle2 className="size-4" /> : operation.status === "failed" ? <AlertCircle className="size-4" /> : operation.status === "cancelled" ? <XCircle className="size-4" /> : <LoaderCircle className="size-4 animate-spin" />}</span><div className="min-w-0 flex-1"><p className="text-xs font-medium">{operationLabel(operation)}</p><p className="text-[11px] text-muted-foreground">{statusLabel(operation.status)}{operation.progress_message ? ` · ${operation.progress_message}` : ""}</p>{["failed", "cancelled"].includes(operation.status) && onRetry ? <Button size="sm" variant="ghost" className="mt-1 h-7 px-2 text-xs" onClick={() => onRetry(operation)}><RotateCcw data-icon="inline-start" />Reintentar</Button> : null}</div></div></li>)}</ul>}
    </section> : null}
  </div>
}
