"use client"

import { useEffect, useState, type ReactNode } from "react"
import { AlertCircle, CheckCircle2, Circle, LoaderCircle, Timer } from "lucide-react"
import { cn } from "@/lib/utils"

export type TaskProgressStepState = "done" | "active" | "pending" | "error"
export interface TaskProgressStep { label: string; state: TaskProgressStepState }

export function AsyncActionContent({ pending, pendingLabel, children }: { pending: boolean; pendingLabel: string; children: ReactNode }) {
  if (!pending) return <>{children}</>
  return <><LoaderCircle className="animate-spin" data-icon="inline-start" />{pendingLabel}</>
}

export function TaskProgressCard({ title, description, steps = [], startedAt, progress, status = "active", technicalDetails, compact = false, className }: {
  title: string; description: string; steps?: TaskProgressStep[]; startedAt?: string | null; progress?: number | null
  status?: "active" | "success" | "error"; technicalDetails?: string | null; compact?: boolean; className?: string
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const active = status === "active"
  useEffect(() => {
    if (!active) return
    const parsed = startedAt ? Date.parse(startedAt) : Number.NaN
    const origin = Number.isFinite(parsed) ? parsed : Date.now()
    const update = () => setElapsedSeconds(Math.max(0, Math.floor((Date.now() - origin) / 1000)))
    update(); const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [active, startedAt])
  const normalizedProgress = typeof progress === "number" ? Math.max(0, Math.min(100, Math.round(progress))) : null
  return <section role="status" aria-live="polite" aria-busy={active} className={cn("rounded-xl border p-3", status === "error" ? "border-destructive/25 bg-destructive/5" : status === "success" ? "border-success/25 bg-success/5" : "border-primary/20 bg-primary/5", compact ? "p-3" : "sm:p-4", className)}>
    <div className="flex items-start gap-3"><div className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl", status === "error" ? "bg-destructive/10 text-destructive" : status === "success" ? "bg-success/10 text-success-foreground" : "bg-primary/10 text-primary")}>{status === "error" ? <AlertCircle className="size-4" /> : status === "success" ? <CheckCircle2 className="size-4" /> : <LoaderCircle className="size-4 animate-spin" />}</div>
      <div className="min-w-0 flex-1"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-sm font-semibold text-foreground">{title}</p><p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{description}</p></div>{active ? <span className="inline-flex items-center gap-1 rounded-md border border-primary/20 bg-background px-2 py-1 text-xs tabular-nums text-muted-foreground"><Timer className="size-3" />{elapsedSeconds}s</span> : null}</div>
        {active ? <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-primary/10">{normalizedProgress === null ? <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" /> : <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${normalizedProgress}%` }} />}</div> : null}
        {steps.length > 0 ? <ol className="mt-3 grid gap-1.5 sm:grid-cols-2">{steps.map(step => <li key={step.label} className={cn("flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs", step.state === "done" && "border-success/20 bg-success/5 text-success-foreground", step.state === "active" && "border-primary/20 bg-background text-foreground", step.state === "error" && "border-destructive/20 bg-destructive/5 text-destructive", step.state === "pending" && "border-border bg-muted/20 text-muted-foreground")}>{step.state === "done" ? <CheckCircle2 className="size-3.5 shrink-0" /> : step.state === "active" ? <LoaderCircle className="size-3.5 shrink-0 animate-spin" /> : step.state === "error" ? <AlertCircle className="size-3.5 shrink-0" /> : <Circle className="size-3.5 shrink-0" />}<span>{step.label}</span></li>)}</ol> : null}
        {technicalDetails ? <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">Ver detalles técnicos</summary><pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 font-mono text-[11px]">{technicalDetails}</pre></details> : null}
      </div></div>
  </section>
}
