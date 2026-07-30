import type { ApplicationRecord, ApplicationSession, JobListItem } from "./types"

export type PreparationStatus =
  | "pending"
  | "generating"
  | "needs_review"
  | "ready_to_apply"
  | "application_started"
  | "blocked"

export type PreparationFilter = "all" | "review" | "ready" | "blocked"

export type PreparationAction =
  | "generate_materials"
  | "review_materials"
  | "continue_review"
  | "open_portal"
  | "continue_session"
  | "confirm_submitted"
  | "resolve_problem"

export interface PreparationStep {
  id: "materials" | "review" | "application" | "confirmation"
  label: string
  state: "todo" | "active" | "done" | "blocked"
}

export interface PreparationViewState {
  status: PreparationStatus
  label: string
  description: string
  primaryAction: {
    type: PreparationAction
    label: string
  }
  secondaryActions: Array<{
    type: PreparationAction
    label: string
  }>
  progress: PreparationStep[]
  blocker?: string | null
  materials: Array<{
    id: "ats_cv" | "cover_letter" | "autofill" | "recruiter_message"
    label: string
    ready: boolean
    needsReview: boolean
  }>
}

const SENT_APPLICATION_STATUSES = new Set([
  "submitted",
  "submitted_manually",
  "submission_verified",
])

const BLOCKED_SESSION_STATES = new Set([
  "failed",
  "cancelled",
  "stalled",
  "blocked",
])

const ACTIVE_SESSION_STATES = new Set([
  "created",
  "preparing",
  "preflight",
  "preparing_materials",
  "materials_ready",
  "opened",
  "ready_to_fill",
  "filling",
  "prefilled",
])

const REVIEW_SESSION_STATES = new Set([
  "needs_user_input",
  "ready_for_review",
])

const READY_SESSION_STATES = new Set(["submit_only"])

export function isConfirmedApplication(application: Pick<ApplicationRecord, "status">): boolean {
  return SENT_APPLICATION_STATUSES.has(application.status)
}

export function getPreparationViewState(
  job: JobListItem,
  session?: ApplicationSession | null,
): PreparationViewState {
  const materials = materialSummaries(job)
  const hasMaterials = materials.some((material) => material.ready)
  const allRequiredMaterialsReady = materials
    .filter((material) => material.id !== "cover_letter")
    .every((material) => material.ready)
  const materialReview = job.materials_review
  const materialWarnings = materialReview?.reasons ?? []
  const sessionState = session?.state ?? null
  const blocker =
    humanBlocker(job, session) ||
    (materialReview?.status === "missing" ? "Faltan materiales para preparar la candidatura." : null)

  if (sessionState && BLOCKED_SESSION_STATES.has(sessionState)) {
    return buildState({
      status: "blocked",
      label: "Bloqueado",
      description: "Hay un problema que debe resolverse antes de continuar.",
      primaryAction: { type: "resolve_problem", label: "Resolver problema" },
      secondaryActions: hasMaterials ? [{ type: "review_materials", label: "Revisar materiales" }] : [],
      activeStep: "application",
      blockedStep: "application",
      blocker: humanBlocker(job, session) || "La sesion de aplicacion se detuvo.",
      materials,
      completed: { materials: hasMaterials, review: materialReview?.status === "ready" },
    })
  }

  if (sessionState && READY_SESSION_STATES.has(sessionState)) {
    return buildState({
      status: "application_started",
      label: "Aplicacion iniciada",
      description: "La candidatura esta lista para que revises el portal y confirmes el envio.",
      primaryAction: { type: "confirm_submitted", label: "Confirmar que aplique" },
      secondaryActions: [{ type: "continue_session", label: "Continuar sesion" }],
      activeStep: "confirmation",
      materials,
      completed: { materials: true, review: true, application: true },
    })
  }

  if (sessionState && REVIEW_SESSION_STATES.has(sessionState)) {
    return buildState({
      status: sessionState === "needs_user_input" ? "blocked" : "needs_review",
      label: sessionState === "needs_user_input" ? "Con problema" : "Requiere revision",
      description:
        sessionState === "needs_user_input"
          ? "El portal necesita datos o una accion manual antes de continuar."
          : "Revisa los datos antes de seguir en el portal.",
      primaryAction: {
        type: sessionState === "needs_user_input" ? "resolve_problem" : "continue_review",
        label: sessionState === "needs_user_input" ? "Resolver problema" : "Continuar revision",
      },
      secondaryActions: [{ type: "confirm_submitted", label: "Confirmar que aplique" }],
      activeStep: sessionState === "needs_user_input" ? "application" : "review",
      blockedStep: sessionState === "needs_user_input" ? "application" : undefined,
      blocker: humanBlocker(job, session),
      materials,
      completed: { materials: hasMaterials, review: sessionState !== "needs_user_input" },
    })
  }

  if (sessionState && ACTIVE_SESSION_STATES.has(sessionState)) {
    return buildState({
      status: "application_started",
      label: "Aplicacion iniciada",
      description: "Hay una sesion de preparacion en curso.",
      primaryAction: { type: "continue_session", label: "Continuar sesion" },
      secondaryActions: hasMaterials ? [{ type: "review_materials", label: "Revisar materiales" }] : [],
      activeStep: "application",
      materials,
      completed: { materials: hasMaterials, review: materialReview?.status === "ready" },
    })
  }

  if (materialWarnings.length > 0 && hasMaterials) {
    return buildState({
      status: "needs_review",
      label: "Requiere revision",
      description: "Los materiales estan generados, pero necesitan una mirada antes de aplicar.",
      primaryAction: { type: "review_materials", label: "Revisar materiales" },
      secondaryActions: allRequiredMaterialsReady ? [{ type: "open_portal", label: "Abrir portal" }] : [],
      activeStep: "review",
      blocker: materialWarnings.map(materialReasonLabel).join(" "),
      materials,
      completed: { materials: true },
    })
  }

  if (allRequiredMaterialsReady && materialReview?.status === "ready") {
    return buildState({
      status: "ready_to_apply",
      label: "Listo para aplicar",
      description: "Los materiales principales estan listos para usar en el portal.",
      primaryAction: { type: "open_portal", label: "Abrir portal de aplicacion" },
      secondaryActions: [{ type: "review_materials", label: "Revisar materiales" }],
      activeStep: "application",
      materials,
      completed: { materials: true, review: true },
    })
  }

  return buildState({
    status: "pending",
    label: "Pendiente",
    description: "Prepara los materiales antes de revisar y aplicar.",
    primaryAction: { type: "generate_materials", label: "Generar materiales" },
    secondaryActions: [],
    activeStep: "materials",
    blocker,
    materials,
    completed: {},
  })
}

export function matchesPreparationFilter(view: PreparationViewState, filter: PreparationFilter): boolean {
  if (filter === "all") return true
  if (filter === "review") return view.status === "needs_review"
  if (filter === "ready") return view.status === "ready_to_apply" || view.status === "application_started"
  return view.status === "blocked"
}

export function materialReasonLabel(reason: string): string {
  if (reason === "materials_missing") return "Faltan materiales."
  if (reason === "ranking_requires_review") return "La recomendacion necesita revision."
  if (reason === "ranking_low_confidence") return "La confianza del ranking es baja."
  if (reason === "ranking_not_actionable") return "La recomendacion no esta lista para aplicar."
  if (reason === "recruiter_message_missing") return "Falta mensaje para recruiter."
  if (reason === "ats_cv_missing") return "Falta CV optimizado."
  if (reason === "ats_cv_too_short") return "El CV optimizado parece demasiado corto."
  if (reason === "autofill_notes_missing") return "Faltan respuestas para el portal."
  if (reason.startsWith("ats_cv_contains_avoid_overclaiming_terms:")) {
    return `Revisar afirmaciones sobre ${reason.split(":", 2)[1]}.`
  }
  return reason.replaceAll("_", " ")
}

function materialSummaries(job: JobListItem): PreparationViewState["materials"] {
  const review = job.materials_review
  const reasons = new Set(review?.reasons ?? [])
  const hasAny = job.has_materials
  const reviewRequired = Boolean(review?.requires_review)
  return [
    {
      id: "ats_cv",
      label: "CV",
      ready: hasAny && !reasons.has("ats_cv_missing"),
      needsReview: reviewRequired && (reasons.has("ats_cv_too_short") || [...reasons].some((reason) => reason.startsWith("ats_cv_"))),
    },
    {
      id: "cover_letter",
      label: "Cover letter",
      ready: hasAny,
      needsReview: reviewRequired,
    },
    {
      id: "autofill",
      label: "Respuestas",
      ready: hasAny && !reasons.has("autofill_notes_missing"),
      needsReview: reviewRequired && reasons.has("autofill_notes_missing"),
    },
    {
      id: "recruiter_message",
      label: "Recruiter",
      ready: hasAny && !reasons.has("recruiter_message_missing"),
      needsReview: reviewRequired && reasons.has("recruiter_message_missing"),
    },
  ]
}

function humanBlocker(job: JobListItem, session?: ApplicationSession | null): string | null {
  if (job.status !== "active") return "La oferta no esta activa. Revisa el portal antes de avanzar."
  if (job.priority.blocker) return job.priority.blocker
  if (!session) return null
  if (session.last_error) return session.last_error
  if ((session.validation_errors_json ?? []).length > 0) return "Hay advertencias de validacion en el portal."
  if ((session.unknown_fields_json ?? []).length > 0) return "El portal tiene preguntas que debes responder manualmente."
  return null
}

function buildState(input: {
  status: PreparationStatus
  label: string
  description: string
  primaryAction: PreparationViewState["primaryAction"]
  secondaryActions: PreparationViewState["secondaryActions"]
  activeStep: PreparationStep["id"]
  blockedStep?: PreparationStep["id"]
  blocker?: string | null
  materials: PreparationViewState["materials"]
  completed: Partial<Record<PreparationStep["id"], boolean>>
}): PreparationViewState {
  const order: Array<PreparationStep["id"]> = ["materials", "review", "application", "confirmation"]
  const labels: Record<PreparationStep["id"], string> = {
    materials: "Materiales",
    review: "Revision",
    application: "Aplicacion",
    confirmation: "Confirmacion",
  }
  return {
    status: input.status,
    label: input.label,
    description: input.description,
    primaryAction: input.primaryAction,
    secondaryActions: input.secondaryActions,
    blocker: input.blocker,
    materials: input.materials,
    progress: order.map((id) => ({
      id,
      label: labels[id],
      state: input.blockedStep === id ? "blocked" : input.completed[id] ? "done" : input.activeStep === id ? "active" : "todo",
    })),
  }
}
