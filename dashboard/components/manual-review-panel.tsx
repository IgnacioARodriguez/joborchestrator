"use client"

import { useState } from "react"
import { Check, Copy, Sparkles, AlertTriangle } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useStore } from "@/lib/store"
import type { Decision, JobPosting, JobRanking } from "@/lib/types"
import { DECISION_ORDER } from "@/lib/types"

// Parses a pasted ChatGPT JSON response into a ranking patch.
function parseReviewJson(raw: string): Partial<JobRanking> {
  const parsed = JSON.parse(raw)
  const patch: Partial<JobRanking> = {}

  if (typeof parsed.final_score === "number") {
    patch.final_score = Math.max(0, Math.min(100, Math.round(parsed.final_score)))
  }
  if (
    typeof parsed.decision === "string" &&
    DECISION_ORDER.includes(parsed.decision as Decision)
  ) {
    patch.decision = parsed.decision as Decision
  }
  if (typeof parsed.confidence === "number") {
    patch.confidence = Math.max(0, Math.min(1, parsed.confidence))
  }
  if (typeof parsed.reasoning_summary === "string") {
    patch.reasoning_summary = parsed.reasoning_summary
  }
  if (typeof parsed.recommended_application_angle === "string") {
    patch.recommended_application_angle = parsed.recommended_application_angle
  }
  if (parsed.evidence && typeof parsed.evidence === "object") {
    patch.evidence = {
      strong_matches: parsed.evidence.strong_matches ?? [],
      partial_matches: parsed.evidence.partial_matches ?? [],
      missing_requirements: parsed.evidence.missing_requirements ?? [],
      red_flags: parsed.evidence.red_flags ?? [],
      central_requirements: parsed.evidence.central_requirements ?? [],
    }
  }

  if (patch.final_score === undefined && patch.decision === undefined) {
    throw new Error("Missing final_score or decision")
  }
  return patch
}

export function ManualReviewPanel({
  job,
  onApplied,
}: {
  job: JobPosting
  onApplied?: () => void
}) {
  const { applyReview } = useStore()
  const [pasted, setPasted] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(job.review.prompt)
      toast.success("Prompt copied", {
        description: "Paste it into ChatGPT, then bring the JSON back here.",
      })
    } catch {
      toast.error("Could not copy to clipboard")
    }
  }

  function handleApply() {
    setError(null)
    try {
      const patch = parseReviewJson(pasted)
      applyReview(job.id, patch)
      setApplied(true)
      toast.success("Review applied", {
        description: "Ranking updated and removed from the queue.",
      })
      onApplied?.()
    } catch (e) {
      setError(
        e instanceof Error
          ? `Invalid JSON: ${e.message}`
          : "Could not parse the pasted response.",
      )
    }
  }

  if (applied) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-success/30 bg-success/10 p-6 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-success/20 text-success">
          <Check className="size-5" />
        </div>
        <p className="text-sm font-medium text-foreground">Review applied</p>
        <p className="text-xs text-muted-foreground">
          The ranking was updated with your ChatGPT verdict.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2 rounded-lg border border-review/30 bg-review/10 p-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-review-foreground" />
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-medium text-review-foreground">
            Review reason
          </p>
          <p className="text-xs leading-relaxed text-foreground">
            {job.review.review_reason}
          </p>
        </div>
      </div>

      <Button variant="outline" size="sm" onClick={copyPrompt}>
        <Copy data-icon="inline-start" />
        Copy ChatGPT prompt
      </Button>

      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={`review-${job.id}`}
          className="text-xs font-medium text-foreground"
        >
          Paste ChatGPT JSON response
        </label>
        <Textarea
          id={`review-${job.id}`}
          value={pasted}
          onChange={(e) => {
            setPasted(e.target.value)
            if (error) setError(null)
          }}
          placeholder='{ "final_score": 82, "decision": "APPLY_NOW", ... }'
          className="min-h-28 font-mono text-xs"
          aria-invalid={error ? true : undefined}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      <Button onClick={handleApply} disabled={!pasted.trim()}>
        <Sparkles data-icon="inline-start" />
        Apply review
      </Button>
    </div>
  )
}
