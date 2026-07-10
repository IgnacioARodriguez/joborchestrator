"use client"

import {
  Briefcase,
  CheckCircle2,
  Send,
  Sparkles,
  Gauge,
  ArrowRight,
  Download,
  RefreshCw,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { KpiCard } from "@/components/kpi-card"
import { DashboardCharts } from "@/components/dashboard-charts"
import { JobCompactCard } from "@/components/job-compact-card"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { computeKpis } from "@/lib/stats"
import type { Section } from "@/lib/nav"
import { isActionableApplyDecision } from "@/lib/job-ui"

function TodayCard({
  title,
  jobs,
  onOpenJob,
  emptyText,
  action,
}: {
  title: string
  jobs: ReturnType<typeof useStore>["jobs"]
  onOpenJob: (id: string) => void
  emptyText: string
  action?: React.ReactNode
}) {
  return (
    <Card className="min-h-0 gap-3">
      <CardHeader className="flex-row items-center justify-between pb-0">
        <CardTitle className="text-sm">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto">
        {jobs.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-xs text-muted-foreground">
            {emptyText}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {jobs.map((job) => (
              <JobCompactCard
                key={job.id}
                job={job}
                onOpen={onOpenJob}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function DashboardScreen({
  onOpenJob,
  onNavigate,
}: {
  onOpenJob: (id: string) => void
  onNavigate: (section: Section) => void
}) {
  const { jobs, jobsMeta, loading, refresh } = useStore()
  const kpis = computeKpis(jobs)

  const topCandidates = [...jobs]
    .filter(
      (j) =>
        j.pipeline_status !== "discarded" &&
        isActionableApplyDecision(
          j.ranking.decision,
          j.ranking.final_score,
        ),
    )
    .sort((a, b) => b.ranking.final_score - a.ranking.final_score)
    .slice(0, 5)

  const recentlyOpened = [...jobs]
    .filter((j) => j.pipeline_status === "opened")
    .sort(
      (a, b) =>
        new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime(),
    )
    .slice(0, 5)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        description={`${jobsMeta?.returned ?? jobs.length} opportunities loaded${jobsMeta?.db_mode ? ` from ${jobsMeta.db_mode}` : ""}. Track ranking quality, pipeline movement, and today’s best next actions.`}
        actions={
          <>
            <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw data-icon="inline-start" className={loading ? "animate-spin" : undefined} />
              Sync
            </Button>
            <Button variant="outline" disabled title="Export will be wired when a backend export endpoint exists">
              <Download data-icon="inline-start" />
              Export
            </Button>
          </>
        }
      />

      <section className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          label="Total opportunities"
          value={kpis.total}
          icon={Briefcase}
          hint="all time"
          description="Imported and ranked opportunities."
        />
        <KpiCard
          label="Apply now"
          value={kpis.applyCandidates}
          icon={Send}
          tone="primary"
          hint="ready"
          description="Strong matches worth action."
        />
        <KpiCard
          label="Applied"
          value={kpis.applied}
          icon={CheckCircle2}
          tone="success"
          description="Moved through the pipeline."
        />
        <KpiCard
          label="New this week"
          value={kpis.newThisWeek}
          icon={Sparkles}
          hint="7 days"
          tone="warning"
          description="Fresh roles since last scan."
        />
        <KpiCard
          label="Average score"
          value={kpis.avgScore}
          icon={Gauge}
          description="Mean ranking quality."
        />
      </section>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-col gap-4">
          <DashboardCharts jobs={jobs} />

          <section className="grid min-h-[360px] grid-cols-1 gap-4 lg:grid-cols-2">
            <TodayCard
              title="Top application candidates"
              jobs={topCandidates}
              onOpenJob={onOpenJob}
              emptyText="No apply candidates right now."
              action={
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => onNavigate("ranking")}
                >
                  Ranking
                  <ArrowRight data-icon="inline-end" />
                </Button>
              }
            />
            <TodayCard
              title="Recently opened"
              jobs={recentlyOpened}
              onOpenJob={onOpenJob}
              emptyText="Nothing opened yet."
            />
          </section>
        </div>
      </div>
    </div>
  )
}
