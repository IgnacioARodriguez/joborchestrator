"use client"

import Image from "next/image"
import { usePathname } from "next/navigation"
import { useCallback, useEffect, useState } from "react"
import {
  Activity,
  Compass,
  LoaderCircle,
  RefreshCw,
  Settings,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { LEGACY_SECTION_ALIASES, NAV_ITEMS, SECTION_PATHS, isPrimarySection, primarySectionFor, type Section } from "@/lib/nav"
import { useStore } from "@/lib/store"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { JobsScreen } from "@/components/screens/review-screen"
import { ApplicationsScreen } from "@/components/screens/applications-screen"
import { ProfileScreen } from "@/components/screens/profile-screen"
import { OpsScreen } from "@/components/screens/ops-screen"
import { InsightsScreen } from "@/components/screens/insights-screen"
import { PipelineScreen } from "@/components/screens/pipeline-screen"
import { SettingsScreen } from "@/components/screens/settings-screen"
import { JobDetailDrawer } from "@/components/job-detail-drawer"
import { ActivityCenter } from "@/components/activity-center"
import { toast } from "sonner"
import type { OperationRun, OpsStatus } from "@/lib/types"

type SearchState = "idle" | "searching" | "success" | "empty" | "error"

function scanProgressCopy(operation: OperationRun) {
  const message = operation.progress_message?.toLowerCase() ?? ""
  if (operation.status === "queued" || message.includes("queue") || message.includes("wait")) return "La búsqueda está en cola y comenzará cuando el asistente esté disponible."
  if (message.includes("linkedin")) return "Buscando oportunidades en LinkedIn y guardándolas a medida que aparecen."
  if (["greenhouse", "lever", "ashby", "ats"].some(value => message.includes(value))) return "Consultando portales de empresas y sistemas de empleo configurados."
  if (message.includes("search") || message.includes("api")) return "Consultando fuentes públicas de empleo con tus búsquedas configuradas."
  return "Consultando las fuentes configuradas y guardando oportunidades nuevas."
}

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

function OpsStatusBanner({
  status,
  onOpenOps,
}: {
  status: OpsStatus | null
  onOpenOps: () => void
}) {
  if (!status) return null
  const hasWork = status.local_worker_needed || status.ranking_worker_needed
  const hasFailure = status.summary.includes("failed")
  if (!hasWork && !hasFailure) return null
  return (
    <div className="mb-3 flex items-center gap-3 rounded-lg border border-border bg-card p-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Activity className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {status.summary}
        </p>
        <p className="text-xs text-muted-foreground">
          {hasWork
            ? "Hay tareas pendientes para revisar en configuración."
            : "Abre configuración para ver el detalle."}
        </p>
      </div>
      <Button variant="outline" size="sm" onClick={onOpenOps}>
        Configuración
      </Button>
    </div>
  )
}

function sectionFromPath(pathname: string): Section {
  if (pathname.startsWith("/apply")) return "apply"
  if (pathname.startsWith("/applications")) return "applications"
  if (pathname.startsWith("/settings")) return "settings"
  if (pathname.startsWith("/profile")) return "profile"
  if (pathname.startsWith("/automations") || pathname.startsWith("/ops")) return "automations"
  if (pathname.startsWith("/insights")) return "insights"
  return "jobs"
}

export function AppShell({ initialSection }: { initialSection?: Section }) {
  const pathname = usePathname()
  const [section, setSection] = useState<Section>(initialSection ?? sectionFromPath(pathname))
  const [openJobId, setOpenJobId] = useState<string | null>(null)
  const [searchState, setSearchState] = useState<SearchState>("idle")
  const [searchMessage, setSearchMessage] = useState<string | null>(null)
  const [searchOperationId, setSearchOperationId] = useState<number | null>(null)
  const [searchOperation, setSearchOperation] = useState<OperationRun | null>(null)
  const [opsStatus, setOpsStatus] = useState<OpsStatus | null>(null)
  const {
    jobs,
    jobsMeta,
    backendOnline,
    loading,
    preparationLoading,
    refresh,
    refreshPreparationQueue,
  } = useStore()
  const backendReady = backendOnline || jobsMeta !== null || jobs.length > 0
  const totalJobs = jobsMeta?.pipeline_counts?.all ?? jobsMeta?.unfiltered_total ?? jobsMeta?.total ?? jobs.length
  const currentLoading = section === "apply" ? preparationLoading : loading
  const linkedinScanActive = Boolean(
    opsStatus?.active_local_operations.some(
      (operation) => operation.type === "linkedin_scan" && ["queued", "running"].includes(operation.status),
    ),
  )
  const jobSearchActive = searchState === "searching" || Boolean(searchOperationId) || linkedinScanActive
  const activityOperations = [
    ...(opsStatus?.active_local_operations ?? []),
    ...(opsStatus?.latest_scan_operation ? [opsStatus.latest_scan_operation] : []),
  ].filter((operation, index, all) => all.findIndex((item) => item.id === operation.id) === index)

  function refreshCurrentSection() {
    if (section === "apply") return refreshPreparationQueue()
    return refresh()
  }

  function navigate(next: Section) {
    setSection(next)
    const primary = primarySectionFor(next)
    if (isPrimarySection(next)) {
      window.history.pushState(null, "", SECTION_PATHS[next])
    } else {
      window.history.pushState(null, "", `${SECTION_PATHS[primary]}#${next}`)
    }
  }

  useEffect(() => {
    function onPopState() {
      setSection(sectionFromPath(window.location.pathname))
    }
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [])

  const loadOpsStatus = useCallback(async () => {
    try {
      setOpsStatus(await api.getOpsStatus())
    } catch {
      setOpsStatus(null)
    }
  }, [])

  useEffect(() => {
    function syncHash() {
      const key = window.location.hash.replace("#", "")
      if (!key) return
      const aliased = LEGACY_SECTION_ALIASES[key]
      if (aliased) setSection(aliased)
    }
    syncHash()
    window.addEventListener("hashchange", syncHash)
    return () => window.removeEventListener("hashchange", syncHash)
  }, [])

  useEffect(() => {
    const poll = () => {
      void loadOpsStatus()
    }
    const initialTimer = window.setTimeout(poll, 0)
    const timer = window.setInterval(() => {
      poll()
    }, 10000)
    return () => {
      window.clearTimeout(initialTimer)
      window.clearInterval(timer)
    }
  }, [loadOpsStatus])

  useEffect(() => {
    if (!jobSearchActive || section !== "jobs") return
    const pollJobs = () => {
      void refresh()
    }
    const initialTimer = window.setTimeout(pollJobs, 0)
    const timer = window.setInterval(pollJobs, 4000)
    return () => {
      window.clearTimeout(initialTimer)
      window.clearInterval(timer)
    }
  }, [jobSearchActive, refresh, section])

  useEffect(() => {
    if (searchOperationId) return
    const latest = opsStatus?.latest_scan_operation
    if (!latest || !["queued", "running"].includes(latest.status)) return
    const timer = window.setTimeout(() => {
      setSearchOperationId(latest.id); setSearchOperation(latest); setSearchState("searching"); setSearchMessage(scanProgressCopy(latest))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [opsStatus, searchOperationId])

  useEffect(() => {
    if (!searchOperationId) return
    const operationId = searchOperationId
    let stopped = false
    let timer: number | undefined
    async function poll() {
      try {
        const operation = (await api.getOperation(operationId)).operation
        if (stopped) return
        setSearchOperation(operation)
        if (["queued", "running"].includes(operation.status)) { setSearchState("searching"); setSearchMessage(scanProgressCopy(operation)); timer = window.setTimeout(poll, 2500); return }
        setSearchOperationId(null); setSearchOperation(null)
        await Promise.all([refresh(), loadOpsStatus()])
        setSearchState(operation.status === "completed" ? "success" : "error")
        setSearchMessage(operation.status === "completed" ? "La búsqueda terminó y la lista de jobs ya está actualizada." : "La búsqueda se detuvo antes de completar todas las fuentes.")
      } catch { if (!stopped) timer = window.setTimeout(poll, 4000) }
    }
    void poll()
    return () => { stopped = true; if (timer !== undefined) window.clearTimeout(timer) }
  }, [loadOpsStatus, refresh, searchOperationId])

  async function scanFreshJobs() {
    setSearchState("searching")
    setSearchMessage(null)
    try {
      const response = await api.scanFresh()
      setSearchOperationId(response.operation_id)
      const message = response.already_running
        ? "La búsqueda ya estaba en curso."
        : response.progress_message || "Búsqueda iniciada. Los nuevos jobs aparecerán al sincronizar."
      setSearchState(response.already_running ? "success" : "success")
      setSearchMessage(message)
      toast.success(response.already_running ? "Búsqueda en curso" : "Búsqueda iniciada", {
        description: message,
      })
      await loadOpsStatus()
    } catch (error) {
      setSearchState("error")
      setSearchMessage("No se pudo completar la búsqueda.")
      toast.error("No se pudo completar la búsqueda", {
        description: error instanceof Error ? error.message : "La API no respondió.",
      })
    }
  }

  return (
    <div className="min-h-dvh bg-background lg:h-dvh lg:overflow-hidden">
      <div className="flex min-h-dvh w-full lg:h-full">
        {/* Desktop sidebar */}
        <aside className="sticky top-0 hidden h-dvh w-[256px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-4 py-5 lg:flex">
          <div className="px-2 pb-7">
            <Image
              src="/rocket-development-logo.png"
              alt="Rocket Development"
              width={190}
              height={53}
              priority
              className="h-12 w-[190px] object-contain object-left"
            />
          </div>
          <nav className="flex flex-col gap-1.5">
            {NAV_ITEMS.map((item) => {
              const active = primarySectionFor(section) === item.id
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
                  aria-current={active ? "page" : undefined}
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
                  {backendReady ? "Listo" : "Sin conexión"}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {totalJobs.toLocaleString()} oportunidades
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
                {totalJobs.toLocaleString()} jobs
              </span>
            </div>
            <div className="flex items-center gap-2">
              <ActivityCenter operations={activityOperations} onRetry={(operation) => toast("Reintento disponible", { description: `Vuelve a iniciar ${operation.type} desde su pantalla.` })} />
              <Button
                variant="outline"
                size="sm"
                disabled={currentLoading}
                onClick={() => void refreshCurrentSection()}
              >
                {currentLoading ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <RefreshCw data-icon="inline-start" />}
                Actualizar
              </Button>
              <Button variant="outline" size="icon-sm" aria-label="Configuración" onClick={() => navigate("settings")}>
                <Settings className="size-4" />
              </Button>
            </div>
          </header>

          <main className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 flex-col overflow-y-auto px-4 pb-24 pt-3 sm:px-6 lg:px-6 lg:pb-6">
            <div className="shrink-0">
              <OpsStatusBanner status={opsStatus} onOpenOps={() => navigate("settings")} />
              <DataLoadingBanner />
            </div>
            {section === "jobs" && (
              <JobsScreen
                onOpenJob={setOpenJobId}
                onSearchNewJobs={() => void scanFreshJobs()}
                searchState={searchState}
                searchMessage={searchMessage}
                searchActive={jobSearchActive}
                searchStartedAt={searchOperation?.started_at ?? searchOperation?.created_at}
              />
            )}
            {section === "apply" && <PipelineScreen onOpenJob={setOpenJobId} />}
            {section === "applications" && <ApplicationsScreen onOpenJob={setOpenJobId} />}
            {section === "settings" && <SettingsScreen onNavigate={navigate} />}
            {section === "profile" && <ProfileScreen />}
            {section === "automations" && <OpsScreen />}
            {section === "insights" && <InsightsScreen />}
          </main>
        </div>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-md items-stretch justify-around">
          {NAV_ITEMS.map((item) => {
            const active = primarySectionFor(section) === item.id
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
