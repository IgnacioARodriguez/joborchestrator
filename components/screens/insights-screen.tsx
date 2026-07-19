"use client"

import { useEffect, useMemo, useState } from "react"
import { DashboardCharts } from "@/components/dashboard-charts"
import { KpiCard } from "@/components/kpi-card"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { computeKpis } from "@/lib/stats"
import { api } from "@/lib/api"
import type { ApplicationRecord, LLMFeedbackSummary, ResumeVariant } from "@/lib/types"
import { Briefcase, CheckCircle2, Gauge, Send, Sparkles } from "lucide-react"

const RESPONSE_STATUSES = new Set(["recruiter_screen", "interview", "technical", "offer"])

interface RateRow {
  label: string
  total: number
  responses: number
}

function responseRate(row: RateRow) {
  if (!row.total) return "0%"
  return `${Math.round((row.responses / row.total) * 100)}%`
}

function labelChannel(channel: string) {
  return channel.replace("_", " ")
}

function ageBucket(application: ApplicationRecord) {
  if (!application.job_first_seen_at) return "Unknown age"
  const submittedAt = application.submitted_at || application.created_at
  const ageMs = new Date(submittedAt).getTime() - new Date(application.job_first_seen_at).getTime()
  if (!Number.isFinite(ageMs) || ageMs < 0) return "Unknown age"
  const days = ageMs / 86_400_000
  if (days <= 2) return "0-2 days old"
  if (days <= 7) return "3-7 days old"
  if (days <= 14) return "8-14 days old"
  return "15+ days old"
}

function groupedRates(applications: ApplicationRecord[], labelFor: (application: ApplicationRecord) => string) {
  const groups = new Map<string, RateRow>()
  for (const application of applications) {
    const label = labelFor(application)
    const row = groups.get(label) ?? { label, total: 0, responses: 0 }
    row.total += 1
    if (RESPONSE_STATUSES.has(application.status)) row.responses += 1
    groups.set(label, row)
  }
  return [...groups.values()].sort((a, b) => b.total - a.total || a.label.localeCompare(b.label))
}

function RateTable({ title, rows }: { title: string; rows: RateRow[] }) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Segment</th>
              <th className="px-4 py-2 text-right font-medium">Applied</th>
              <th className="px-4 py-2 text-right font-medium">Responses</th>
              <th className="px-4 py-2 text-right font-medium">Rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((row) => (
              <tr key={row.label} className="border-t border-border">
                <td className="px-4 py-2 capitalize text-foreground">{row.label}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{row.total}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{row.responses}</td>
                <td className="px-4 py-2 text-right tabular-nums font-medium text-foreground">{responseRate(row)}</td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-8 text-center text-sm text-muted-foreground" colSpan={4}>No application data yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function FeedbackSummaryPanel({ summary }: { summary: LLMFeedbackSummary | null }) {
  const artifacts = summary ? Object.entries(summary.by_artifact) : []
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">LLM feedback</h2>
      </div>
      <div className="grid gap-3 p-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted-foreground">Total signals</p>
          <p className="text-2xl font-semibold text-foreground">{summary?.total ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Accepted/applied</p>
          <p className="text-2xl font-semibold text-success">{summary?.positive ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Rejected</p>
          <p className="text-2xl font-semibold text-destructive">{summary?.negative ?? 0}</p>
        </div>
      </div>
      <div className="border-t border-border px-4 py-3">
        {artifacts.length ? (
          <div className="flex flex-wrap gap-2">
            {artifacts.map(([artifact, row]) => (
              <span key={artifact} className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
                {artifact.replaceAll("_", " ")}: {row.total}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No feedback captured yet.</p>
        )}
      </div>
    </section>
  )
}

export function InsightsScreen() {
  const { jobs } = useStore()
  const [applications, setApplications] = useState<ApplicationRecord[]>([])
  const [resumes, setResumes] = useState<ResumeVariant[]>([])
  const [feedbackSummary, setFeedbackSummary] = useState<LLMFeedbackSummary | null>(null)
  const kpis = computeKpis(jobs)

  useEffect(() => {
    let cancelled = false
    async function loadFeedbackLoop() {
      const [applicationData, resumeData, feedbackData] = await Promise.all([
        api.getApplications(),
        api.getResumes(),
        api.getLlmFeedbackSummary(),
      ])
      if (!cancelled) {
        setApplications(applicationData.applications)
        setResumes(resumeData.resumes)
        setFeedbackSummary(feedbackData.summary)
      }
    }
    void loadFeedbackLoop().catch(() => {
      if (!cancelled) {
        setApplications([])
        setResumes([])
        setFeedbackSummary(null)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  const resumeLabels = useMemo(() => new Map(resumes.map((resume) => [resume.id, resume.label])), [resumes])
  const submittedApplications = applications.filter((application) => application.status !== "preparing")
  const byChannel = groupedRates(submittedApplications, (application) => labelChannel(application.channel))
  const byResume = groupedRates(submittedApplications, (application) =>
    application.resume_variant_id ? resumeLabels.get(application.resume_variant_id) ?? `Resume #${application.resume_variant_id}` : "No variant",
  )
  const byAge = groupedRates(submittedApplications, ageBucket)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Insights"
        title="Performance signals"
        description="Descriptive funnel, response rates and source trends. No trained ML model is used here."
      />
      <section className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard label="Total opportunities" value={kpis.total} icon={Briefcase} hint="all time" />
        <KpiCard label="Apply now" value={kpis.applyCandidates} icon={Send} tone="primary" hint="ready" />
        <KpiCard label="Applied" value={kpis.applied} icon={CheckCircle2} tone="success" />
        <KpiCard label="New this week" value={kpis.newThisWeek} icon={Sparkles} hint="7 days" tone="warning" />
        <KpiCard label="Average score" value={kpis.avgScore} icon={Gauge} />
      </section>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <RateTable title="Response by channel" rows={byChannel} />
            <RateTable title="Response by resume variant" rows={byResume} />
            <RateTable title="Response by job age at apply" rows={byAge} />
          </div>
          <FeedbackSummaryPanel summary={feedbackSummary} />
          <DashboardCharts jobs={jobs} />
        </div>
      </div>
    </div>
  )
}
