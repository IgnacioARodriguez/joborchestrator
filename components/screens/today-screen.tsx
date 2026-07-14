"use client"

import { ArrowRight, Bell, Briefcase, CheckCircle2, CircleHelp, Clock, Send, WandSparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { JobCompactCard } from "@/components/job-compact-card"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import type { Section } from "@/lib/nav"
import type { JobPosting } from "@/lib/types"

function Queue({
  title,
  icon: Icon,
  jobs,
  empty,
  actionLabel,
  onAction,
  onOpenJob,
}: {
  title: string
  icon: typeof Briefcase
  jobs: JobPosting[]
  empty: string
  actionLabel: string
  onAction: () => void
  onOpenJob: (id: string) => void
}) {
  return (
    <Card className="min-h-[260px] gap-3">
      <CardHeader className="flex-row items-center justify-between pb-0">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Icon className="size-4 text-primary" />
          {title}
        </CardTitle>
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onAction}>
          {actionLabel}
          <ArrowRight data-icon="inline-end" />
        </Button>
      </CardHeader>
      <CardContent>
        {jobs.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-8 text-center text-xs text-muted-foreground">
            {empty}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {jobs.slice(0, 4).map((job) => (
              <JobCompactCard key={job.id} job={job} onOpen={onOpenJob} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function TodayScreen({
  onOpenJob,
  onNavigate,
}: {
  onOpenJob: (id: string) => void
  onNavigate: (section: Section) => void
}) {
  const { jobs, applications } = useStore()
  const ordered = [...jobs].sort((a, b) => b.priority.priority_score - a.priority.priority_score)
  const needsReview = ordered.filter((job) => job.priority.next_action === "Review")
  const ready = ordered.filter((job) => ["Apply now", "Prepare"].includes(job.priority.next_action))
  const waitingAnswerJobs = applications
    .filter((application) => application.status === "preparing")
    .map((application) => jobs.find((job) => Number(job.id) === application.job_id))
    .filter((job): job is JobPosting => Boolean(job))
  const followUpJobs = applications
    .filter((application) => application.status === "submitted" || application.status === "recruiter_screen")
    .map((application) => jobs.find((job) => Number(job.id) === application.job_id))
    .filter((job): job is JobPosting => Boolean(job))
  const interviewJobs = applications
    .filter((application) => application.status === "interview" || application.status === "technical")
    .map((application) => jobs.find((job) => Number(job.id) === application.job_id))
    .filter((job): job is JobPosting => Boolean(job))
  const automationFailures = jobs.filter((job) => job.ranking.decision === "MAYBE" && job.ranking.final_score === 0)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Today"
        title="Action queue"
        description="One surface for review, apply, follow-up and preparation work."
        actions={
          <Button variant="outline" onClick={() => onNavigate("insights")}>
            Insights
            <ArrowRight data-icon="inline-end" />
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <Queue title="Review" icon={CircleHelp} jobs={needsReview} empty="No ranked jobs waiting for review." actionLabel="Review" onAction={() => onNavigate("review")} onOpenJob={onOpenJob} />
          <Queue title="Apply now / Prepare" icon={Send} jobs={ready} empty="No high-priority apply candidates." actionLabel="Apply" onAction={() => onNavigate("review")} onOpenJob={onOpenJob} />
          <Queue title="Waiting for your answer" icon={Bell} jobs={waitingAnswerJobs} empty="No preparing applications need input." actionLabel="Applications" onAction={() => onNavigate("applications")} onOpenJob={onOpenJob} />
          <Queue title="Follow up today" icon={Clock} jobs={followUpJobs} empty="No follow-ups due in the current queue." actionLabel="Applications" onAction={() => onNavigate("applications")} onOpenJob={onOpenJob} />
          <Queue title="Interviews to prepare" icon={CheckCircle2} jobs={interviewJobs} empty="No interviews or technical stages yet." actionLabel="Applications" onAction={() => onNavigate("applications")} onOpenJob={onOpenJob} />
          <Queue title="Automation failures" icon={WandSparkles} jobs={automationFailures} empty="No automation failures detected." actionLabel="Automations" onAction={() => onNavigate("automations")} onOpenJob={onOpenJob} />
        </div>
      </div>
    </div>
  )
}
