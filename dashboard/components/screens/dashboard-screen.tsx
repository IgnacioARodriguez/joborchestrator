"use client"

import {
  Briefcase,
  CheckCircle2,
  ClipboardCheck,
  Send,
  Sparkles,
  Gauge,
  ArrowRight,
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
import { JobRow } from "@/components/job-row"
import { useStore } from "@/lib/store"
import { computeKpis } from "@/lib/stats"
import type { Section } from "@/lib/nav"

function TodayCard({
  title,
  jobs,
  onOpenJob,
  showReview,
  emptyText,
  action,
}: {
  title: string
  jobs: ReturnType<typeof useStore>["jobs"]
  onOpenJob: (id: string) => void
  showReview?: boolean
  emptyText: string
  action?: React.ReactNode
}) {
  return (
    <Card className="gap-2">
      <CardHeader className="flex-row items-center justify-between pb-0">
        <CardTitle className="text-sm">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>
        {jobs.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-muted-foreground">
            {emptyText}
          </p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {jobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onOpen={onOpenJob}
                showReview={showReview}
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
  const { jobs } = useStore()
  const kpis = computeKpis(jobs)

  const topToReview = [...jobs]
    .filter(
      (j) =>
        j.pipeline_status !== "discarded" &&
        (j.ranking.decision === "APPLY_NOW" ||
          j.ranking.decision === "APPLY_WITH_TAILORED_CV"),
    )
    .sort((a, b) => b.ranking.final_score - a.ranking.final_score)
    .slice(0, 5)

  const needsReview = jobs
    .filter((j) => j.review.requires_llm_review)
    .slice(0, 5)

  const recentlyOpened = [...jobs]
    .filter((j) => j.pipeline_status === "opened")
    .sort(
      (a, b) =>
        new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime(),
    )
    .slice(0, 5)

  return (
    <div className="flex flex-col gap-5">
      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <KpiCard
          label="Total"
          value={kpis.total}
          icon={Briefcase}
          hint="opportunities"
        />
        <KpiCard
          label="Apply"
          value={kpis.applyCandidates}
          icon={Send}
          tone="primary"
          hint="candidates"
        />
        <KpiCard
          label="Review"
          value={kpis.needsReview}
          icon={ClipboardCheck}
          tone="review"
          hint="needs LLM"
        />
        <KpiCard label="Applied" value={kpis.applied} icon={CheckCircle2} />
        <KpiCard
          label="New"
          value={kpis.newThisWeek}
          icon={Sparkles}
          hint="this week"
        />
        <KpiCard label="Avg score" value={kpis.avgScore} icon={Gauge} />
      </section>

      <DashboardCharts jobs={jobs} />

      <section className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <TodayCard
          title="Top jobs to review"
          jobs={topToReview}
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
          title="Needs ChatGPT review"
          jobs={needsReview}
          onOpenJob={onOpenJob}
          showReview
          emptyText="Review queue is clear."
          action={
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onNavigate("review")}
            >
              Queue
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
  )
}
