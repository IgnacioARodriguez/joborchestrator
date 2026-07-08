import type { Decision, JobPosting, PipelineStatus } from "./types"

// Presentation config shared across screens. Kept separate from data + types.

export interface DecisionStyle {
  label: string
  // Tailwind classes using semantic status tokens defined in globals.css.
  badge: string
  dot: string
}

export const DECISION_STYLES: Record<Decision, DecisionStyle> = {
  APPLY_NOW: {
    label: "Apply Now",
    badge: "bg-success/15 text-success-foreground border-success/25",
    dot: "bg-success",
  },
  APPLY_WITH_TAILORED_CV: {
    label: "Tailor CV",
    badge: "bg-info/15 text-info-foreground border-info/25",
    dot: "bg-info",
  },
  MAYBE: {
    label: "Maybe",
    badge: "bg-warning/20 text-warning-foreground border-warning/30",
    dot: "bg-warning",
  },
  SKIP: {
    label: "Skip",
    badge: "bg-neutral-muted text-neutral-muted-foreground border-border",
    dot: "bg-neutral-muted-foreground",
  },
  AVOID: {
    label: "Avoid",
    badge: "bg-destructive/12 text-destructive border-destructive/25",
    dot: "bg-destructive",
  },
}

export const PIPELINE_LABELS: Record<PipelineStatus, string> = {
  new: "New",
  shortlisted: "Shortlisted",
  applied: "Applied",
  discarded: "Discarded",
  opened: "Opened",
}

export function scoreTone(score: number): {
  badge: string
  ring: string
} {
  if (score >= 80)
    return {
      badge: "bg-success/15 text-success-foreground border-success/25",
      ring: "text-success",
    }
  if (score >= 65)
    return {
      badge: "bg-info/15 text-info-foreground border-info/25",
      ring: "text-info",
    }
  if (score >= 45)
    return {
      badge: "bg-warning/20 text-warning-foreground border-warning/30",
      ring: "text-warning",
    }
  return {
    badge: "bg-neutral-muted text-neutral-muted-foreground border-border",
    ring: "text-muted-foreground",
  }
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = Math.max(0, now - then)
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  return `${weeks}w ago`
}

export function isNewThisWeek(job: JobPosting): boolean {
  const seen = new Date(job.first_seen_at).getTime()
  return Date.now() - seen <= 7 * 24 * 60 * 60 * 1000
}
