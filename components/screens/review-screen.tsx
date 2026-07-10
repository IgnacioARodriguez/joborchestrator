"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Check, ExternalLink, Search, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DecisionBadge, ScoreBadge } from "@/components/badges"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import type { JobPosting } from "@/lib/types"
import { relativeTime } from "@/lib/job-ui"
import { cn } from "@/lib/utils"

function summarize(items: string[], fallback: string) {
  return items.slice(0, 2).join(", ") || fallback
}

export function ReviewScreen({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { jobs, setPipelineStatus } = useStore()
  const [query, setQuery] = useState("")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [bulk, setBulk] = useState<Set<string>>(new Set())

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return jobs
      .filter((job) => job.pipeline_status !== "discarded")
      .filter((job) => !q || `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(q))
      .sort((a, b) => b.ranking.final_score - a.ranking.final_score)
  }, [jobs, query])

  const activeId = selectedId ?? visible[0]?.id ?? null

  const selectedIndex = useCallback(
    () => Math.max(0, visible.findIndex((job) => job.id === activeId)),
    [activeId, visible],
  )

  const act = useCallback((job: JobPosting, status: "shortlisted" | "ready_to_apply" | "discarded") => {
    setPipelineStatus(job.id, status)
    toast.success(status === "discarded" ? "Discarded" : "Saved", { description: job.title })
  }, [setPipelineStatus])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return
      const index = selectedIndex()
      const current = visible[index]
      if (event.key.toLowerCase() === "j") {
        event.preventDefault()
        setSelectedId(visible[Math.min(index + 1, visible.length - 1)]?.id ?? null)
      }
      if (event.key.toLowerCase() === "k") {
        event.preventDefault()
        setSelectedId(visible[Math.max(index - 1, 0)]?.id ?? null)
      }
      if (event.key === "Enter" && current) onOpenJob(current.id)
      if (event.key.toLowerCase() === "a" && current) act(current, "ready_to_apply")
      if (event.key.toLowerCase() === "s" && current) act(current, "shortlisted")
      if (event.key.toLowerCase() === "x" && current) act(current, "discarded")
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [act, onOpenJob, selectedIndex, visible])

  function discardBulk() {
    for (const id of bulk) setPipelineStatus(id, "discarded")
    toast("Bulk discarded", { description: `${bulk.size} jobs moved out of review.` })
    setBulk(new Set())
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Review"
        title="Opportunity review"
        description="Dense ranked queue for deciding what to apply to next."
        actions={bulk.size > 0 ? <Button variant="outline" onClick={discardBulk}><Trash2 data-icon="inline-start" />Discard {bulk.size}</Button> : null}
      />
      <div className="rounded-lg border border-border bg-card p-2">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, company, location" className="pl-9" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full min-w-[1060px] border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-muted text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="w-10 px-3 py-2 text-left"></th>
              <th className="px-3 py-2 text-left">Recommended</th>
              <th className="px-3 py-2 text-left">Score</th>
              <th className="px-3 py-2 text-left">Role</th>
              <th className="px-3 py-2 text-left">Company</th>
              <th className="px-3 py-2 text-left">Fit</th>
              <th className="px-3 py-2 text-left">Gap</th>
              <th className="px-3 py-2 text-left">Age</th>
              <th className="px-3 py-2 text-left">Next step</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((job) => (
              <tr
                key={job.id}
                className={cn("border-b border-border bg-background hover:bg-muted/40", activeId === job.id && "bg-primary/5")}
                onClick={() => setSelectedId(job.id)}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={bulk.has(job.id)}
                    onChange={(event) => {
                      setBulk((prev) => {
                        const next = new Set(prev)
                        if (event.target.checked) next.add(job.id)
                        else next.delete(job.id)
                        return next
                      })
                    }}
                    aria-label={`Select ${job.title}`}
                  />
                </td>
                <td className="px-3 py-2"><DecisionBadge decision={job.ranking.decision} score={job.ranking.final_score} /></td>
                <td className="px-3 py-2"><ScoreBadge score={job.ranking.final_score} /></td>
                <td className="max-w-[230px] px-3 py-2 font-medium text-foreground"><button className="line-clamp-2 text-left hover:underline" onClick={() => onOpenJob(job.id)}>{job.title}</button></td>
                <td className="max-w-[160px] px-3 py-2 text-muted-foreground">{job.company}</td>
                <td className="max-w-[220px] px-3 py-2 text-xs text-muted-foreground">{summarize(job.ranking.evidence.strong_matches, "No strong match recorded")}</td>
                <td className="max-w-[220px] px-3 py-2 text-xs text-muted-foreground">{summarize(job.ranking.evidence.missing_requirements, "No major gap recorded")}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{relativeTime(job.first_seen_at)}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <Button size="icon-sm" variant="ghost" aria-label="Ready to apply" onClick={() => act(job, "ready_to_apply")}><Check className="size-4" /></Button>
                    <Button size="icon-sm" variant="ghost" aria-label="Open detail" onClick={() => onOpenJob(job.id)}><ExternalLink className="size-4" /></Button>
                    <Button size="icon-sm" variant="ghost" aria-label="Discard" onClick={() => act(job, "discarded")}><Trash2 className="size-4" /></Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
