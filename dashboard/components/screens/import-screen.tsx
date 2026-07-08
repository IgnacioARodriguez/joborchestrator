"use client"

import { useState } from "react"
import { Upload, FileJson, RotateCcw, ClipboardPaste } from "lucide-react"
import { toast } from "sonner"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useStore } from "@/lib/store"
import { parseImportPayload } from "@/lib/import"
import { SAMPLE_IMPORT_JSON } from "@/lib/sample-data"
import type { Section } from "@/lib/nav"

export function ImportScreen({
  onNavigate,
}: {
  onNavigate: (section: Section) => void
}) {
  const { importJobs, resetToSample, jobs } = useStore()
  const [raw, setRaw] = useState("")
  const [error, setError] = useState<string | null>(null)

  function handleImport(mode: "merge" | "replace") {
    setError(null)
    try {
      const parsed = parseImportPayload(raw)
      importJobs(parsed, mode)
      toast.success(
        mode === "replace" ? "Dataset replaced" : "Jobs imported",
        {
          description: `${parsed.length} ${
            parsed.length === 1 ? "posting" : "postings"
          } processed.`,
        },
      )
      setRaw("")
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not parse the JSON payload.",
      )
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileJson className="size-4 text-primary" />
            Import agent output
          </CardTitle>
          <CardDescription className="text-xs leading-relaxed">
            Paste the JSON array produced by your job-search agent. Each entry
            should include the posting, its ranking, evidence, and review flags.
            Currently tracking {jobs.length}{" "}
            {jobs.length === 1 ? "job" : "jobs"}.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Textarea
            value={raw}
            onChange={(e) => {
              setRaw(e.target.value)
              if (error) setError(null)
            }}
            placeholder='[ { "id": "job-123", "title": "Senior Engineer", "ranking": { "final_score": 82, "decision": "APPLY_NOW" }, ... } ]'
            className="min-h-56 font-mono text-xs"
            aria-invalid={error ? true : undefined}
            aria-label="Import JSON"
          />
          {error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button onClick={() => handleImport("merge")} disabled={!raw.trim()}>
              <Upload data-icon="inline-start" />
              Import &amp; merge
            </Button>
            <Button
              variant="outline"
              onClick={() => handleImport("replace")}
              disabled={!raw.trim()}
            >
              Replace dataset
            </Button>
            <Button
              variant="ghost"
              onClick={() => setRaw(SAMPLE_IMPORT_JSON)}
            >
              <ClipboardPaste data-icon="inline-start" />
              Load sample JSON
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Reset workspace</CardTitle>
          <CardDescription className="text-xs">
            Restore the built-in demo dataset. This clears any imported jobs and
            pipeline changes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => {
              resetToSample()
              toast.success("Workspace reset to sample data")
            }}
          >
            <RotateCcw data-icon="inline-start" />
            Reset to sample data
          </Button>
          <Button
            variant="ghost"
            onClick={() => onNavigate("ranking")}
            className="ml-2"
          >
            Go to Ranking
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
