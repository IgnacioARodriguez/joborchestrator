"use client"

import { useState } from "react"
import { Compass } from "lucide-react"
import { cn } from "@/lib/utils"
import { NAV_ITEMS, type Section } from "@/lib/nav"
import { useStore } from "@/lib/store"
import { DashboardScreen } from "@/components/screens/dashboard-screen"
import { RankingScreen } from "@/components/screens/ranking-screen"
import { NeedsReviewScreen } from "@/components/screens/needs-review-screen"
import { PipelineScreen } from "@/components/screens/pipeline-screen"
import { ImportScreen } from "@/components/screens/import-screen"
import { JobDetailDrawer } from "@/components/job-detail-drawer"

const SECTION_TITLES: Record<Section, string> = {
  dashboard: "Dashboard",
  ranking: "Ranking",
  review: "Needs Review",
  pipeline: "Pipeline",
  import: "Import",
}

export function AppShell() {
  const [section, setSection] = useState<Section>("dashboard")
  const [openJobId, setOpenJobId] = useState<string | null>(null)
  const { jobs } = useStore()

  const reviewCount = jobs.filter((j) => j.review.requires_llm_review).length

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
                  {item.id === "review" && reviewCount > 0 && (
                    <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-review/20 px-1.5 text-xs font-semibold text-review-foreground">
                      {reviewCount}
                    </span>
                  )}
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
            {section === "dashboard" && (
              <DashboardScreen onOpenJob={setOpenJobId} onNavigate={navigate} />
            )}
            {section === "ranking" && <RankingScreen onOpenJob={setOpenJobId} />}
            {section === "review" && (
              <NeedsReviewScreen onOpenJob={setOpenJobId} />
            )}
            {section === "pipeline" && (
              <PipelineScreen onOpenJob={setOpenJobId} />
            )}
            {section === "import" && <ImportScreen onNavigate={navigate} />}
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
                <span className="relative">
                  <Icon className="size-5" />
                  {item.id === "review" && reviewCount > 0 && (
                    <span className="absolute -right-2 -top-1.5 inline-flex min-w-4 items-center justify-center rounded-full bg-review px-1 text-[9px] font-bold text-background">
                      {reviewCount}
                    </span>
                  )}
                </span>
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
