"use client"

import { Building2, Inbox } from "lucide-react"
import { toast } from "sonner"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import type { ApplicationRecord, ApplicationStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const APPLICATION_COLUMNS: ApplicationStatus[] = [
  "preparing",
  "submitted",
  "recruiter_screen",
  "interview",
  "technical",
  "offer",
  "rejected",
  "withdrawn",
]

const LABELS: Record<ApplicationStatus, string> = {
  preparing: "Preparing",
  submitted: "Submitted",
  recruiter_screen: "Recruiter screen",
  interview: "Interview",
  technical: "Technical",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
}

function ApplicationCard({ application }: { application: ApplicationRecord }) {
  const { setApplicationStatus } = useStore()
  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
      <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
        {application.job_title || `Application ${application.id}`}
      </h3>
      <p className="mt-1 flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        <Building2 className="size-3.5 shrink-0" />
        <span className="truncate">{application.company || "Unknown company"}</span>
      </p>
      <p className="mt-1 text-[11px] uppercase text-muted-foreground/80">{application.channel.replace("_", " ")}</p>
      <div className="mt-3 flex flex-wrap gap-1">
        {APPLICATION_COLUMNS.filter((status) => status !== application.status).map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => {
              setApplicationStatus(application.id, status)
              toast.success(`Moved to ${LABELS[status]}`, { description: application.job_title || undefined })
            }}
            className="rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {LABELS[status]}
          </button>
        ))}
      </div>
    </article>
  )
}

export function ApplicationsScreen() {
  const { applications } = useStore()
  const byStatus = (status: ApplicationStatus) =>
    applications
      .filter((application) => application.status === status)
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Applications"
        title="Application kanban"
        description="Only real applications live here, separate from discovered opportunities."
      />
      <div className="min-h-0 flex-1 overflow-x-auto pb-2">
        <div className="grid min-w-[1320px] grid-cols-8 gap-3">
          {APPLICATION_COLUMNS.map((status) => {
            const items = byStatus(status)
            return (
              <section
                key={status}
                className={cn("flex h-[calc(100dvh-190px)] min-h-[420px] flex-col rounded-lg border border-border bg-muted/25", (status === "rejected" || status === "withdrawn") && "opacity-90")}
              >
                <div className="shrink-0 border-b border-border bg-card px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold text-foreground">{LABELS[status]}</h2>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">{items.length}</span>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
                  {items.length === 0 ? (
                    <Empty className="h-full border border-dashed bg-background/70">
                      <EmptyHeader>
                        <EmptyMedia variant="icon"><Inbox /></EmptyMedia>
                        <EmptyTitle>Empty lane</EmptyTitle>
                        <EmptyDescription>{LABELS[status]} applications appear here.</EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {items.map((application) => <ApplicationCard key={application.id} application={application} />)}
                    </div>
                  )}
                </div>
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}
