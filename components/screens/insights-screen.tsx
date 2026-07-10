"use client"

import { DashboardCharts } from "@/components/dashboard-charts"
import { KpiCard } from "@/components/kpi-card"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { computeKpis } from "@/lib/stats"
import { Briefcase, CheckCircle2, Gauge, Send, Sparkles } from "lucide-react"

export function InsightsScreen() {
  const { jobs } = useStore()
  const kpis = computeKpis(jobs)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Insights"
        title="Performance signals"
        description="Descriptive funnel, source and score trends for the current opportunity set."
      />
      <section className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard label="Total opportunities" value={kpis.total} icon={Briefcase} hint="all time" />
        <KpiCard label="Apply now" value={kpis.applyCandidates} icon={Send} tone="primary" hint="ready" />
        <KpiCard label="Applied" value={kpis.applied} icon={CheckCircle2} tone="success" />
        <KpiCard label="New this week" value={kpis.newThisWeek} icon={Sparkles} hint="7 days" tone="warning" />
        <KpiCard label="Average score" value={kpis.avgScore} icon={Gauge} />
      </section>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <DashboardCharts jobs={jobs} />
      </div>
    </div>
  )
}
