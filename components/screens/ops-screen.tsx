"use client"

import { useEffect, useState } from "react"
import {
  BriefcaseBusiness,
  DatabaseZap,
  LinkIcon,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
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
import { api } from "@/lib/api"
import { useStore } from "@/lib/store"
import type { CompanySource, RankingJobRecord, ScanResult } from "@/lib/types"

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
    source: {
      title: "Saving ATS source",
      detail: "Adding the company portal so it can be scanned later.",
    },
    ats: {
      title: "Scanning ATS portals",
      detail: "Contacting enabled company portals and saving new or updated jobs.",
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
  const busyCopy = operationCopy(busy)

  async function loadOps() {
    try {
      const [sourceData, rankingData] = await Promise.all([
        api.getSources(),
        api.getRankingJobs(),
      ])
      const profileData = await api.getProfile()
      setSources(sourceData.sources)
      setHasProfile(Boolean(profileData.profile))
      setProviders(sourceData.providers)
      setSearchProviders(sourceData.search_providers)
      setProvider(sourceData.providers[0] ?? "greenhouse")
      setRankingJobs(rankingData.jobs)
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
                className="flex items-center justify-between gap-2 rounded-lg border border-border p-2 text-xs"
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
              </div>
            ))}
          </div>
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
  )
}
