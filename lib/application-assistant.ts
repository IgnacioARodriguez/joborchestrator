import type { ApplicationHumanInterventionItem, ApplicationSession } from "./types"

export type ApplicationAssistantKind =
  | "progress"
  | "login"
  | "captcha"
  | "consent"
  | "answer"
  | "resume"
  | "validation"
  | "final_review"
  | "unavailable"
  | "manual"
  | "complete"

export interface ApplicationAssistantState {
  kind: ApplicationAssistantKind
  title: string
  description: string
  fields: string[]
  portalUrl: string | null
  browserAvailable: boolean
  canResume: boolean
  canMarkSubmitted: boolean
}

const COPY: Record<ApplicationAssistantKind, Pick<ApplicationAssistantState, "title" | "description">> = {
  progress: {
    title: "Preparando la postulación",
    description: "El asistente local está analizando y completando el formulario.",
  },
  login: {
    title: "Iniciá sesión en el portal",
    description: "Completá el inicio de sesión o la creación de cuenta y después continuá la misma sesión.",
  },
  captcha: {
    title: "Resolvé la verificación humana",
    description: "Completá el CAPTCHA o control de seguridad. JobOrchestrator no intenta resolverlo automáticamente.",
  },
  consent: {
    title: "Revisá el consentimiento",
    description: "Esta acción tiene implicaciones legales o de privacidad y debe confirmarse personalmente.",
  },
  answer: {
    title: "Respondé los campos pendientes",
    description: "Faltan respuestas o hay datos que requieren tu confirmación antes de continuar.",
  },
  resume: {
    title: "Adjuntá o revisá el CV",
    description: "El portal no permitió verificar la carga del archivo. Revisalo manualmente antes de continuar.",
  },
  validation: {
    title: "Revisá el formulario",
    description: "El portal rechazó o no confirmó uno o más campos completados automáticamente.",
  },
  final_review: {
    title: "Formulario listo para enviar",
    description: "Revisá la candidatura en el portal y realizá personalmente el envío final.",
  },
  unavailable: {
    title: "La oferta ya no está disponible",
    description: "El portal indica que la publicación fue cerrada, eliminada o completada.",
  },
  manual: {
    title: "Se necesita una acción manual",
    description: "Abrí el portal, completá el paso pendiente y después continuá la automatización.",
  },
  complete: {
    title: "Postulación registrada",
    description: "La candidatura ya figura como enviada en JobOrchestrator.",
  },
}

export function friendlyApplicationProgress(message?: string | null) {
  const normalized = (message ?? "").toLowerCase()
  if (normalized.includes("waiting for your local worker")) return "Esperando al asistente local..."
  if (normalized.includes("opening external application")) return "Abriendo el portal de la empresa..."
  if (normalized.includes("detected provider")) return "Portal identificado. Analizando el formulario..."
  if (normalized.includes("filling safe")) return "Completando los campos seguros..."
  if (normalized.includes("resume") || normalized.includes("upload")) return "Adjuntando el CV preparado..."
  if (normalized.includes("validation") || normalized.includes("review")) return "Verificando el formulario..."
  if (normalized.includes("login")) return "Esperando que inicies sesión en el portal..."
  return message?.trim() || COPY.progress.description
}

export function getApplicationAssistantState(
  session: ApplicationSession | null,
  progressMessage?: string | null,
): ApplicationAssistantState {
  if (progressMessage) {
    return {
      kind: "progress",
      ...COPY.progress,
      description: friendlyApplicationProgress(progressMessage),
      fields: [],
      portalUrl: portalUrlFrom(session),
      browserAvailable: browserAvailable(session),
      canResume: false,
      canMarkSubmitted: false,
    }
  }

  const items = session?.artifacts_json.human_intervention?.items ?? []
  const kind = detectKind(session, items)
  return {
    kind,
    ...COPY[kind],
    fields: uniqueLabels(items, session?.unknown_fields_json ?? []),
    portalUrl: portalUrlFrom(session),
    browserAvailable: browserAvailable(session),
    canResume: session?.state === "needs_user_input" && kind !== "unavailable",
    canMarkSubmitted: Boolean(session && ["submit_only", "ready_for_review"].includes(session.state)),
  }
}

function detectKind(
  session: ApplicationSession | null,
  items: ApplicationHumanInterventionItem[],
): ApplicationAssistantKind {
  if (!session) return "manual"
  if (["submitted", "submitted_manually", "submission_verified"].includes(session.state)) return "complete"
  const text = [session.last_error, ...items.flatMap((item) => [item.type, item.reason, item.label])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
  if (/posting unavailable|closed|removed|no longer available/.test(text)) return "unavailable"
  if (/captcha|challenge|human verification|security check/.test(text)) return "captcha"
  if (/login|required login|sign in|log in|create account/.test(text)) return "login"
  if (items.some((item) => item.type === "consent")) return "consent"
  if (items.some((item) => ["answer", "demographic", "dynamic_field"].includes(item.type))) return "answer"
  if (items.some((item) => item.type === "resume_upload")) return "resume"
  if (items.some((item) => ["validation", "widget"].includes(item.type))) return "validation"
  if (["submit_only", "ready_for_review"].includes(session.state) || items.some((item) => item.type === "submit_only")) {
    return "final_review"
  }
  return "manual"
}

function uniqueLabels(items: ApplicationHumanInterventionItem[], unknown: Array<Record<string, unknown>>) {
  const labels = [
    ...items.map((item) => item.label || item.field),
    ...unknown.map((item) => String(item.label ?? item.name ?? "")),
  ].filter((value): value is string => Boolean(value?.trim()))
  return [...new Set(labels)].slice(0, 6)
}

function portalUrlFrom(session: ApplicationSession | null) {
  const artifacts = session?.artifacts_json
  const url = artifacts?.final_url || artifacts?.opened_url || artifacts?.url
  return typeof url === "string" && /^https?:\/\//.test(url) ? url : null
}

function browserAvailable(session: ApplicationSession | null) {
  return session?.artifacts_json.browser_handoff?.status === "started"
}
