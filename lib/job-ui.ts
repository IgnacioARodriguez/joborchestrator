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
  ready_to_apply: "Ready to apply",
  discarded: "Discarded",
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

export function isActionableApplyDecision(
  decision: Decision,
  score: number,
): boolean {
  if (decision === "APPLY_NOW") return score >= 65
  if (decision === "APPLY_WITH_TAILORED_CV") return score >= 50
  return false
}

export function hasDecisionScoreMismatch(decision: Decision, score: number): boolean {
  return (
    (decision === "APPLY_NOW" || decision === "APPLY_WITH_TAILORED_CV") &&
    !isActionableApplyDecision(decision, score)
  )
}

export function rankingSummaryText(
  decision: Decision,
  score: number,
  summary: string,
): string {
  if (hasDecisionScoreMismatch(decision, score)) {
    return "Ranking incomplete: the recommendation and score disagree. Re-run ranking before treating this as an apply candidate."
  }
  return summary || "No ranking explanation available."
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

export function applyUrlForJob(job: JobPosting): string {
  if (job.apply_type === "external" && job.external_apply_url) {
    return job.external_apply_url
  }
  return job.apply_url || job.url
}

export function applicantLabel(job: JobPosting): string | null {
  if (typeof job.applicant_count === "number") {
    return `${job.applicant_count.toLocaleString()} applicants`
  }
  return job.applicant_count_raw || null
}

export function salaryLabel(job: JobPosting): string | null {
  const currency = job.salary_currency || ""
  if (typeof job.salary_min !== "number" && typeof job.salary_max !== "number") {
    return null
  }
  if (job.salary_min === job.salary_max || typeof job.salary_max !== "number") {
    return formatSalaryValue(job.salary_min, currency)
  }
  if (typeof job.salary_min !== "number") {
    return formatSalaryValue(job.salary_max, currency)
  }
  return `${formatSalaryValue(job.salary_min, currency)}-${formatSalaryValue(job.salary_max, currency)}`
}

function formatSalaryValue(value: number | null | undefined, currency: string): string {
  if (typeof value !== "number") return ""
  const rounded = Number.isInteger(value) ? value : Math.round(value)
  const amount = rounded >= 1000 ? `${Math.round(rounded / 1000)}k` : rounded.toLocaleString()
  return currency ? `${amount} ${currency}` : amount
}
