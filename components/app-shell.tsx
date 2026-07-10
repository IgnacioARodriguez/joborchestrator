"use client"

import { useEffect, useState } from "react"
import {
  Compass,
  Download,
  LoaderCircle,
  RefreshCw,
  Settings,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { NAV_ITEMS, type Section } from "@/lib/nav"
import { useStore } from "@/lib/store"
import { Button } from "@/components/ui/button"
import { DashboardScreen } from "@/components/screens/dashboard-screen"
import { RankingScreen } from "@/components/screens/ranking-screen"
import { PipelineScreen } from "@/components/screens/pipeline-screen"
import { ProfileScreen } from "@/components/screens/profile-screen"
import { OpsScreen } from "@/components/screens/ops-screen"
import { JobDetailDrawer } from "@/components/job-detail-drawer"

function DataLoadingBanner() {
  const { loading } = useStore()
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

  if (!loading) return null

  const detail =
    elapsed >= 8
      ? "Still syncing from the cloud database. Cold starts can take a moment after deploy."
      : "Loading opportunities from the backend."

  return (
    <div className="mb-3 flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 p-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
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
  const { jobs, jobsMeta, backendOnline, loading, refresh } = useStore()

  function navigate(next: Section) {
    setSection(next)
  }

  return (
    <div className="min-h-dvh bg-background lg:h-dvh lg:overflow-hidden">
      <div className="flex min-h-dvh w-full lg:h-full">
        {/* Desktop sidebar */}
        <aside className="sticky top-0 hidden h-dvh w-[256px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-4 py-5 lg:flex">
          <div className="flex items-center gap-3 px-2 pb-7">
            <div className="flex size-10 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-[0_8px_18px_rgba(65,105,225,0.22)]">
              <Compass className="size-5" />
            </div>
            <div>
              <span className="block text-sm font-semibold text-sidebar-foreground">
                Job Orchestrator
              </span>
              <span className="text-xs text-muted-foreground">Career ops system</span>
            </div>
          </div>
          <nav className="flex flex-col gap-1.5">
            {NAV_ITEMS.map((item) => {
              const active = section === item.id
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(item.id)}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_rgba(65,105,225,0.08)]"
                      : "text-muted-foreground hover:bg-muted hover:text-sidebar-foreground",
                  )}
                >
                  <Icon className="size-4.5 shrink-0" />
                  <span className="flex-1 text-left">{item.label}</span>
                </button>
              )
            })}
          </nav>
          <div className="mt-auto rounded-2xl border border-border bg-muted/40 p-4">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-xl bg-success/10 text-success-foreground">
                <Zap className="size-4" />
              </span>
              <div>
                <p className="text-xs font-semibold text-foreground">
                  {backendOnline ? "System ready" : "API offline"}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {jobsMeta?.db_mode ? `Synced from ${jobsMeta.db_mode}` : `${jobs.length} opportunities`}
                </p>
              </div>
            </div>
          </div>
        </aside>

        {/* Main column */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex min-h-12 items-center justify-between border-b border-border/80 bg-background/90 px-4 backdrop-blur lg:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground lg:hidden">
                <Compass className="size-4" />
              </div>
              <span className="text-xs text-muted-foreground">
                {jobsMeta?.returned ?? jobs.length} jobs
                {jobsMeta?.db_mode ? ` · ${jobsMeta.db_mode}` : ""}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={loading}
                onClick={() => void refresh()}
              >
                {loading ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <RefreshCw data-icon="inline-start" />}
                Sync
              </Button>
              <Button variant="outline" size="icon-sm" aria-label="Export" disabled title="Export needs a backend endpoint">
                <Download className="size-4" />
              </Button>
              <Button variant="outline" size="icon-sm" aria-label="Settings" onClick={() => navigate("ops")}>
                <Settings className="size-4" />
              </Button>
            </div>
          </header>

          <main className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 flex-col px-4 pb-24 pt-3 sm:px-6 lg:px-6 lg:pb-6">
            <div className="shrink-0">
              <DataLoadingBanner />
            </div>
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
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
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
