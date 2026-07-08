import { AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { DECISION_STYLES, scoreTone } from "@/lib/job-ui"
import type { Decision } from "@/lib/types"

export function ScoreBadge({
  score,
  className,
}: {
  score: number
  className?: string
}) {
  const tone = scoreTone(score)
  return (
    <span
      className={cn(
        "inline-flex min-w-9 items-center justify-center rounded-md border px-1.5 py-0.5 text-xs font-semibold tabular-nums",
        tone.badge,
        className,
      )}
    >
      {score}
    </span>
  )
}

export function DecisionBadge({
  decision,
  className,
}: {
  decision: Decision
  className?: string
}) {
  const style = DECISION_STYLES[decision]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        style.badge,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", style.dot)} />
      {style.label}
    </span>
  )
}

export function ReviewBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-review/30 bg-review/15 px-2 py-0.5 text-xs font-medium text-review-foreground",
        className,
      )}
    >
      <AlertCircle className="size-3" />
      Needs Review
    </span>
  )
}

export function ScoreRing({
  score,
  size = 56,
}: {
  score: number
  size?: number
}) {
  const tone = scoreTone(score)
  const stroke = 5
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Score ${score} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-border"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={cn("transition-all", tone.ring)}
          stroke="currentColor"
        />
      </svg>
      <span
        className={cn(
          "absolute inset-0 flex items-center justify-center text-sm font-semibold tabular-nums",
          tone.ring,
        )}
      >
        {score}
      </span>
    </div>
  )
}
