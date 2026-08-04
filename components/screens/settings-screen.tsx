"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Bot,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FileText,
  Globe2,
  LoaderCircle,
  MapPin,
  Play,
  Plus,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Upload,
  UserRound,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
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
import { PageHeader } from "@/components/page-chrome"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Section } from "@/lib/nav"
import type {
  AnswerDefinition,
  ApplicationTarget,
  AutomationAccount,
  CandidateProfile,
  CompanySource,
  LinkedInProfileSetting,
  OperationRun,
  OpsStatus,
  ProfileSkill,
  WorkMode,
} from "@/lib/types"

type SettingsView =
  | "overview"
  | "profile"
  | "search"
  | "sources"
  | "automation"
  | "advanced"

type BusyAction = "load" | "save" | "cv" | "source" | "scan" | null

const EMPTY_PROFILE: CandidateProfile = {
  schema_version: 1,
  headline: "",
  target_roles: [],
  secondary_roles: [],
  role_aliases: {},
  skills: [],
  industries: [],
  preferred_locations: [],
  preferred_work_modes: [],
  application_targets: [],
  dealbreakers: [],
  avoid_roles: [],
  real_experience_years: 0,
  notes: "",
  suggested_roles_reasoning: "",
}

const WORK_MODE_LABELS: Record<WorkMode, string> = {
  onsite: "Presencial",
  hybrid: "Híbrido",
  remote: "Remoto",
}

const SETTINGS_VIEWS: Array<{
  id: SettingsView
  label: string
  description: string
  icon: typeof UserRound
}> = [
  {
    id: "overview",
    label: "Resumen",
    description: "Estado general y acciones pendientes",
    icon: CheckCircle2,
  },
  {
    id: "profile",
    label: "Perfil",
    description: "Experiencia, CV y habilidades",
    icon: UserRound,
  },
  {
    id: "search",
    label: "Qué busco",
    description: "Roles, ubicaciones y límites",
    icon: Search,
  },
  {
    id: "sources",
    label: "Fuentes",
    description: "Dónde encontrar oportunidades",
    icon: Globe2,
  },
  {
    id: "automation",
    label: "Automatización",
    description: "Qué hace JobOrchestrator por vos",
    icon: Bot,
  },
  {
    id: "advanced",
    label: "Avanzado",
    description: "Diagnóstico y controles técnicos",
    icon: Settings2,
  },
]

function listFromText(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
}

function lines(value: string[]) {
  return value.join("\n")
}

function normalizeProfile(profile: CandidateProfile | null): CandidateProfile {
  if (!profile) return { ...EMPTY_PROFILE }
  return {
    ...EMPTY_PROFILE,
    ...profile,
    target_roles: profile.target_roles ?? [],
    secondary_roles: profile.secondary_roles ?? [],
    role_aliases: profile.role_aliases ?? {},
    skills: profile.skills ?? [],
    industries: profile.industries ?? [],
    preferred_locations: profile.preferred_locations ?? [],
    preferred_work_modes: profile.preferred_work_modes ?? [],
    application_targets: profile.application_targets ?? [],
    dealbreakers: profile.dealbreakers ?? [],
    avoid_roles: profile.avoid_roles ?? [],
  }
}

function formatDateTime(value?: string | null) {
  if (!value) return "Sin actividad registrada"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("es-ES")
}

function humanize(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function accountStatus(status: string) {
  if (status === "ready") return { label: "Conectado", tone: "success" as const }
  if (status === "needs_login") return { label: "Iniciá sesión", tone: "warning" as const }
  if (status === "blocked") return { label: "Acceso bloqueado", tone: "danger" as const }
  if (status === "failed") return { label: "Necesita atención", tone: "danger" as const }
  return { label: "Sin verificar", tone: "neutral" as const }
}

function statusClasses(tone: "success" | "warning" | "danger" | "neutral") {
  if (tone === "success") return "bg-success/10 text-success-foreground"
  if (tone === "warning") return "bg-warning/10 text-warning-foreground"
  if (tone === "danger") return "bg-destructive/10 text-destructive"
  return "bg-muted text-muted-foreground"
}

function StatusPill({ label, tone }: { label: string; tone: "success" | "warning" | "danger" | "neutral" }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium", statusClasses(tone))}>
      {label}
    </span>
  )
}

function parseAtsUrl(rawValue: string) {
  const url = new URL(rawValue.trim())
  const host = url.hostname.toLowerCase()
  const pathParts = url.pathname.split("/").filter(Boolean)

  if (host.includes("greenhouse.io")) {
    const ref = url.searchParams.get("for") || pathParts[0]
    if (ref) return { provider: "greenhouse", companyRef: ref }
  }
  if (host.includes("lever.co")) {
    const ref = pathParts[0]
    if (ref) return { provider: "lever", companyRef: ref }
  }
  if (host.includes("ashbyhq.com")) {
    const ref = pathParts[0]
    if (ref) return { provider: "ashby", companyRef: ref }
  }

  return null
}

function labelFromRef(value: string) {
  return value
    .replaceAll("-", " ")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function scanSummary(operation: OperationRun | null) {
  const output = (operation?.output_json || {}) as {
    summary?: { found?: number; new?: number; updated?: number; errors?: number }
  }
  return output.summary || {}
}

const ACTIVE_OPERATION_STATUSES = new Set(["queued", "running"])

function isActiveOperation(operation: OperationRun | null | undefined) {
  return Boolean(operation && ACTIVE_OPERATION_STATUSES.has(operation.status))
}

function trackedOperationIds(...operationIds: Array<number | null>) {
  const validIds = operationIds.filter(
    (id): id is number => typeof id === "number" && id > 0,
  )
  return [...new Set(validIds)]
}

export function SettingsScreen({ onNavigate }: { onNavigate: (section: Section) => void }) {
  const [view, setView] = useState<SettingsView>(() => {
    if (typeof window === "undefined") return "overview"
    const hash = window.location.hash.replace("#", "") as SettingsView
    return SETTINGS_VIEWS.some((item) => item.id === hash) ? hash : "overview"
  })
  const [profile, setProfile] = useState<CandidateProfile>(EMPTY_PROFILE)
  const [sources, setSources] = useState<CompanySource[]>([])
  const [searchProviders, setSearchProviders] = useState<string[]>([])
  const [accounts, setAccounts] = useState<AutomationAccount[]>([])
  const [answers, setAnswers] = useState<AnswerDefinition[]>([])
  const [opsStatus, setOpsStatus] = useState<OpsStatus | null>(null)
  const [latestScan, setLatestScan] = useState<OperationRun | null>(null)
  const [linkedinProfile, setLinkedinProfile] = useState<LinkedInProfileSetting | null>(null)
  const [busy, setBusy] = useState<BusyAction>("load")
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [cvOperationId, setCvOperationId] = useState<number | null>(null)
  const [scanOperationId, setScanOperationId] = useState<number | null>(null)
  const [newPrimaryRole, setNewPrimaryRole] = useState("")
  const [newSecondaryRole, setNewSecondaryRole] = useState("")
  const [newSkill, setNewSkill] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [sourceCompany, setSourceCompany] = useState("")
  const pollErrorShownRef = useRef(false)

  const loadProfile = useCallback(async () => {
    const data = await api.getProfile()
    setProfile(normalizeProfile(data.profile))
  }, [])

  const loadSources = useCallback(async () => {
    const data = await api.getSources()
    setSources(data.sources)
    setSearchProviders(data.search_providers)
  }, [])

  const loadOpsStatus = useCallback(async () => {
    const data = await api.getOpsStatus()
    setOpsStatus(data)
    return data
  }, [])

  const loadSettings = useCallback(async (showLoader = false) => {
    if (showLoader) setBusy("load")
    try {
      const [, , accountData, answerData, opsData, scanData, linkedinData] = await Promise.all([
        loadProfile(),
        loadSources(),
        api.getAutomationAccounts(),
        api.getAnswers(),
        loadOpsStatus(),
        api.getLatestOperation("job_scan"),
        api.getLinkedInProfile(),
      ])
      setAccounts(accountData.accounts)
      setAnswers(answerData.answers)
      setLatestScan(scanData.operation)
      setLinkedinProfile(linkedinData.linkedin_profile)

      const activeOperations = opsData.active_local_operations ?? []
      const activeCv = activeOperations.find(
        (operation) => operation.type === "cv_profile_import" && isActiveOperation(operation),
      )
      const activeScan = activeOperations.find(
        (operation) => operation.type === "job_scan" && isActiveOperation(operation),
      )
      const latestScanId = isActiveOperation(scanData.operation)
        ? scanData.operation?.id ?? null
        : null
      setCvOperationId(activeCv?.id ?? null)
      setScanOperationId(activeScan?.id ?? latestScanId)
    } catch (error) {
      toast.error("No se pudo cargar la configuración", {
        description: error instanceof Error ? error.message : "El backend no respondió.",
      })
    } finally {
      if (showLoader) setBusy(null)
    }
  }, [loadOpsStatus, loadProfile, loadSources])

  useEffect(() => {
    // Initial API synchronization intentionally hydrates the screen state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSettings(true)
  }, [loadSettings])

  useEffect(() => {
    const operationIds = trackedOperationIds(cvOperationId, scanOperationId)
    if (operationIds.length === 0) return

    const trackedCvId = cvOperationId
    const trackedScanId = scanOperationId
    let stopped = false
    let timer: number | undefined

    function clearTimer() {
      if (timer === undefined) return
      window.clearTimeout(timer)
      timer = undefined
    }

    function schedule(delay: number) {
      clearTimer()
      if (stopped || document.visibilityState === "hidden") return
      timer = window.setTimeout(() => void poll(), delay)
    }

    async function poll() {
      if (stopped || document.visibilityState === "hidden") return

      try {
        const response = await api.getOperationsByIds(operationIds)
        if (stopped) return
        pollErrorShownRef.current = false

        const operationsById = new Map(
          response.operations.map((operation) => [operation.id, operation]),
        )
        const resourcesToRefresh = new Set<"profile" | "ops">()
        let hasActiveOperation = false

        if (trackedCvId) {
          const cvOperation = operationsById.get(trackedCvId)
          if (!cvOperation) {
            hasActiveOperation = true
          } else if (isActiveOperation(cvOperation)) {
            hasActiveOperation = true
          } else if (cvOperation.status === "completed") {
            setCvOperationId((current) => (current === trackedCvId ? null : current))
            resourcesToRefresh.add("profile")
            resourcesToRefresh.add("ops")
            toast.success("CV analizado", {
              description: "El perfil se actualizó y podés revisarlo antes de guardarlo.",
            })
          } else if (["failed", "cancelled"].includes(cvOperation.status)) {
            setCvOperationId((current) => (current === trackedCvId ? null : current))
            resourcesToRefresh.add("ops")
            toast.error("No se pudo analizar el CV", {
              description: cvOperation.error || "Revisá el procesamiento local.",
            })
          }
        }

        if (trackedScanId) {
          const scanOperation = operationsById.get(trackedScanId)
          if (!scanOperation) {
            hasActiveOperation = true
          } else {
            setLatestScan(scanOperation)
            if (isActiveOperation(scanOperation)) {
              hasActiveOperation = true
            } else if (scanOperation.status === "completed") {
              setScanOperationId((current) => (current === trackedScanId ? null : current))
              resourcesToRefresh.add("ops")
              toast.success("Búsqueda completada", {
                description: "Las nuevas oportunidades ya están disponibles en Jobs.",
              })
            } else if (["failed", "cancelled"].includes(scanOperation.status)) {
              setScanOperationId((current) => (current === trackedScanId ? null : current))
              resourcesToRefresh.add("ops")
              toast.error("La búsqueda necesita atención", {
                description: scanOperation.error || "Revisá el diagnóstico avanzado.",
              })
            }
          }
        }

        if (resourcesToRefresh.size > 0) {
          const refreshes = [...resourcesToRefresh].map((resource) =>
            resource === "profile" ? loadProfile() : loadOpsStatus(),
          )
          const results = await Promise.allSettled(refreshes)
          if (!stopped && results.some((result) => result.status === "rejected")) {
            toast.error("La operación terminó, pero no se pudieron actualizar todos los datos.")
          }
        }
        if (!stopped && hasActiveOperation) schedule(2000)
      } catch (error) {
        if (stopped) return
        if (!pollErrorShownRef.current) {
          pollErrorShownRef.current = true
          toast.error("No se pudo actualizar el progreso", {
            description: error instanceof Error ? error.message : "El backend no respondió.",
          })
        }
        schedule(4000)
      }
    }

    function onVisibilityChange() {
      if (document.visibilityState === "hidden") {
        clearTimer()
        return
      }
      schedule(0)
    }

    document.addEventListener("visibilitychange", onVisibilityChange)
    schedule(1000)
    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [cvOperationId, loadOpsStatus, loadProfile, scanOperationId])

  const enabledSources = useMemo(
    () => sources.filter((source) => Boolean(source.enabled)),
    [sources],
  )
  const linkedinAccount = useMemo(
    () => accounts.find((account) => account.domain.toLowerCase().includes("linkedin")) ?? null,
    [accounts],
  )
  const readyAccounts = useMemo(
    () => accounts.filter((account) => account.status === "ready").length,
    [accounts],
  )
  const answersReady = useMemo(
    () => answers.filter((answer) => !answer.requires_confirmation && (answer.status ?? "approved") === "approved").length,
    [answers],
  )
  const answersToReview = answers.length - answersReady
  const profileChecks = [
    Boolean(profile.headline.trim()),
    profile.target_roles.length > 0,
    profile.skills.length >= 3,
    profile.application_targets.length > 0,
    profile.real_experience_years > 0,
  ]
  const profileCompletion = Math.round(
    (profileChecks.filter(Boolean).length / profileChecks.length) * 100,
  )
  const pendingActions = [
    profileCompletion < 80 ? "Completar el perfil profesional" : null,
    enabledSources.length === 0 && searchProviders.length === 0 ? "Activar al menos una fuente" : null,
    linkedinAccount && linkedinAccount.status !== "ready" ? "Iniciar sesión en LinkedIn" : null,
    answersToReview > 0 ? `Revisar ${answersToReview} respuestas de formularios` : null,
  ].filter((item): item is string => Boolean(item))

  function changeView(nextView: SettingsView) {
    setView(nextView)
    window.history.replaceState(null, "", `/settings#${nextView}`)
  }

  function patchProfile(update: Partial<CandidateProfile>) {
    setProfile((current) => ({ ...current, ...update }))
  }

  function addRole(field: "target_roles" | "secondary_roles", rawValue: string) {
    const role = rawValue.trim()
    if (!role) return
    const allRoles = [...profile.target_roles, ...profile.secondary_roles]
    if (allRoles.some((item) => item.toLowerCase() === role.toLowerCase())) return
    patchProfile({ [field]: [...profile[field], role] })
    if (field === "target_roles") setNewPrimaryRole("")
    else setNewSecondaryRole("")
  }

  function removeRole(field: "target_roles" | "secondary_roles", role: string) {
    const aliases = { ...profile.role_aliases }
    delete aliases[role]
    patchProfile({
      [field]: profile[field].filter((item) => item !== role),
      role_aliases: aliases,
    })
  }

  function addSkill() {
    const name = newSkill.trim()
    if (!name) return
    if (profile.skills.some((skill) => skill.name.toLowerCase() === name.toLowerCase())) return
    const skill: ProfileSkill = {
      name,
      category: "General",
      level: "medium",
      evidence: "Agregada manualmente.",
    }
    patchProfile({ skills: [...profile.skills, skill] })
    setNewSkill("")
  }

  function updateTarget(index: number, update: Partial<ApplicationTarget>) {
    patchProfile({
      application_targets: profile.application_targets.map((target, targetIndex) =>
        targetIndex === index ? { ...target, ...update } : target,
      ),
    })
  }

  function toggleWorkMode(index: number, mode: WorkMode) {
    const target = profile.application_targets[index]
    if (!target) return
    const active = target.work_modes.includes(mode)
    const nextModes = active
      ? target.work_modes.filter((item) => item !== mode)
      : [...target.work_modes, mode]
    updateTarget(index, { work_modes: nextModes.length ? nextModes : [mode] })
  }

  async function saveProfile() {
    setBusy("save")
    try {
      const response = await api.saveProfile(profile)
      setProfile(response.profile)
      toast.success("Cambios guardados", {
        description: "El ranking y las próximas búsquedas usarán esta configuración.",
      })
    } catch (error) {
      toast.error("No se pudieron guardar los cambios", {
        description: error instanceof Error ? error.message : "El backend no respondió.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function importCv() {
    if (!cvFile) return
    setBusy("cv")
    try {
      const response = await api.importProfileCv(cvFile)
      setCvOperationId(response.operation_id)
      setCvFile(null)
      toast.success("CV recibido", {
        description: "JobOrchestrator lo está leyendo para actualizar tu perfil.",
      })
    } catch (error) {
      toast.error("No se pudo subir el CV", {
        description: error instanceof Error ? error.message : "El backend no respondió.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function addSource() {
    const parsed = (() => {
      try {
        return parseAtsUrl(sourceUrl)
      } catch {
        return null
      }
    })()

    if (!parsed) {
      toast.error("No pudimos detectar el portal", {
        description: "Usá un enlace de Greenhouse, Lever o Ashby, o abrí la configuración avanzada.",
      })
      return
    }

    const companyName = sourceCompany.trim() || labelFromRef(parsed.companyRef)
    setBusy("source")
    try {
      await api.addSource({
        provider: parsed.provider,
        company_name: companyName,
        company_ref: parsed.companyRef,
        enabled: true,
      })
      setSourceUrl("")
      setSourceCompany("")
      await loadSources()
      toast.success("Portal agregado", {
        description: `${companyName} se incluirá en las próximas búsquedas.`,
      })
    } catch (error) {
      toast.error("No se pudo agregar el portal", {
        description: error instanceof Error ? error.message : "El backend no respondió.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function scanFreshJobs() {
    setBusy("scan")
    try {
      const response = await api.scanFresh()
      setScanOperationId(response.operation_id)
      toast.success(response.already_running ? "La búsqueda ya estaba en curso" : "Búsqueda iniciada", {
        description: response.progress_message || "Los resultados aparecerán automáticamente en Jobs.",
      })
    } catch (error) {
      toast.error("No se pudo iniciar la búsqueda", {
        description: error instanceof Error ? error.message : "El backend no respondió.",
      })
    } finally {
      setBusy(null)
    }
  }

  const summary = scanSummary(latestScan)
  const linkedinStatus = linkedinAccount
    ? accountStatus(linkedinAccount.status)
    : { label: "Sin configurar", tone: "neutral" as const }
  const scanActive = latestScan ? ["queued", "running"].includes(latestScan.status) : false

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 pb-6">
      <PageHeader
        title="Configuración"
        description="Definí quién sos, qué trabajo buscás y hasta dónde querés automatizar."
      />

      {busy === "load" ? (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="flex items-center gap-3 p-4">
            <LoaderCircle className="size-5 animate-spin text-primary" />
            <div>
              <p className="text-sm font-medium">Cargando configuración</p>
              <p className="text-xs text-muted-foreground">Estamos reuniendo tu perfil, fuentes y automatizaciones.</p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="min-w-0">
          <div className="flex gap-2 overflow-x-auto pb-1 lg:sticky lg:top-0 lg:flex-col lg:overflow-visible">
            {SETTINGS_VIEWS.map((item) => {
              const Icon = item.icon
              const active = view === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => changeView(item.id)}
                  className={cn(
                    "flex min-w-[170px] items-center gap-3 rounded-xl border px-3 py-3 text-left transition-colors lg:min-w-0",
                    active
                      ? "border-primary/30 bg-primary/5 text-foreground"
                      : "border-transparent text-muted-foreground hover:border-border hover:bg-muted/40 hover:text-foreground",
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", active ? "bg-primary text-primary-foreground" : "bg-muted")}>
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{item.label}</span>
                    <span className="hidden text-[11px] leading-snug text-muted-foreground lg:block">{item.description}</span>
                  </span>
                  <ChevronRight className="hidden size-4 lg:block" />
                </button>
              )
            })}
          </div>
        </aside>

        <section className="min-w-0">
          {view === "overview" ? (
            <div className="flex flex-col gap-4">
              <Card className="border-primary/20 bg-primary/5">
                <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="size-5 text-primary" />
                      <p className="font-semibold text-foreground">
                        {pendingActions.length === 0 ? "Configuración lista" : "Tu configuración está casi lista"}
                      </p>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {pendingActions.length === 0
                        ? "JobOrchestrator tiene la información necesaria para buscar, priorizar y preparar aplicaciones."
                        : `${pendingActions.length} ${pendingActions.length === 1 ? "acción pendiente" : "acciones pendientes"}.`}
                    </p>
                  </div>
                  <Button onClick={() => changeView(pendingActions[0]?.includes("perfil") ? "profile" : pendingActions[0]?.includes("fuente") ? "sources" : pendingActions[0]?.includes("LinkedIn") ? "sources" : pendingActions[0]?.includes("respuestas") ? "automation" : "profile")}>
                    Revisar pendientes
                  </Button>
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                <button type="button" className="text-left" onClick={() => changeView("profile")}>
                  <Card className="h-full transition-colors hover:border-primary/30">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Perfil</p>
                      <p className="mt-1 text-2xl font-semibold">{profileCompletion}%</p>
                      <p className="mt-2 text-xs text-muted-foreground">{profile.skills.length} habilidades · {profile.target_roles.length} roles principales</p>
                    </CardContent>
                  </Card>
                </button>
                <button type="button" className="text-left" onClick={() => changeView("search")}>
                  <Card className="h-full transition-colors hover:border-primary/30">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Búsqueda</p>
                      <p className="mt-1 text-2xl font-semibold">{profile.application_targets.length}</p>
                      <p className="mt-2 text-xs text-muted-foreground">zonas configuradas</p>
                    </CardContent>
                  </Card>
                </button>
                <button type="button" className="text-left" onClick={() => changeView("sources")}>
                  <Card className="h-full transition-colors hover:border-primary/30">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Fuentes</p>
                      <p className="mt-1 text-2xl font-semibold">{enabledSources.length + searchProviders.length}</p>
                      <p className="mt-2 text-xs text-muted-foreground">portales y servicios activos</p>
                    </CardContent>
                  </Card>
                </button>
                <button type="button" className="text-left" onClick={() => changeView("automation")}>
                  <Card className="h-full transition-colors hover:border-primary/30">
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">Autocompletado</p>
                      <p className="mt-1 text-2xl font-semibold">{answersReady}</p>
                      <p className="mt-2 text-xs text-muted-foreground">respuestas aprobadas</p>
                    </CardContent>
                  </Card>
                </button>
              </div>

              {pendingActions.length > 0 ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Acciones pendientes</CardTitle>
                    <CardDescription className="text-xs">Resolvelas para que la automatización tenga menos interrupciones.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    {pendingActions.map((action) => (
                      <div key={action} className="flex items-center gap-3 rounded-lg border border-border p-3 text-sm">
                        <CircleAlert className="size-4 shrink-0 text-warning-foreground" />
                        <span>{action}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ) : null}
            </div>
          ) : null}

          {view === "profile" ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold">Tu perfil profesional</h2>
                  <p className="text-sm text-muted-foreground">Se usa para ordenar oportunidades y generar materiales sin inventar experiencia.</p>
                </div>
                <Button disabled={busy !== null} onClick={() => void saveProfile()}>
                  {busy === "save" ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Save data-icon="inline-start" />}
                  {busy === "save" ? "Guardando" : "Guardar cambios"}
                </Button>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm"><FileText className="size-4 text-primary" /> CV principal</CardTitle>
                    <CardDescription className="text-xs">Subí un CV para completar o actualizar automáticamente el perfil.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    {profile.base_cv_filename ? (
                      <div className="rounded-lg border border-border bg-muted/20 p-3 text-sm">
                        <p className="font-medium">{profile.base_cv_filename}</p>
                        <p className="mt-1 text-xs text-muted-foreground">CV actualmente usado como fuente de verdad.</p>
                      </div>
                    ) : null}
                    <Input type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => setCvFile(event.target.files?.[0] ?? null)} />
                    <Button variant="outline" disabled={!cvFile || busy !== null || cvOperationId !== null} onClick={() => void importCv()}>
                      {busy === "cv" || cvOperationId ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Upload data-icon="inline-start" />}
                      {cvOperationId ? "Analizando CV" : "Actualizar desde CV"}
                    </Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Información profesional</CardTitle>
                    <CardDescription className="text-xs">Solo datos objetivos y verificables.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium">Título profesional</span>
                      <Input value={profile.headline} placeholder="Backend developer especializado en Python y APIs" onChange={(event) => patchProfile({ headline: event.target.value })} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium">Años reales de experiencia</span>
                      <Input type="number" min="0" step="0.5" value={profile.real_experience_years} onChange={(event) => patchProfile({ real_experience_years: Number(event.target.value) || 0 })} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium">Industrias o dominios</span>
                      <Textarea className="min-h-24" value={lines(profile.industries)} placeholder="Fintech&#10;Educación&#10;Developer tools" onChange={(event) => patchProfile({ industries: listFromText(event.target.value) })} />
                    </label>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Habilidades</CardTitle>
                  <CardDescription className="text-xs">Mantené una lista clara. El editor avanzado conserva niveles, categorías y evidencias.</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex gap-2">
                    <Input value={newSkill} placeholder="Agregar habilidad" onChange={(event) => setNewSkill(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addSkill() }} />
                    <Button size="icon" variant="outline" aria-label="Agregar habilidad" onClick={addSkill}><Plus className="size-4" /></Button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {profile.skills.map((skill, index) => (
                      <Badge key={`${skill.name}-${index}`} variant="secondary" className="gap-1.5 py-1.5">
                        {skill.name}
                        <button type="button" aria-label={`Quitar ${skill.name}`} onClick={() => patchProfile({ skills: profile.skills.filter((_, skillIndex) => skillIndex !== index) })}>
                          <X className="size-3" />
                        </button>
                      </Badge>
                    ))}
                    {profile.skills.length === 0 ? <p className="text-xs text-muted-foreground">Subí un CV o agregá las habilidades principales.</p> : null}
                  </div>
                  <Button variant="ghost" className="self-start" onClick={() => onNavigate("profile")}>Abrir editor completo de perfil</Button>
                </CardContent>
              </Card>
            </div>
          ) : null}

          {view === "search" ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold">Qué trabajo estás buscando</h2>
                  <p className="text-sm text-muted-foreground">Estas preferencias alimentan todas las fuentes; no hace falta repetirlas por portal.</p>
                </div>
                <Button disabled={busy !== null} onClick={() => void saveProfile()}>
                  {busy === "save" ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Save data-icon="inline-start" />}
                  {busy === "save" ? "Guardando" : "Guardar cambios"}
                </Button>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm"><BriefcaseBusiness className="size-4 text-primary" /> Roles objetivo</CardTitle>
                  <CardDescription className="text-xs">Los roles principales pesan más; los alternativos amplían la búsqueda.</CardDescription>
                </CardHeader>
                <CardContent className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <div className="flex flex-col gap-2">
                    <p className="text-xs font-medium">Principales</p>
                    <div className="flex gap-2">
                      <Input value={newPrimaryRole} placeholder="Backend Developer" onChange={(event) => setNewPrimaryRole(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addRole("target_roles", newPrimaryRole) }} />
                      <Button size="icon" variant="outline" aria-label="Agregar rol principal" onClick={() => addRole("target_roles", newPrimaryRole)}><Plus className="size-4" /></Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {profile.target_roles.map((role) => (
                        <Badge key={role} className="gap-1.5 py-1.5">{role}<button type="button" aria-label={`Quitar ${role}`} onClick={() => removeRole("target_roles", role)}><X className="size-3" /></button></Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex flex-col gap-2">
                    <p className="text-xs font-medium">También considerar</p>
                    <div className="flex gap-2">
                      <Input value={newSecondaryRole} placeholder="Solutions Engineer" onChange={(event) => setNewSecondaryRole(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addRole("secondary_roles", newSecondaryRole) }} />
                      <Button size="icon" variant="outline" aria-label="Agregar rol alternativo" onClick={() => addRole("secondary_roles", newSecondaryRole)}><Plus className="size-4" /></Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {profile.secondary_roles.map((role) => (
                        <Badge key={role} variant="secondary" className="gap-1.5 py-1.5">{role}<button type="button" aria-label={`Quitar ${role}`} onClick={() => removeRole("secondary_roles", role)}><X className="size-3" /></button></Badge>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm"><MapPin className="size-4 text-primary" /> Dónde buscar</CardTitle>
                  <CardDescription className="text-xs">Cada zona se usa en LinkedIn, portales ATS y APIs públicas.</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  {profile.application_targets.map((target, index) => (
                    <div key={`${target.label}-${index}`} className="grid grid-cols-1 gap-3 rounded-xl border border-border p-3 xl:grid-cols-[1fr_1.2fr_auto_auto]">
                      <label className="flex flex-col gap-1.5"><span className="text-xs font-medium">Nombre</span><Input value={target.label} placeholder="Málaga" onChange={(event) => updateTarget(index, { label: event.target.value })} /></label>
                      <label className="flex flex-col gap-1.5"><span className="text-xs font-medium">Ubicación</span><Input value={target.location} placeholder="Málaga, España" onChange={(event) => updateTarget(index, { location: event.target.value })} /></label>
                      <fieldset className="flex flex-col gap-1.5">
                        <legend className="text-xs font-medium">Modalidad</legend>
                        <div className="flex flex-wrap gap-1">
                          {(["onsite", "hybrid", "remote"] as WorkMode[]).map((mode) => (
                            <Button key={mode} type="button" size="sm" variant={target.work_modes.includes(mode) ? "default" : "outline"} onClick={() => toggleWorkMode(index, mode)}>{WORK_MODE_LABELS[mode]}</Button>
                          ))}
                        </div>
                      </fieldset>
                      <Button size="icon" variant="ghost" aria-label={`Quitar ${target.label}`} onClick={() => patchProfile({ application_targets: profile.application_targets.filter((_, targetIndex) => targetIndex !== index) })}><X className="size-4" /></Button>
                    </div>
                  ))}
                  <Button variant="outline" className="self-start" onClick={() => patchProfile({ application_targets: [...profile.application_targets, { label: "Nueva zona", location: "", work_modes: ["remote"] }] })}><Plus data-icon="inline-start" /> Agregar zona</Button>
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-sm">Roles que no querés</CardTitle><CardDescription className="text-xs">Uno por línea.</CardDescription></CardHeader>
                  <CardContent><Textarea className="min-h-32" value={lines(profile.avoid_roles)} placeholder="Staff Engineer&#10;Frontend puro" onChange={(event) => patchProfile({ avoid_roles: listFromText(event.target.value) })} /></CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Condiciones excluyentes</CardTitle><CardDescription className="text-xs">Ejemplos: live coding obligatorio, presencial fuera de Málaga, salario insuficiente.</CardDescription></CardHeader>
                  <CardContent><Textarea className="min-h-32" value={lines(profile.dealbreakers)} placeholder="Live coding obligatorio&#10;Relocation obligatoria" onChange={(event) => patchProfile({ dealbreakers: listFromText(event.target.value) })} /></CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader><CardTitle className="text-sm">Contexto adicional</CardTitle><CardDescription className="text-xs">Información que el ranking debe respetar, sin convertirla en una regla rígida.</CardDescription></CardHeader>
                <CardContent><Textarea className="min-h-28" value={profile.notes} placeholder="Prefiero puestos sin live coding y equipos con producto propio." onChange={(event) => patchProfile({ notes: event.target.value })} /></CardContent>
              </Card>
            </div>
          ) : null}

          {view === "sources" ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold">Fuentes de oportunidades</h2>
                  <p className="text-sm text-muted-foreground">JobOrchestrator usa tus objetivos de búsqueda automáticamente en todas las fuentes.</p>
                </div>
                <Button disabled={busy !== null || scanOperationId !== null} onClick={() => void scanFreshJobs()}>
                  {busy === "scan" || scanOperationId ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Play data-icon="inline-start" />}
                  {scanOperationId ? "Buscando oportunidades" : "Buscar ahora"}
                </Button>
              </div>

              {latestScan ? (
                <Card className={cn(scanActive && "border-primary/20 bg-primary/5")}>
                  <CardContent className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-5">
                    <div className="col-span-2 sm:col-span-1"><p className="text-xs text-muted-foreground">Estado</p><p className="mt-1 text-sm font-medium">{scanActive ? "En proceso" : latestScan.status === "completed" ? "Completada" : latestScan.status === "failed" ? "Necesita atención" : humanize(latestScan.status)}</p></div>
                    <div><p className="text-xs text-muted-foreground">Encontradas</p><p className="mt-1 text-lg font-semibold">{summary.found ?? 0}</p></div>
                    <div><p className="text-xs text-muted-foreground">Nuevas</p><p className="mt-1 text-lg font-semibold">{summary.new ?? 0}</p></div>
                    <div><p className="text-xs text-muted-foreground">Actualizadas</p><p className="mt-1 text-lg font-semibold">{summary.updated ?? 0}</p></div>
                    <div><p className="text-xs text-muted-foreground">Última actividad</p><p className="mt-1 text-xs font-medium">{formatDateTime(latestScan.updated_at)}</p></div>
                  </CardContent>
                </Card>
              ) : null}

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                <Card>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div><CardTitle className="text-sm">LinkedIn</CardTitle><CardDescription className="mt-1 text-xs">Usa una sesión de navegador local para buscar oportunidades.</CardDescription></div>
                      <StatusPill label={linkedinStatus.label} tone={linkedinStatus.tone} />
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs">
                      <p className="font-medium">Sesión: {linkedinProfile?.current || "main"}</p>
                      <p className="mt-1 text-muted-foreground">La sesión se reutiliza; no guardamos la contraseña en esta pantalla.</p>
                    </div>
                    <Button variant="outline" onClick={() => onNavigate("automations")}>Configurar sesión</Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div><CardTitle className="text-sm">Portales de empresas</CardTitle><CardDescription className="mt-1 text-xs">Greenhouse, Lever, Ashby y otras fuentes ATS.</CardDescription></div>
                      <StatusPill label={`${enabledSources.length} activos`} tone={enabledSources.length > 0 ? "success" : "neutral"} />
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex flex-wrap gap-1.5">
                      {enabledSources.slice(0, 6).map((source) => <Badge key={source.id} variant="secondary">{source.company_name}</Badge>)}
                      {enabledSources.length === 0 ? <p className="text-xs text-muted-foreground">Todavía no agregaste portales de empresas.</p> : null}
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div><CardTitle className="text-sm">Bolsas y APIs</CardTitle><CardDescription className="mt-1 text-xs">Servicios públicos que amplían la cobertura.</CardDescription></div>
                      <StatusPill label={`${searchProviders.length} activas`} tone={searchProviders.length > 0 ? "success" : "neutral"} />
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-1.5">
                    {searchProviders.map((provider) => <Badge key={provider} variant="outline">{humanize(provider)}</Badge>)}
                    {searchProviders.length === 0 ? <p className="text-xs text-muted-foreground">No hay APIs públicas configuradas.</p> : null}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Agregar portal de una empresa</CardTitle>
                  <CardDescription className="text-xs">Pegá el enlace de empleos. Detectamos automáticamente Greenhouse, Lever o Ashby.</CardDescription>
                </CardHeader>
                <CardContent className="grid grid-cols-1 gap-3 xl:grid-cols-[1.5fr_1fr_auto]">
                  <Input value={sourceUrl} placeholder="https://jobs.lever.co/empresa" onChange={(event) => setSourceUrl(event.target.value)} />
                  <Input value={sourceCompany} placeholder="Nombre de la empresa (opcional)" onChange={(event) => setSourceCompany(event.target.value)} />
                  <Button disabled={!sourceUrl.trim() || busy !== null} onClick={() => void addSource()}>
                    {busy === "source" ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Plus data-icon="inline-start" />}
                    Agregar
                  </Button>
                </CardContent>
              </Card>

              <Button variant="ghost" className="self-start" onClick={() => onNavigate("automations")}>Abrir configuración técnica de fuentes</Button>
            </div>
          ) : null}

          {view === "automation" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 className="text-lg font-semibold">Nivel de automatización</h2>
                <p className="text-sm text-muted-foreground">La automatización es asistida: prepara y completa, pero no envía una candidatura sin tu revisión.</p>
              </div>

              <Card>
                <CardContent className="flex flex-col gap-2 p-4">
                  {[
                    { title: "Buscar oportunidades", detail: "Consulta las fuentes activas usando tus roles y ubicaciones.", ready: enabledSources.length > 0 || searchProviders.length > 0, label: "Automático" },
                    { title: "Analizar y priorizar", detail: "Compara cada oferta con tu perfil y explica por qué encaja.", ready: profileCompletion >= 60, label: "Automático" },
                    { title: "Preparar CV y mensajes", detail: "Genera materiales adaptados cuando decidís aplicar.", ready: profileCompletion >= 60, label: "Al solicitarlo" },
                    { title: "Completar formularios", detail: "Usa únicamente respuestas aprobadas y detiene el flujo si falta información.", ready: answersReady > 0, label: "Asistido" },
                    { title: "Enviar candidatura", detail: "El envío final y los consentimientos legales permanecen bajo tu control.", ready: true, label: "Siempre manual" },
                  ].map((step, index) => (
                    <div key={step.title} className="flex items-start gap-3 rounded-xl border border-border p-3">
                      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold", step.ready ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>{index + 1}</span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{step.title}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{step.detail}</p>
                      </div>
                      <StatusPill label={step.ready ? step.label : "Falta configurar"} tone={step.ready ? "success" : "warning"} />
                    </div>
                  ))}
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Respuestas para formularios</CardTitle>
                    <CardDescription className="text-xs">El sistema diferencia datos estables de respuestas que siempre requieren revisión.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg border border-border bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Listas para usar</p><p className="mt-1 text-2xl font-semibold">{answersReady}</p></div>
                      <div className="rounded-lg border border-border bg-muted/20 p-3"><p className="text-xs text-muted-foreground">Requieren revisión</p><p className="mt-1 text-2xl font-semibold">{answersToReview}</p></div>
                    </div>
                    <div className="flex flex-col gap-2">
                      {answers.slice(0, 6).map((answer) => (
                        <div key={answer.canonical_key} className="flex items-center justify-between gap-2 rounded-lg border border-border p-2 text-xs">
                          <span className="truncate font-medium">{humanize(answer.canonical_key)}</span>
                          <StatusPill label={answer.requires_confirmation ? "Revisar" : "Aprobada"} tone={answer.requires_confirmation ? "warning" : "success"} />
                        </div>
                      ))}
                      {answers.length === 0 ? <p className="text-xs text-muted-foreground">Todavía no hay respuestas guardadas.</p> : null}
                    </div>
                    <Button variant="outline" onClick={() => onNavigate("profile")}>Administrar respuestas</Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Sesiones de portales</CardTitle>
                    <CardDescription className="text-xs">Cuentas y sesiones que el navegador puede reutilizar.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    {accounts.slice(0, 8).map((account) => {
                      const status = accountStatus(account.status)
                      return (
                        <div key={account.id} className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-xs">
                          <div className="min-w-0"><p className="truncate font-medium">{account.domain}</p><p className="mt-0.5 truncate text-muted-foreground">{humanize(account.provider)}</p></div>
                          <StatusPill label={status.label} tone={status.tone} />
                        </div>
                      )
                    })}
                    {accounts.length === 0 ? <p className="text-xs text-muted-foreground">Las sesiones aparecerán cuando abras un portal desde una aplicación.</p> : null}
                    <p className="pt-1 text-xs text-muted-foreground">{readyAccounts} sesiones listas para reutilizar.</p>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : null}

          {view === "advanced" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 className="text-lg font-semibold">Configuración avanzada</h2>
                <p className="text-sm text-muted-foreground">Herramientas de diagnóstico y edición detallada. No son necesarias para el uso normal.</p>
              </div>

              <Card className="border-warning/20 bg-warning/5">
                <CardContent className="flex items-start gap-3 p-4">
                  <CircleAlert className="mt-0.5 size-5 shrink-0 text-warning-foreground" />
                  <div><p className="text-sm font-medium">Esta sección expone conceptos técnicos</p><p className="mt-1 text-xs text-muted-foreground">Workers, proveedores, colas, IDs de operaciones y ajustes de diagnóstico se conservan acá para no perder control.</p></div>
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-sm">Editor completo de perfil</CardTitle><CardDescription className="text-xs">Alias de roles, niveles y evidencias de habilidades, respuestas canónicas y variantes de CV.</CardDescription></CardHeader>
                  <CardContent><Button variant="outline" onClick={() => onNavigate("profile")}>Abrir editor avanzado</Button></CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Consola de operaciones</CardTitle><CardDescription className="text-xs">Fuentes ATS, scraper de LinkedIn, workers locales, ranking y operaciones recientes.</CardDescription></CardHeader>
                  <CardContent><Button variant="outline" onClick={() => onNavigate("automations")}>Abrir consola técnica</Button></CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Estado del sistema</CardTitle><CardDescription className="text-xs">Resumen operativo sin detalles internos.</CardDescription></CardHeader>
                  <CardContent className="flex flex-col gap-2 text-sm">
                    <div className="flex items-center justify-between gap-3"><span>Procesamiento local</span><StatusPill label={opsStatus?.local_worker_needed ? "Requiere atención" : "Listo"} tone={opsStatus?.local_worker_needed ? "warning" : "success"} /></div>
                    <div className="flex items-center justify-between gap-3"><span>Análisis de oportunidades</span><StatusPill label={opsStatus?.ranking_worker_needed ? "Pendiente" : "Listo"} tone={opsStatus?.ranking_worker_needed ? "warning" : "success"} /></div>
                    <p className="pt-2 text-xs text-muted-foreground">{opsStatus?.summary || "Sin diagnóstico disponible."}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Insights</CardTitle><CardDescription className="text-xs">Métricas y lecturas avanzadas fuera del flujo principal.</CardDescription></CardHeader>
                  <CardContent><Button variant="outline" onClick={() => onNavigate("insights")}>Abrir insights</Button></CardContent>
                </Card>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  )
}
