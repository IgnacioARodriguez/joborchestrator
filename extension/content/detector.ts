import { isGreenhouseApplicationPage } from "../adapters/greenhouse"
import { extractFields } from "./extractor"
import { applyAutofillPlan } from "./filler"
import { observeSubmissionConfirmation } from "./submission-observer"
import type { AutofillPlan, ExtractedField, ResolvedAnswer } from "../shared/types"

const API_BASE = "http://127.0.0.1:8000"

async function bootstrap(): Promise<void> {
  if (!isGreenhouseApplicationPage()) return
  const fields = extractFields()
  const plan = await resolvePlan(fields)
  applyAutofillPlan(plan)
  observeSubmissionConfirmation(() => {
    void notifySubmitted(plan)
  })
}

async function resolvePlan(fields: ExtractedField[]): Promise<AutofillPlan> {
  const [answers, jobId] = await Promise.all([fetchAnswers(), resolveJobId()])
  return {
    job_id: jobId,
    fields,
    answers: fields.map((field) => resolveField(field, answers)),
  }
}

async function resolveJobId(): Promise<number | undefined> {
  try {
    const currentUrl = window.location.href
    const jobsResponse = await fetch(`${API_BASE}/api/jobs?limit=500`)
    if (jobsResponse.ok) {
      const payload = await jobsResponse.json()
      const match = (payload.jobs || []).find((job: { id: string; url?: string; apply_url?: string; external_apply_url?: string }) =>
        [job.url, job.apply_url, job.external_apply_url].some((url) => url && currentUrl.startsWith(url)),
      )
      if (match?.id) return Number(match.id)
    }
    const created = await fetch(`${API_BASE}/api/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: document.querySelector("h1")?.textContent?.trim() || "Greenhouse application",
        company: document.querySelector("[class*='company'], .app-title")?.textContent?.trim() || "Unknown company",
        url: currentUrl,
        apply_url: currentUrl,
        source: "greenhouse",
      }),
    })
    if (!created.ok) return undefined
    const payload = await created.json()
    return payload.job?.id ? Number(payload.job.id) : undefined
  } catch {
    return undefined
  }
}

async function fetchAnswers(): Promise<Array<{ canonical_key: string; question_patterns: string[]; value?: string; requires_confirmation: boolean }>> {
  try {
    const response = await fetch(`${API_BASE}/api/answers`)
    if (!response.ok) return []
    const payload = await response.json()
    return payload.answers || []
  } catch {
    return []
  }
}

function resolveField(
  field: ExtractedField,
  answers: Array<{ canonical_key: string; question_patterns: string[]; value?: string; requires_confirmation: boolean }>,
): ResolvedAnswer {
  const label = field.label.toLowerCase()
  const match = answers.find((answer) =>
    answer.question_patterns.some((pattern) => pattern && label.includes(pattern.toLowerCase())),
  )
  if (!match?.value) {
    return { field_id: field.field_id, confidence: "missing", needs_review: true }
  }
  return {
    field_id: field.field_id,
    value: match.value,
    confidence: match.requires_confirmation ? "medium" : "high",
    needs_review: match.requires_confirmation,
  }
}

async function notifySubmitted(plan: AutofillPlan): Promise<void> {
  if (!plan.job_id) return
  try {
    const created = await fetch(`${API_BASE}/api/jobs/${plan.job_id}/applications`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ats_type: "greenhouse",
        status: "submitted",
        channel: "portal",
        resume_variant_id: plan.resume_variant_id,
        submitted_at: new Date().toISOString(),
      }),
    })
    if (!created.ok) return
    const payload = await created.json()
    const applicationId = payload.application?.id
    if (!applicationId) return
    await fetch(`${API_BASE}/api/applications/${applicationId}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_type: "submitted", note: "Detected Greenhouse confirmation page." }),
    })
  } catch {
    // Confirmation reporting is best-effort and never blocks the page.
  }
}

void bootstrap()
