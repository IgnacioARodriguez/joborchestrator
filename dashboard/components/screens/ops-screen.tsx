"use client"

import { useEffect, useState } from "react"
import {
  BriefcaseBusiness,
  DatabaseZap,
  LinkIcon,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
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
  const [providers, setProviders] = useState<string[]>([])
  const [searchProviders, setSearchProviders] = useState<string[]>([])
  const [rankingJobs, setRankingJobs] = useState<RankingJobRecord[]>([])
  const [provider, setProvider] = useState("greenhouse")
  const [companyName, setCompanyName] = useState("")
  const [companyRef, setCompanyRef] = useState("")
  const [queries, setQueries] = useState(DEFAULT_QUERIES)
  const [location, setLocation] = useState("Spain")
  const [busy, setBusy] = useState<string | null>(null)
  const [results, setResults] = useState<ScanResult[]>([])

  async function loadOps() {
    try {
      const [sourceData, rankingData] = await Promise.all([
        api.getSources(),
        api.getRankingJobs(),
      ])
      setSources(sourceData.sources)
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

  async function runAction<T>(name: string, fn: () => Promise<T>) {
    setBusy(name)
    try {
      const value = await fn()
      await refresh()
      await loadOps()
      return value
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr]">
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
          <Button variant="outline" onClick={() => void refresh()}>
            <RefreshCw data-icon="inline-start" />
            Refresh jobs
          </Button>
          <Button variant="outline" onClick={() => void loadOps()}>
            <RefreshCw data-icon="inline-start" />
            Refresh ops
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <LinkIcon className="size-4 text-primary" />
            LinkedIn scraper import
          </CardTitle>
          <CardDescription className="text-xs">
            Imports the latest Excel produced by the existing local LinkedIn
            scraper.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            disabled={busy !== null}
            onClick={() =>
              void runAction("linkedin", async () => {
                const res = await api.importLatestLinkedIn()
                toast.success("LinkedIn imported", {
                  description: `${res.file}: ${res.import_stats.new ?? 0} new, ${
                    res.import_stats.updated ?? 0
                  } updated.`,
                })
              })
            }
          >
            <LinkIcon data-icon="inline-start" />
            Import latest LinkedIn Excel
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
              <Plus data-icon="inline-start" />
              Add source
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
              <Play data-icon="inline-start" />
              Scan enabled ATS
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
            <Search data-icon="inline-start" />
            Run search APIs
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
            Queues unranked jobs for the existing NVIDIA ranking worker.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy !== null}
              onClick={() =>
                void runAction("ranking", async () => {
                  const res = await api.createRankingJob({
                    limit: 250,
                    run_once: false,
                    request_batch_size: 25,
                    max_concurrency: 4,
                  })
                  toast.success("Ranking job queued", {
                    description: `${res.queued} jobs queued.`,
                  })
                })
              }
            >
              <Sparkles data-icon="inline-start" />
              Queue unranked jobs
            </Button>
          </div>
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
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null || !["queued", "running"].includes(job.status)}
                  onClick={() =>
                    void runAction(`ranking-${job.id}`, async () => {
                      await api.runRankingJobOnce(job.id)
                      toast.success(`Processed ranking job #${job.id}`)
                    })
                  }
                >
                  <Play data-icon="inline-start" />
                  Run once
                </Button>
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
