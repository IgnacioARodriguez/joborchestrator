import type {
  Decision,
  JobPosting,
  JobRanking,
  JobSource,
  RankingEvidence,
  RankingScores,
} from "./types"
import { DECISION_LABELS } from "./types"

// Parses a JSON payload from the job-search agent into normalized JobPosting
// records. Accepts a single object or an array. Missing fields are filled with
// safe defaults so partial agent output still renders.

const VALID_DECISIONS = Object.keys(DECISION_LABELS) as Decision[]
const VALID_SOURCES: JobSource[] = [
  "LinkedIn",
  "Greenhouse",
  "Lever",
  "Ashby",
  "API",
]

function toNumber(value: unknown, fallback: number): number {
  const n = typeof value === "string" ? Number(value) : value
  return typeof n === "number" && Number.isFinite(n) ? n : fallback
}

function toStringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((v): v is string => typeof v === "string")
}

function toDecision(value: unknown): Decision {
  return VALID_DECISIONS.includes(value as Decision)
    ? (value as Decision)
    : "MAYBE"
}

function toSource(value: unknown): JobSource {
  return VALID_SOURCES.includes(value as JobSource)
    ? (value as JobSource)
    : "API"
}

function normalizeScores(value: unknown): RankingScores {
  const s = (value ?? {}) as Record<string, unknown>
  return {
    role_fit: toNumber(s.role_fit, 0),
    requirement_coverage: toNumber(s.requirement_coverage, 0),
    seniority_match: toNumber(s.seniority_match, 0),
    location_fit: toNumber(s.location_fit, 0),
    compensation: toNumber(s.compensation, 0),
  }
}

function normalizeEvidence(value: unknown): RankingEvidence {
  const e = (value ?? {}) as Record<string, unknown>
  return {
    strong_matches: toStringArray(e.strong_matches),
    partial_matches: toStringArray(e.partial_matches),
    missing_requirements: toStringArray(e.missing_requirements),
    red_flags: toStringArray(e.red_flags),
    central_requirements: toStringArray(e.central_requirements),
  }
}

function normalizeRanking(value: unknown): JobRanking {
  const r = (value ?? {}) as Record<string, unknown>
  return {
    final_score: Math.max(0, Math.min(100, toNumber(r.final_score, 0))),
    decision: toDecision(r.decision),
    confidence: Math.max(0, Math.min(1, toNumber(r.confidence, 0.5))),
    scores: normalizeScores(r.scores),
    evidence: normalizeEvidence(r.evidence),
    reasoning_summary: toStringValue(r.reasoning_summary),
    recommended_application_angle: toStringValue(
      r.recommended_application_angle,
    ),
    ranking_version: toStringValue(r.ranking_version, "imported"),
  }
}

let importCounter = 0

function normalizeJob(raw: unknown): JobPosting {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Each entry must be a JSON object.")
  }
  const j = raw as Record<string, unknown>
  const now = new Date().toISOString()
  const materials = (j.materials ?? {}) as Record<string, unknown>
  const review = (j.review ?? {}) as Record<string, unknown>

  const id =
    toStringValue(j.id) ||
    `import-${Date.now()}-${importCounter++}`

  const requiresReview =
    typeof review.requires_llm_review === "boolean"
      ? review.requires_llm_review
      : false

  return {
    id,
    title: toStringValue(j.title, "Untitled role"),
    company: toStringValue(j.company, "Unknown company"),
    location: toStringValue(j.location, "Unspecified"),
    remote: Boolean(j.remote),
    source: toSource(j.source),
    url: toStringValue(j.url, "#"),
    apply_url: toStringValue(j.apply_url, toStringValue(j.url, "#")),
    description_text: toStringValue(j.description_text),
    first_seen_at: toStringValue(j.first_seen_at, now),
    last_seen_at: toStringValue(j.last_seen_at, now),
    status:
      j.status === "expired" || j.status === "filled"
        ? (j.status as "expired" | "filled")
        : "active",
    pipeline_status:
      j.pipeline_status === "shortlisted" ||
      j.pipeline_status === "applied" ||
      j.pipeline_status === "discarded" ||
      j.pipeline_status === "opened"
        ? j.pipeline_status
        : "new",
    ranking: normalizeRanking(j.ranking),
    review: {
      requires_llm_review: requiresReview,
      review_reason: toStringValue(review.review_reason),
      prompt: toStringValue(review.prompt),
      pasted_chatgpt_json:
        typeof review.pasted_chatgpt_json === "string"
          ? review.pasted_chatgpt_json
          : null,
      applied_at:
        typeof review.applied_at === "string" ? review.applied_at : null,
    },
    materials: {
      recruiter_message: toStringValue(materials.recruiter_message),
      cover_letter: toStringValue(materials.cover_letter),
      ats_cv_notes: toStringValue(materials.ats_cv_notes),
      autofill_notes: toStringValue(materials.autofill_notes),
    },
  }
}

export function parseImportPayload(raw: string): JobPosting[] {
  const trimmed = raw.trim()
  if (!trimmed) {
    throw new Error("Paste a JSON payload to import.")
  }

  let data: unknown
  try {
    data = JSON.parse(trimmed)
  } catch {
    throw new Error("Invalid JSON. Check for trailing commas or missing braces.")
  }

  const entries = Array.isArray(data) ? data : [data]
  if (entries.length === 0) {
    throw new Error("The payload contained no job entries.")
  }

  return entries.map(normalizeJob)
}
