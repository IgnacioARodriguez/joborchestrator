import type { Decision, JobPosting, JobSource } from "./types"
import { DECISION_ORDER } from "./types"
import { isActionableApplyDecision, isNewThisWeek } from "./job-ui"

export function computeKpis(jobs: JobPosting[]) {
  const total = jobs.length
  const applyCandidates = jobs.filter(
    (j) => isActionableApplyDecision(j.ranking.decision, j.ranking.final_score),
  ).length
  const applied = jobs.filter((j) => j.pipeline_status === "applied").length
  const newThisWeek = jobs.filter(isNewThisWeek).length
  const avgScore = total
    ? Math.round(
        jobs.reduce((sum, j) => sum + j.ranking.final_score, 0) / total,
      )
    : 0
  return { total, applyCandidates, applied, newThisWeek, avgScore }
}

export function decisionDistribution(jobs: JobPosting[]) {
  const counts: Record<Decision, number> = {
    APPLY_NOW: 0,
    APPLY_WITH_TAILORED_CV: 0,
    MAYBE: 0,
    SKIP: 0,
    AVOID: 0,
  }
  for (const j of jobs) counts[j.ranking.decision]++
  return DECISION_ORDER.map((d) => ({ decision: d, count: counts[d] }))
}

export function sourceDistribution(jobs: JobPosting[]) {
  const sources: JobSource[] = ["LinkedIn", "Greenhouse", "Lever", "Ashby", "API"]
  const counts = Object.fromEntries(sources.map((s) => [s, 0])) as Record<
    JobSource,
    number
  >
  for (const j of jobs) counts[j.source]++
  return sources.map((s) => ({ source: s, count: counts[s] }))
}

export function weeklyTrend(jobs: JobPosting[]) {
  // Buckets by day for the last 7 days based on first_seen_at.
  const days: { day: string; label: string; count: number }[] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    d.setDate(d.getDate() - i)
    days.push({
      day: d.toISOString().slice(0, 10),
      label: d.toLocaleDateString("en-US", { weekday: "short" }),
      count: 0,
    })
  }
  for (const j of jobs) {
    const key = new Date(j.first_seen_at).toISOString().slice(0, 10)
    const bucket = days.find((x) => x.day === key)
    if (bucket) bucket.count++
  }
  return days
}

export function pipelineFunnel(jobs: JobPosting[]) {
  const shortlisted = jobs.filter(
    (j) =>
      j.pipeline_status === "shortlisted" ||
      j.pipeline_status === "applied",
  ).length
  const applied = jobs.filter((j) => j.pipeline_status === "applied").length
  const discarded = jobs.filter((j) => j.pipeline_status === "discarded").length
  return [
    { stage: "New", count: jobs.length },
    { stage: "Shortlisted", count: shortlisted },
    { stage: "Applied", count: applied },
    { stage: "Discarded", count: discarded },
  ]
}

export function scoreHistogram(jobs: JobPosting[]) {
  const buckets = [
    { range: "0–39", min: 0, max: 39, count: 0 },
    { range: "40–59", min: 40, max: 59, count: 0 },
    { range: "60–74", min: 60, max: 74, count: 0 },
    { range: "75–84", min: 75, max: 84, count: 0 },
    { range: "85–100", min: 85, max: 100, count: 0 },
  ]
  for (const j of jobs) {
    const s = j.ranking.final_score
    const b = buckets.find((x) => s >= x.min && s <= x.max)
    if (b) b.count++
  }
  return buckets.map((b) => ({ range: b.range, count: b.count }))
}
