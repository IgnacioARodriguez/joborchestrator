import type { LucideIcon } from "lucide-react"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function KpiCard({
  label,
  value,
  icon: Icon,
  hint,
  description,
  tone = "default",
}: {
  label: string
  value: string | number
  icon: LucideIcon
  hint?: string
  description?: string
  tone?: "default" | "primary" | "success" | "warning"
}) {
  return (
    <Card className="min-h-[142px] gap-0 p-5">
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </span>
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-2xl",
            tone === "primary" && "bg-primary/10 text-primary",
            tone === "success" && "bg-success/10 text-success-foreground",
            tone === "warning" && "bg-warning/15 text-warning-foreground",
            tone === "default" && "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="size-5" />
        </span>
      </div>
      <div className="mt-5 flex items-end justify-between gap-3">
        <span className="text-3xl font-semibold tabular-nums tracking-normal text-foreground">
          {value}
        </span>
        {hint && (
          <span className="rounded-full border border-border bg-muted/50 px-2 py-1 text-[11px] font-medium text-muted-foreground">
            {hint}
          </span>
        )}
      </div>
      {description ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{description}</p>
      ) : null}
    </Card>
  )
}
