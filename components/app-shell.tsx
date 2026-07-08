"use client"

import { useEffect, useState } from "react"
import { Compass, LoaderCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { NAV_ITEMS, type Section } from "@/lib/nav"
import { useStore } from "@/lib/store"
import { DashboardScreen } from "@/components/screens/dashboard-screen"
import { RankingScreen } from "@/components/screens/ranking-screen"
import { PipelineScreen } from "@/components/screens/pipeline-screen"
import { ProfileScreen } from "@/components/screens/profile-screen"
import { OpsScreen } from "@/components/screens/ops-screen"
import { JobDetailDrawer } from "@/components/job-detail-drawer"

const SECTION_TITLES: Record<Section, string> = {
  dashboard: "Dashboard",
  ranking: "Ranking",
  pipeline: "Pipeline",
  profile: "Profile",
  ops: "Operations",
}

function DataLoadingBanner() {
  const { loading, backendOnline, jobs, jobsMeta } = useStore()
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!loading) {
      return
    }
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 500)
    return () => window.clearInterval(timer)
  }, [loading])

  if (!loading && backendOnline && jobs.length > 0) {
    return (
      <div className="mb-4 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        Loaded {jobsMeta?.returned ?? jobs.length} opportunities
        {jobsMeta?.total && jobsMeta.total !== (jobsMeta.returned ?? jobs.length)
          ? ` of ${jobsMeta.total}`
          : ""}
        {jobsMeta?.db_mode ? ` from ${jobsMeta.db_mode}` : ""}.
      </div>
    )
  }

  if (!loading) return null

  const detail =
    elapsed >= 8
      ? "Still syncing from the cloud database. Cold starts can take a moment after deploy."
      : "Loading opportunities from the backend."

  return (
    <div className="mb-4 flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 p-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <LoaderCircle className="size-4 animate-spin" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">
          Loading opportunities
        </p>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </div>
      <span className="hidden rounded-md border border-primary/20 bg-background px-2 py-1 text-xs tabular-nums text-muted-foreground sm:inline-flex">
        {elapsed}s
      </span>
    </div>
  )
}

export function AppShell() {
  const [section, setSection] = useState<Section>("dashboard")
  const [openJobId, setOpenJobId] = useState<string | null>(null)

  function navigate(next: Section) {
    setSection(next)
  }

  return (
    <div className="min-h-dvh bg-background">
      <div className="mx-auto flex w-full max-w-6xl">
        {/* Desktop sidebar */}
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border bg-sidebar px-3 py-5 lg:flex">
          <div className="flex items-center gap-2 px-2 pb-6">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Compass className="size-4.5" />
            </div>
            <span className="text-sm font-semibold text-sidebar-foreground">
              Job Orchestrator
            </span>
          </div>
          <nav className="flex flex-col gap-1">
            {NAV_ITEMS.map((item) => {
              const active = section === item.id
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(item.id)}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                  )}
                >
                  <Icon className="size-4.5" />
                  <span className="flex-1 text-left">{item.label}</span>
                </button>
              )
            })}
          </nav>
        </aside>

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-background/85 px-4 py-3 backdrop-blur lg:px-6">
            <div className="flex items-center gap-2">
              <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground lg:hidden">
                <Compass className="size-4" />
              </div>
              <h1 className="text-base font-semibold text-foreground">
                {SECTION_TITLES[section]}
              </h1>
            </div>
          </header>

          <main className="flex-1 px-4 pb-24 pt-4 lg:px-6 lg:pb-10">
            <DataLoadingBanner />
            {section === "dashboard" && (
              <DashboardScreen onOpenJob={setOpenJobId} onNavigate={navigate} />
            )}
            {section === "ranking" && <RankingScreen onOpenJob={setOpenJobId} />}
            {section === "pipeline" && (
              <PipelineScreen onOpenJob={setOpenJobId} />
            )}
            {section === "profile" && <ProfileScreen />}
            {section === "ops" && <OpsScreen />}
          </main>
        </div>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-md items-stretch justify-around">
          {NAV_ITEMS.map((item) => {
            const active = section === item.id
            const Icon = item.icon
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => navigate(item.id)}
                className={cn(
                  "relative flex flex-1 flex-col items-center gap-0.5 px-1 py-2 text-[10px] font-medium transition-colors",
                  active ? "text-primary" : "text-muted-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className="size-5" />
                <span className="text-center leading-tight">{item.label}</span>
              </button>
            )
          })}
        </div>
      </nav>

      <JobDetailDrawer
        jobId={openJobId}
        onClose={() => setOpenJobId(null)}
      />
    </div>
  )
}
