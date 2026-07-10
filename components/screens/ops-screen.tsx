"use client"

import { useEffect, useRef, useState } from "react"
import {
  Ban,
  BriefcaseBusiness,
  DatabaseZap,
  LinkIcon,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Upload,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { PageHeader } from "@/components/page-chrome"
import { api } from "@/lib/api"
import { useStore } from "@/lib/store"
import type { CompanySource, OperationRun, RankingJobRecord, ScanResult } from "@/lib/types"

const DEFAULT_QUERIES = [
  "software engineer",
  "backend developer",
  "python developer",
  "solutions engineer",
].join("\n")

function operationCopy(name: string | null) {
  if (!name) return null
  if (name.startsWith("ranking-")) {
    return {
      title: "Ranking jobs with NVIDIA",
      detail: "The LLM is reading job descriptions and comparing them against your profile.",
    }
  }
  const copy: Record<string, { title: string; detail: string }> = {
    "refresh-jobs": {
      title: "Refreshing opportunities",
      detail: "Pulling the latest jobs and ranking data from the backend.",
    },
    "refresh-ops": {
      title: "Refreshing operations",
      detail: "Checking scanner sources, ranking jobs, and backend status.",
    },
    linkedin: {
      title: "Importing LinkedIn Excel",
      detail: "Uploading the spreadsheet, filtering rows, and saving new opportunities.",
    },
    "linkedin-profile": {
      title: "Switching LinkedIn profile",
      detail: "Saving the browser session profile used by the local scraper.",
    },
    source: {
      title: "Saving ATS source",
      detail: "Adding the company portal so it can be scanned later.",
    },
    ats: {
      title: "Scanning ATS portals",
      detail: "Contacting enabled company portals and saving new or updated jobs.",
    },
    all: {
      title: "Running unified scrape",
      detail: "Launching ATS portals and public job APIs in parallel.",
    },
    search: {
      title: "Searching public job APIs",
      detail: "Running keyword searches and storing matching opportunities.",
    },
    ranking: {
      title: "Queueing NVIDIA ranking",
      detail: "Preparing unranked jobs for LLM evaluation.",
    },
  }
  return copy[name] ?? {
    title: "Working on it",
    detail: "The backend is processing the request.",
  }
}

function LoadingIcon() {
  return <LoaderCircle className="size-4 animate-spin" data-icon="inline-start" />
}

function statusVariant(status: string) {
  if (status === "failed") return "destructive" as const
  if (status === "completed") return "default" as const
  return "secondary" as const
}

function ResultList({ results }: { results: ScanResult[] }) {
  if (results.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {results.map((result) => (
        <div
          key={`${result.source_type}-${result.company_ref}`}
          className="rounded-lg border border-border bg-muted/20 p-3 text-xs"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-foreground">
              {result.company_name}
            </span>
            <Badge variant={result.errors.length ? "destructive" : "secondary"}>
              {result.source_type}
            </Badge>
          </div>
          <p className="mt-1 text-muted-foreground">
            {result.found_count} found · {result.new_count} new ·{" "}
            {result.updated_count} updated · {result.duration_seconds}s
          </p>
          {result.errors.length > 0 && (
            <p className="mt-1 text-destructive">{result.errors.join("; ")}</p>
          )}
        </div>
      ))}
    </div>
  )
}

export function OpsScreen() {
  const { refresh, backendOnline, jobs } = useStore()
  const [sources, setSources] = useState<CompanySource[]>([])
  const [hasProfile, setHasProfile] = useState(false)
  const [providers, setProviders] = useState<string[]>([])
  const [searchProviders, setSearchProviders] = useState<string[]>([])
  const [rankingJobs, setRankingJobs] = useState<RankingJobRecord[]>([])
  const [operations, setOperations] = useState<OperationRun[]>([])
  const [provider, setProvider] = useState("greenhouse")
  const [companyName, setCompanyName] = useState("")
  const [companyRef, setCompanyRef] = useState("")
  const [queries, setQueries] = useState(DEFAULT_QUERIES)
  const [location, setLocation] = useState("Spain")
  const [busy, setBusy] = useState<string | null>(null)
  const [busyDetail, setBusyDetail] = useState("")
  const [busyStartedAt, setBusyStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [results, setResults] = useState<ScanResult[]>([])
  const [linkedinFile, setLinkedinFile] = useState<File | null>(null)
  const [linkedinProfiles, setLinkedinProfiles] = useState<string[]>([])
  const [linkedinProfile, setLinkedinProfile] = useState("main")
  const [linkedinProfileInput, setLinkedinProfileInput] = useState("main")
  const [linkedinProfileDir, setLinkedinProfileDir] = useState("")
  const [scanOperationId, setScanOperationId] = useState<number | null>(null)
  const liveRefreshAtRef = useRef(0)
  const busyCopy = operationCopy(busy)

  async function loadOps() {
    try {
      const [sourceData, rankingData, operationData] = await Promise.all([
        api.getSources(),
        api.getRankingJobs(),
        api.getOperations(8),
      ])
      const [profileData, linkedinProfileData] = await Promise.all([
        api.getProfile(),
        api.getLinkedInProfile(),
      ])
      setSources(sourceData.sources)
      setHasProfile(Boolean(profileData.profile))
      setProviders(sourceData.providers)
      setSearchProviders(sourceData.search_providers)
      setProvider(sourceData.providers[0] ?? "greenhouse")
      setRankingJobs(rankingData.jobs)
      setOperations(operationData.operations)
      setLinkedinProfiles(linkedinProfileData.linkedin_profile.profiles)
      setLinkedinProfile(linkedinProfileData.linkedin_profile.current)
      setLinkedinProfileInput(linkedinProfileData.linkedin_profile.current)
      setLinkedinProfileDir(linkedinProfileData.linkedin_profile.profile_dir)
    } catch (e) {
      toast.error("Backend unavailable", {
        description: e instanceof Error ? e.message : "Start the API server.",
      })
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadOps()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (!busyStartedAt) {
      return
    }
    const interval = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - busyStartedAt) / 1000)))
    }, 500)
    return () => window.clearInterval(interval)
  }, [busyStartedAt])

  useEffect(() => {
    if (!scanOperationId) return
    const interval = window.setInterval(async () => {
      try {
        const response = await api.getOperation(scanOperationId)
        const operation = response.operation
        setBusy("all")
        setBusyDetail(operation.progress_message || "Unified job scan is running.")
        if (["queued", "running"].includes(operation.status)) {
          const now = Date.now()
          if (now - liveRefreshAtRef.current >= 4000) {
            liveRefreshAtRef.current = now
            await refresh()
            await loadOps()
          }
        }
        if (operation.status === "completed") {
          const output = (operation.output_json || {}) as {
            ats?: ScanResult[]
            search?: ScanResult[]
            errors?: Record<string, string>
            summary?: { new?: number; updated?: number; errors?: number }
          }
          setResults([...(output.ats ?? []), ...(output.search ?? [])])
          setScanOperationId(null)
          setBusy(null)
          setBusyDetail("")
          setBusyStartedAt(null)
          setElapsedSeconds(0)
          await refresh()
          await loadOps()
          toast.success("Unified scrape finished", {
            description: `${output.summary?.new ?? 0} new, ${output.summary?.updated ?? 0} updated.`,
          })
        }
        if (operation.status === "failed") {
          setScanOperationId(null)
          setBusy(null)
          setBusyDetail("")
          setBusyStartedAt(null)
          setElapsedSeconds(0)
          await loadOps()
          toast.error("Unified scrape failed", {
            description: operation.error ?? "Check local worker logs.",
          })
        }
      } catch (e) {
        setScanOperationId(null)
        setBusy(null)
        setBusyDetail("")
        setBusyStartedAt(null)
        setElapsedSeconds(0)
        toast.error("Could not check scan operation", {
          description: e instanceof Error ? e.message : "Backend request failed.",
        })
      }
    }, 1500)
    return () => window.clearInterval(interval)
  }, [refresh, scanOperationId])

  async function runAction<T>(name: string, fn: () => Promise<T>) {
    setBusy(name)
    setBusyDetail(operationCopy(name)?.detail ?? "The backend is processing the request.")
    setBusyStartedAt(Date.now())
    setElapsedSeconds(0)
    try {
      const value = await fn()
      setBusyDetail("Finishing up and refreshing the dashboard data.")
      await refresh()
      await loadOps()
      return value
    } catch (e) {
      toast.error("Operation failed", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
      return undefined
    } finally {
      setBusy(null)
      setBusyDetail("")
      setBusyStartedAt(null)
      setElapsedSeconds(0)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow="Operations"
        title="Automation control room"
        description="Run scans, import LinkedIn exports, queue ranking jobs, and monitor local worker operations."
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr]">
      {busyCopy && (
        <Card className="border-primary/20 bg-primary/5 xl:col-span-2">
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <LoaderCircle className="size-5 animate-spin" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">
                {busyCopy.title}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {busyDetail || busyCopy.detail}
              </p>
            </div>
            <span className="hidden rounded-md border border-primary/20 bg-background px-2 py-1 text-xs tabular-nums text-muted-foreground sm:inline-flex">
              {elapsedSeconds}s
            </span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <DatabaseZap className="size-4 text-primary" />
            Backend
          </CardTitle>
          <CardDescription className="text-xs">
            {backendOnline
              ? `Connected to local API. Tracking ${jobs.length} opportunities.`
              : "Start the local API to use real scans and ranking."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={busy !== null}
            onClick={() => void runAction("refresh-jobs", refresh)}
          >
            {busy === "refresh-jobs" ? (
              <LoadingIcon />
            ) : (
              <RefreshCw data-icon="inline-start" />
            )}
            {busy === "refresh-jobs" ? "Refreshing jobs" : "Refresh jobs"}
          </Button>
          <Button
            variant="outline"
            disabled={busy !== null}
            onClick={() => void runAction("refresh-ops", loadOps)}
          >
            {busy === "refresh-ops" ? (
              <LoadingIcon />
            ) : (
              <RefreshCw data-icon="inline-start" />
            )}
            {busy === "refresh-ops" ? "Refreshing ops" : "Refresh ops"}
          </Button>
          <Button
            disabled={busy !== null || (sources.length === 0 && searchProviders.length === 0)}
            onClick={() =>
              void (async () => {
                setBusy("all")
                setBusyDetail("Queueing unified job scan.")
                setBusyStartedAt(Date.now())
                setElapsedSeconds(0)
                try {
                  const res = await api.scanAll({
                    include_ats: sources.length > 0,
                    include_search: searchProviders.length > 0,
                    include_linkedin: false,
                    search_providers: searchProviders,
                    queries: queries.split("\n"),
                    location,
                    remote: true,
                    max_pages: 1,
                  })
                  setScanOperationId(res.operation_id)
                  liveRefreshAtRef.current = 0
                  setBusyDetail("Queued. Waiting for the local worker.")
                  toast.success("Unified scrape queued", {
                    description: `Operation #${res.operation_id}`,
                  })
                  await loadOps()
                } catch (e) {
                  setBusy(null)
                  setBusyDetail("")
                  setBusyStartedAt(null)
                  setElapsedSeconds(0)
                  toast.error("Could not queue unified scrape", {
                    description: e instanceof Error ? e.message : "Backend request failed.",
                  })
                }
              })()
            }
          >
            {busy === "all" ? (
              <LoadingIcon />
            ) : (
              <Play data-icon="inline-start" />
            )}
            {busy === "all" ? "Scraping all" : "Scrap all"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <LinkIcon className="size-4 text-primary" />
            LinkedIn Excel import
          </CardTitle>
          <CardDescription className="text-xs">
            Uploads an Excel file exported by the local LinkedIn scraper into
            the cloud database.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[180px_1fr_auto]">
            <Select
              value={linkedinProfile}
              onValueChange={(value) => {
                if (!value) return
                setLinkedinProfile(value)
                setLinkedinProfileInput(value)
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Profile" />
              </SelectTrigger>
              <SelectContent>
                {linkedinProfiles.map((profile) => (
                  <SelectItem key={profile} value={profile}>
                    {profile}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={linkedinProfileInput}
              onChange={(event) => setLinkedinProfileInput(event.target.value)}
              placeholder="main or test"
            />
            <Button
              variant="outline"
              disabled={busy !== null || !linkedinProfileInput.trim()}
              onClick={() =>
                void runAction("linkedin-profile", async () => {
                  const res = await api.setLinkedInProfile(linkedinProfileInput)
                  setLinkedinProfiles(res.linkedin_profile.profiles)
                  setLinkedinProfile(res.linkedin_profile.current)
                  setLinkedinProfileInput(res.linkedin_profile.current)
                  setLinkedinProfileDir(res.linkedin_profile.profile_dir)
                  toast.success("LinkedIn profile selected", {
                    description: res.linkedin_profile.current,
                  })
                })
              }
            >
              {busy === "linkedin-profile" ? <LoadingIcon /> : <LinkIcon data-icon="inline-start" />}
              Save profile
            </Button>
          </div>
          <p className="break-all text-xs text-muted-foreground">
            Active scraper session: {linkedinProfileDir || "linkedin_user_profile"}
          </p>
          <Input
            type="file"
            accept=".xlsx,.xls"
            onChange={(event) => setLinkedinFile(event.target.files?.[0] ?? null)}
          />
          <Button
            disabled={busy !== null || !linkedinFile}
            onClick={() =>
              void runAction("linkedin", async () => {
                if (!linkedinFile) return
                const res = await api.importLinkedInExcel(linkedinFile)
                setLinkedinFile(null)
                toast.success("LinkedIn imported", {
                  description: `${res.file}: ${res.import_stats.new ?? 0} new, ${
                    res.import_stats.updated ?? 0
                  } updated.`,
                })
              })
            }
          >
            {busy === "linkedin" ? (
              <LoadingIcon />
            ) : (
              <Upload data-icon="inline-start" />
            )}
            {busy === "linkedin" ? "Importing Excel" : "Upload and import Excel"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <BriefcaseBusiness className="size-4 text-primary" />
            ATS portal scanner
          </CardTitle>
          <CardDescription className="text-xs">
            Add Greenhouse, Lever, Ashby, and other configured ATS sources, then
            scan enabled companies.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Select value={provider} onValueChange={(value) => value && setProvider(value)}>
              <SelectTrigger>
                <SelectValue placeholder="Provider" />
              </SelectTrigger>
              <SelectContent>
                {providers.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="Company"
            />
            <Input
              value={companyRef}
              onChange={(e) => setCompanyRef(e.target.value)}
              placeholder="ATS slug/ref"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={!companyName || !companyRef || busy !== null}
              onClick={() =>
                void runAction("source", async () => {
                  await api.addSource({
                    provider,
                    company_name: companyName,
                    company_ref: companyRef,
                    enabled: true,
                  })
                  setCompanyName("")
                  setCompanyRef("")
                  toast.success("Source saved")
                })
            }
          >
              {busy === "source" ? (
                <LoadingIcon />
              ) : (
                <Plus data-icon="inline-start" />
              )}
              {busy === "source" ? "Saving source" : "Add source"}
            </Button>
            <Button
              disabled={busy !== null || sources.length === 0}
              onClick={() =>
                void runAction("ats", async () => {
                  const res = await api.scanAts()
                  setResults(res.results)
                  toast.success("ATS scan finished")
                })
              }
            >
              {busy === "ats" ? (
                <LoadingIcon />
              ) : (
                <Play data-icon="inline-start" />
              )}
              {busy === "ats" ? "Scanning ATS" : "Scan enabled ATS"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sources.slice(0, 12).map((source) => (
              <Badge key={source.id} variant="secondary">
                {source.provider}: {source.company_name}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Search className="size-4 text-primary" />
            Search APIs
          </CardTitle>
          <CardDescription className="text-xs">
            Searches public job APIs by keyword/location and saves results into
            the same ranking store.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Textarea
            value={queries}
            onChange={(e) => setQueries(e.target.value)}
            className="min-h-28 text-xs"
          />
          <Input value={location} onChange={(e) => setLocation(e.target.value)} />
          <Button
            disabled={busy !== null || searchProviders.length === 0}
            onClick={() =>
              void runAction("search", async () => {
                const res = await api.scanSearch({
                  providers: searchProviders,
                  queries: queries.split("\n"),
                  location,
                  remote: true,
                  max_pages: 1,
                })
                setResults(res.results)
                toast.success("Search scan finished")
              })
            }
          >
            {busy === "search" ? (
              <LoadingIcon />
            ) : (
              <Search data-icon="inline-start" />
            )}
            {busy === "search" ? "Searching APIs" : "Run search APIs"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Sparkles className="size-4 text-primary" />
            NVIDIA LLM ranking
          </CardTitle>
          <CardDescription className="text-xs">
            {hasProfile
              ? "Queues unranked jobs. Your local NVIDIA ranking worker processes them."
              : "Upload and save a profile before running NVIDIA ranking."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy !== null || !hasProfile}
              onClick={() =>
                void runAction("ranking", async () => {
                  const res = await api.createRankingJob({
                    limit: 250,
                    run_once: false,
                    request_batch_size: 2,
                    max_concurrency: 1,
                  })
                  toast.success("Ranking job queued", {
                    description: `${res.queued} jobs queued.`,
                  })
                })
              }
            >
              {busy === "ranking" ? (
                <LoadingIcon />
              ) : (
                <Sparkles data-icon="inline-start" />
              )}
            {busy === "ranking" ? "Queueing jobs" : "Queue unranked jobs"}
            </Button>
            {!hasProfile && (
              <p className="flex items-center text-xs text-muted-foreground">
                Profile required for NVIDIA ranking.
              </p>
            )}
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Keep <span className="font-mono">run_ranking_worker.bat</span> running on your PC to process queued jobs and write logs locally.
          </p>
          <div className="flex flex-col gap-2">
            {rankingJobs.slice(0, 5).map((job) => (
              <div
                key={job.id}
                className="flex flex-col gap-2 rounded-lg border border-border p-2 text-xs"
              >
                <div>
                  <p className="font-medium text-foreground">
                    #{job.id} · {job.status}
                  </p>
                  <p className="text-muted-foreground">
                    {job.processed_items}/{job.total_items} processed ·{" "}
                    {job.saved_items} saved · {job.failed_items} failed
                  </p>
                </div>
                <Badge variant={job.status === "failed" ? "destructive" : "secondary"}>
                  local worker
                </Badge>
                <p className="text-muted-foreground">
                  {job.queued_items ?? 0} queued - {job.running_items ?? 0} running -{" "}
                  {job.completed_items ?? 0} done - {job.failed_item_count ?? 0} failed
                </p>
                {(job.latest_item_error || job.error) && (
                  <p className="line-clamp-2 text-muted-foreground">
                    {job.latest_item_error || job.error}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy !== null || !["queued", "running"].includes(job.status)}
                    onClick={() =>
                      void runAction("refresh-ops", async () => {
                        await api.requeueStaleRankingItems(job.id)
                        toast.success(`Requeued stale items for #${job.id}`)
                      })
                    }
                  >
                    <RotateCcw data-icon="inline-start" />
                    Requeue stale
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy !== null || (job.failed_item_count ?? job.failed_items) === 0}
                    onClick={() =>
                      void runAction("refresh-ops", async () => {
                        const res = await api.requeueFailedRankingItems(job.id)
                        toast.success(`Requeued ${res.requeued} failed items`)
                      })
                    }
                  >
                    <RefreshCw data-icon="inline-start" />
                    Retry failed
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy !== null || !["queued", "running"].includes(job.status)}
                    onClick={() =>
                      void runAction("refresh-ops", async () => {
                        await api.cancelRankingJob(job.id)
                        toast.success(`Cancelled ranking job #${job.id}`)
                      })
                    }
                  >
                    <Ban data-icon="inline-start" />
                    Cancel
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Recent operations</CardTitle>
          <CardDescription className="text-xs">
            Async work handled by local workers.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {operations.map((operation) => (
            <div
              key={operation.id}
              className="flex flex-col gap-1 rounded-lg border border-border p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-foreground">
                  #{operation.id} Â· {operation.type}
                </p>
                <Badge variant={statusVariant(operation.status)}>
                  {operation.status}
                </Badge>
              </div>
              <p className="text-muted-foreground">
                {operation.progress_message || "Waiting for worker."}
              </p>
              {operation.error && (
                <p className="line-clamp-2 text-destructive">{operation.error}</p>
              )}
              <p className="text-muted-foreground">
                attempts {operation.attempts} - updated {operation.updated_at}
              </p>
            </div>
          ))}
          {operations.length === 0 && (
            <p className="text-xs text-muted-foreground">No async operations yet.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Last operation results</CardTitle>
        </CardHeader>
        <CardContent>
          <ResultList results={results} />
        </CardContent>
      </Card>
      </div>
    </div>
  )
}
