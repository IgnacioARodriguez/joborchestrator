"use client"

import { useEffect, useMemo, useState } from "react"
import {
  BriefcaseBusiness,
  LoaderCircle,
  Plus,
  Save,
  Sparkles,
  Upload,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { PageHeader } from "@/components/page-chrome"
import {
  AsyncActionButton,
  TaskProgressCard,
  type TaskProgressStep,
} from "@/components/task-progress-card"
import { api } from "@/lib/api"
import type {
  ApplicationTarget,
  AnswerDefinition,
  AnswerSensitivity,
  AnswerStatus,
  CandidateProfile,
  OperationRun,
  ProfileSkill,
  ResumeVariant,
  SkillCatalogItem,
  SkillLevel,
  WorkMode,
} from "@/lib/types"
import { userFacingError } from "@/lib/user-facing-error"

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
  application_targets: [
    { label: "Malaga", location: "Malaga, Spain", work_modes: ["onsite", "hybrid", "remote"] },
    { label: "Europe Remote", location: "Europe", work_modes: ["remote"] },
    { label: "Barcelona", location: "Barcelona, Spain", work_modes: ["onsite"] },
  ],
  dealbreakers: [],
  avoid_roles: [],
  real_experience_years: 0,
  notes: "",
  suggested_roles_reasoning: "",
}

const LEVEL_LABELS: Record<SkillLevel, string> = {
  strong: "Strong",
  medium: "Medium",
  weak: "Learning",
}

const WORK_MODE_LABELS: Record<WorkMode, string> = {
  onsite: "Onsite",
  hybrid: "Hybrid",
  remote: "Remote",
}

const ANSWER_CATEGORY: Record<AnswerSensitivity, string> = {
  public: "Automatic stable",
  preference: "Configurable",
  sensitive: "Always review",
}

const EMPTY_ANSWER: AnswerDefinition = {
  canonical_key: "",
  question_patterns: [],
  answer_type: "text",
  value: "",
  source: "approved",
  sensitivity: "public",
  requires_confirmation: false,
  status: "approved",
  last_confirmed_at: null,
}

function lines(value: string[]) {
  return value.join("\n")
}

function listFromText(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
}

function LoadingIcon() {
  return <LoaderCircle className="size-4 animate-spin" data-icon="inline-start" />
}

function skillKey(name: string) {
  return name.trim().toLowerCase()
}

function cvOperationDescription(operation: OperationRun) {
  if (operation.status === "queued") {
    return "El CV está en cola. El análisis comenzará cuando el asistente local esté disponible."
  }
  if (operation.status === "completed") {
    return "El CV fue analizado y el perfil editable ya está actualizado."
  }
  if (operation.status === "failed") {
    return userFacingError(
      operation.error,
      "No se pudo analizar el CV. Comprueba el asistente local e inténtalo nuevamente.",
    )
  }
  const message = operation.progress_message?.toLowerCase() ?? ""
  if (message.includes("extract") || message.includes("parse")) {
    return "Extrayendo experiencia, roles y tecnologías del CV."
  }
  if (message.includes("skill")) {
    return "Organizando las skills y el nivel de experiencia detectado."
  }
  if (message.includes("profile") || message.includes("save")) {
    return "Actualizando el perfil que utilizarán los rankings y las aplicaciones."
  }
  return "Leyendo el CV y convirtiéndolo en un perfil editable."
}

function cvOperationSteps(operation: OperationRun): TaskProgressStep[] {
  const queued = operation.status === "queued"
  const running = operation.status === "running"
  const completed = operation.status === "completed"
  const failed = operation.status === "failed"
  return [
    { label: "CV recibido", state: "done" },
    {
      label: "Esperando asistente local",
      state: queued ? "active" : "done",
    },
    {
      label: "Extrayendo experiencia y skills",
      state: completed ? "done" : failed ? "error" : running ? "active" : "pending",
    },
    {
      label: "Actualizando el perfil editable",
      state: completed ? "done" : failed ? "error" : "pending",
    },
  ]
}

export function ProfileScreen() {
  const [profile, setProfile] = useState<CandidateProfile>(EMPTY_PROFILE)
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadVersion, setLoadVersion] = useState(0)
  const [pendingActions, setPendingActions] = useState<Record<string, boolean>>({})
  const [operation, setOperation] = useState<OperationRun | null>(null)
  const [skillCatalog, setSkillCatalog] = useState<SkillCatalogItem[]>([])
  const [newTargetRole, setNewTargetRole] = useState("")
  const [newSecondaryRole, setNewSecondaryRole] = useState("")
  const [newCatalogSkill, setNewCatalogSkill] = useState("")
  const [newCatalogCategory, setNewCatalogCategory] = useState("General")
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string>>({})
  const [answers, setAnswers] = useState<AnswerDefinition[]>([])
  const [answerDraft, setAnswerDraft] = useState<AnswerDefinition>(EMPTY_ANSWER)
  const [resumes, setResumes] = useState<ResumeVariant[]>([])
  const [resumeDraft, setResumeDraft] = useState({ label: "", file_ref: "", base_version: "", diff_summary: "" })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoadState("loading")
      setLoadError(null)
      try {
        const response = await api.getProfile()
        if (!cancelled && response.profile) setProfile(response.profile)
        const catalog = await api.getSkillCatalog()
        if (!cancelled) setSkillCatalog(catalog.skills)
        const latest = await api.getLatestOperation("cv_profile_import")
        const [answerData, resumeData] = await Promise.all([
          api.getAnswers(),
          api.getResumes(),
        ])
        if (!cancelled) {
          setAnswers(answerData.answers)
          setResumes(resumeData.resumes)
        }
        if (!cancelled && latest.operation) {
          setOperation(latest.operation)
        }
        if (!cancelled) setLoadState("ready")
      } catch (error) {
        if (!cancelled) {
          const message = userFacingError(
            error,
            "No se pudo cargar el perfil. Comprueba la conexión e intenta nuevamente.",
          )
          setLoadError(message)
          setLoadState("error")
          toast.error("No se pudo cargar el perfil", { description: message })
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [loadVersion])

  useEffect(() => {
    if (!operation || !["queued", "running"].includes(operation.status)) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const response = await api.getOperation(operation.id)
        if (stopped) return
        setOperation(response.operation)
        if (response.operation.status === "completed") {
          const profileResponse = await api.getProfile()
          if (!stopped && profileResponse.profile) {
            setProfile(profileResponse.profile)
            toast.success("Perfil actualizado", {
              description: "El asistente terminó de leer el CV.",
            })
          }
          return
        }
        if (response.operation.status === "failed") {
          toast.error("No se pudo analizar el CV", {
            description: userFacingError(
              response.operation.error,
              "Comprueba el asistente local e intenta nuevamente.",
            ),
          })
          return
        }
        timer = window.setTimeout(poll, 2500)
      } catch (error) {
        if (!stopped) {
          toast.error("No se pudo actualizar el progreso", {
            description: userFacingError(error),
          })
          timer = window.setTimeout(poll, 3000)
        }
      }
    }
    timer = window.setTimeout(poll, 1000)
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [operation])

  const groupedSkills = useMemo(() => {
    const groups = new Map<string, ProfileSkill[]>()
    for (const skill of profile.skills) {
      const category = skill.category || "General"
      groups.set(category, [...(groups.get(category) ?? []), skill])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [profile.skills])

  const groupedCatalog = useMemo(() => {
    const selected = new Set(profile.skills.map((skill) => skillKey(skill.name)))
    const groups = new Map<string, SkillCatalogItem[]>()
    for (const skill of skillCatalog) {
      if (selected.has(skillKey(skill.name))) continue
      groups.set(skill.category, [...(groups.get(skill.category) ?? []), skill])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [profile.skills, skillCatalog])

  const groupedAnswers = useMemo(() => {
    const groups = new Map<AnswerSensitivity, AnswerDefinition[]>()
    for (const sensitivity of ["public", "preference", "sensitive"] as AnswerSensitivity[]) {
      groups.set(sensitivity, [])
    }
    for (const answer of answers) {
      groups.set(answer.sensitivity, [...(groups.get(answer.sensitivity) ?? []), answer])
    }
    return [...groups.entries()]
  }, [answers])

  const profileMutationPending = Object.entries(pendingActions).some(
    ([key, pending]) => pending && key.startsWith("profile:"),
  )
  const cvOperationActive = Boolean(
    operation && ["queued", "running"].includes(operation.status),
  )

  function setActionPending(action: string, pending: boolean) {
    setPendingActions((current) => {
      if (pending) return { ...current, [action]: true }
      const next = { ...current }
      delete next[action]
      return next
    })
  }

  function patch(update: Partial<CandidateProfile>) {
    setProfile((current) => ({ ...current, ...update }))
  }

  async function persistProfile(
    nextProfile: CandidateProfile,
    successMessage?: string,
    actionKey = "profile:save",
  ) {
    if (profileMutationPending) return
    setProfile(nextProfile)
    setActionPending(actionKey, true)
    try {
      const response = await api.saveProfile(nextProfile)
      setProfile(response.profile)
      if (successMessage) {
        toast.success(successMessage, {
          description: "Los cambios ya están guardados.",
        })
      }
    } catch (error) {
      toast.error("No se pudo guardar el perfil", {
        description: userFacingError(error),
      })
    } finally {
      setActionPending(actionKey, false)
    }
  }

  async function updateSkill(index: number, update: Partial<ProfileSkill>) {
    const nextProfile = {
      ...profile,
      skills: profile.skills.map((skill, i) =>
        i === index ? { ...skill, ...update } : skill,
      ),
    }
    await persistProfile(nextProfile, undefined, `profile:skill-level-${index}`)
  }

  async function addSkill(skill: Pick<ProfileSkill, "name" | "category">, level: SkillLevel = "medium") {
    const key = skillKey(skill.name)
    if (profile.skills.some((item) => skillKey(item.name) === key)) return
    const nextProfile = {
      ...profile,
      skills: [
        ...profile.skills,
        {
          name: skill.name,
          category: skill.category || "General",
          level,
          evidence: "Added manually.",
        },
      ],
    }
    await persistProfile(
      nextProfile,
      `${skill.name} agregada`,
      `profile:skill-add-${skillKey(skill.name)}`,
    )
  }

  async function addCustomCatalogSkill() {
    const name = newCatalogSkill.trim()
    const category = newCatalogCategory.trim() || "General"
    if (!name) return
    if (profileMutationPending) return
    if (profile.skills.some((item) => skillKey(item.name) === skillKey(name))) {
      toast.info("La skill ya está agregada", { description: name })
      return
    }
    const actionKey = "profile:catalog-skill-add"
    setActionPending(actionKey, true)
    try {
      const response = await api.addSkillCatalogItem({ category, name })
      setSkillCatalog(response.skills)
      setNewCatalogSkill("")
      const nextProfile = {
        ...profile,
        skills: [
          ...profile.skills,
          {
            name: response.skill.name,
            category: response.skill.category,
            level: "medium" as SkillLevel,
            evidence: "Agregada manualmente.",
          },
        ],
      }
      const saved = await api.saveProfile(nextProfile)
      setProfile(saved.profile)
      toast.success("Skill agregada", { description: response.skill.name })
    } catch (error) {
      toast.error("No se pudo agregar la skill", {
        description: userFacingError(error),
      })
    } finally {
      setActionPending(actionKey, false)
    }
  }

  async function removeSkill(index: number) {
    const skillName = profile.skills[index]?.name ?? "Skill"
    const nextProfile = {
      ...profile,
      skills: profile.skills.filter((_, i) => i !== index),
    }
    await persistProfile(
      nextProfile,
      `${skillName} eliminada`,
      `profile:skill-remove-${index}`,
    )
  }

  async function addRole(field: "target_roles" | "secondary_roles", value: string) {
    const role = value.trim()
    if (!role) return
    const exists = [...profile.target_roles, ...profile.secondary_roles].some(
      (item) => item.toLowerCase() === role.toLowerCase(),
    )
    if (exists) return
    const nextProfile = { ...profile, [field]: [...profile[field], role] }
    if (field === "target_roles") setNewTargetRole("")
    else setNewSecondaryRole("")
    await persistProfile(nextProfile, `${role} agregado`, `profile:role-add-${field}`)
  }

  async function removeRole(field: "target_roles" | "secondary_roles", role: string) {
    const aliases = { ...(profile.role_aliases ?? {}) }
    delete aliases[role]
    const nextProfile = {
      ...profile,
      [field]: profile[field].filter((item) => item !== role),
      role_aliases: aliases,
    }
    await persistProfile(
      nextProfile,
      `${role} eliminado`,
      `profile:role-remove-${field}-${role}`,
    )
  }

  async function addRoleAlias(role: string) {
    const alias = (aliasDrafts[role] ?? "").trim()
    if (!alias) return
    const existing = profile.role_aliases?.[role] ?? []
    if (existing.some((item) => item.toLowerCase() === alias.toLowerCase())) return
    const nextProfile = {
      ...profile,
      role_aliases: {
        ...(profile.role_aliases ?? {}),
        [role]: [...existing, alias],
      },
    }
    setAliasDrafts((current) => ({ ...current, [role]: "" }))
    await persistProfile(nextProfile, `${alias} agregado`, `profile:alias-add-${role}`)
  }

  async function removeRoleAlias(role: string, alias: string) {
    const nextProfile = {
      ...profile,
      role_aliases: {
        ...(profile.role_aliases ?? {}),
        [role]: (profile.role_aliases?.[role] ?? []).filter((item) => item !== alias),
      },
    }
    await persistProfile(
      nextProfile,
      `${alias} eliminado`,
      `profile:alias-remove-${role}-${alias}`,
    )
  }

  async function importCv() {
    if (!cvFile) return
    const actionKey = "cv:import"
    setActionPending(actionKey, true)
    try {
      const response = await api.importProfileCv(cvFile)
      const op = await api.getOperation(response.operation_id)
      setOperation(op.operation)
      setCvFile(null)
      toast.success("CV recibido", {
        description: "El progreso seguirá visible mientras el asistente lo analiza.",
      })
    } catch (error) {
      toast.error("No se pudo iniciar el análisis", {
        description: userFacingError(error),
      })
    } finally {
      setActionPending(actionKey, false)
    }
  }

  async function saveProfile(
    actionKey = "profile:save",
    successMessage = "Perfil guardado",
  ) {
    await persistProfile(profile, successMessage, actionKey)
  }

  async function saveAnswerDraft() {
    const canonical_key = answerDraft.canonical_key.trim()
    if (!canonical_key) return
    const actionKey = "answer:save"
    setActionPending(actionKey, true)
    try {
      const payload = {
        ...answerDraft,
        canonical_key,
        question_patterns: answerDraft.question_patterns.filter(Boolean),
        requires_confirmation:
          answerDraft.requires_confirmation || answerDraft.sensitivity !== "public" || answerDraft.status === "requires_confirmation",
      }
      const response = await api.saveAnswer(payload)
      setAnswers((current) => {
        const others = current.filter((answer) => answer.canonical_key !== response.answer.canonical_key)
        return [...others, response.answer].sort((a, b) => a.canonical_key.localeCompare(b.canonical_key))
      })
      setAnswerDraft(EMPTY_ANSWER)
      toast.success("Respuesta guardada", { description: canonical_key })
    } catch (error) {
      toast.error("No se pudo guardar la respuesta", {
        description: userFacingError(error),
      })
    } finally {
      setActionPending(actionKey, false)
    }
  }

  async function createResumeVariant() {
    const label = resumeDraft.label.trim()
    if (!label) return
    const actionKey = "resume:save"
    setActionPending(actionKey, true)
    try {
      const response = await api.createResume({
        label,
        file_ref: resumeDraft.file_ref || null,
        base_version: resumeDraft.base_version || null,
        diff_summary: resumeDraft.diff_summary || null,
      })
      setResumes((current) => [response.resume, ...current])
      setResumeDraft({ label: "", file_ref: "", base_version: "", diff_summary: "" })
      toast.success("Versión de CV guardada", { description: label })
    } catch (error) {
      toast.error("No se pudo guardar la versión de CV", {
        description: userFacingError(error),
      })
    } finally {
      setActionPending(actionKey, false)
    }
  }

  function updateApplicationTarget(index: number, update: Partial<ApplicationTarget>) {
    patch({
      application_targets: profile.application_targets.map((target, i) =>
        i === index ? { ...target, ...update } : target,
      ),
    })
  }

  function toggleTargetWorkMode(index: number, mode: WorkMode) {
    const target = profile.application_targets[index]
    if (!target) return
    const active = target.work_modes.includes(mode)
    const work_modes = active
      ? target.work_modes.filter((item) => item !== mode)
      : [...target.work_modes, mode]
    updateApplicationTarget(index, { work_modes: work_modes.length ? work_modes : [mode] })
  }

  return (
    <div className="flex flex-col gap-4 pb-6">
      <PageHeader
        eyebrow="Perfil"
        title="Perfil del candidato"
        description="Roles, zonas, skills y contexto que utilizan los rankings."
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {loadState === "loading" ? (
        <TaskProgressCard
          className="xl:col-span-2"
          title="Cargando tu perfil"
          description="Recuperando CV, roles, skills y respuestas reutilizables."
        />
      ) : null}

      {loadState === "error" ? (
        <TaskProgressCard
          className="xl:col-span-2"
          status="error"
          title="No se pudo cargar el perfil"
          description={loadError ?? "Comprueba la conexión e intenta nuevamente."}
          actions={
            <Button variant="outline" onClick={() => setLoadVersion((current) => current + 1)}>
              Reintentar
            </Button>
          }
        />
      ) : null}

      {operation && ["queued", "running", "failed", "completed"].includes(operation.status) ? (
        <TaskProgressCard
          className="xl:col-span-2"
          status={
            operation.status === "failed"
              ? "error"
              : operation.status === "completed"
                ? "success"
                : "active"
          }
          startedAt={operation.started_at ?? operation.created_at}
          title={
            operation.status === "completed"
              ? "Perfil actualizado desde el CV"
              : operation.status === "failed"
                ? "No se pudo analizar el CV"
                : "Analizando tu CV"
          }
          description={cvOperationDescription(operation)}
          steps={cvOperationSteps(operation)}
          technicalDetails={operation.status === "failed" ? operation.error : null}
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Upload className="size-4 text-primary" />
            CV Loader
          </CardTitle>
          <CardDescription className="text-xs">
            Upload a CV, then the local worker reads it with AI and saves an editable profile.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            disabled={pendingActions["cv:import"] || cvOperationActive}
            onChange={(event) => setCvFile(event.target.files?.[0] ?? null)}
          />
          <AsyncActionButton
            pending={Boolean(pendingActions["cv:import"])}
            pendingLabel="Preparando análisis…"
            disabled={!cvFile || cvOperationActive}
            onClick={() => void importCv()}
          >
            <Sparkles data-icon="inline-start" />
            Analizar CV
          </AsyncActionButton>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <BriefcaseBusiness className="size-4 text-primary" />
            Suggested roles
          </CardTitle>
          <CardDescription className="text-xs">
            Add roles and variants. Ranking treats variants as equivalent labels.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <div className="flex gap-2">
              <Input
                value={newTargetRole}
                placeholder="Add target role"
                onChange={(event) => setNewTargetRole(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void addRole("target_roles", newTargetRole)
                }}
              />
              <Button
                size="icon"
                variant="outline"
                aria-label="Agregar rol objetivo"
                disabled={profileMutationPending || !newTargetRole.trim()}
                onClick={() => void addRole("target_roles", newTargetRole)}
              >
                {pendingActions["profile:role-add-target_roles"] ? <LoadingIcon /> : <Plus className="size-4" />}
              </Button>
            </div>
            <div className="flex gap-2">
              <Input
                value={newSecondaryRole}
                placeholder="Add adjacent role"
                onChange={(event) => setNewSecondaryRole(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void addRole("secondary_roles", newSecondaryRole)
                }}
              />
              <Button
                size="icon"
                variant="outline"
                aria-label="Agregar rol secundario"
                disabled={profileMutationPending || !newSecondaryRole.trim()}
                onClick={() => void addRole("secondary_roles", newSecondaryRole)}
              >
                {pendingActions["profile:role-add-secondary_roles"] ? <LoadingIcon /> : <Plus className="size-4" />}
              </Button>
            </div>
          </div>
          {profile.suggested_roles_reasoning && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {profile.suggested_roles_reasoning}
            </p>
          )}
          {[...profile.target_roles, ...profile.secondary_roles].length === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
              Add a role or upload a CV to get AI suggestions.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {[
                ...profile.target_roles.map((role) => ({ role, field: "target_roles" as const })),
                ...profile.secondary_roles.map((role) => ({ role, field: "secondary_roles" as const })),
              ].map(({ role, field }) => (
                <div key={`${field}-${role}`} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant={field === "target_roles" ? "default" : "secondary"}>{role}</Badge>
                    <Button
                      aria-label={`Eliminar ${role}`}
                      size="icon-sm"
                      variant="ghost"
                      disabled={profileMutationPending}
                      onClick={() => void removeRole(field, role)}
                    >
                      {pendingActions[`profile:role-remove-${field}-${role}`] ? <LoadingIcon /> : <X className="size-3.5" />}
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {(profile.role_aliases?.[role] ?? []).map((alias) => (
                      <Badge key={alias} variant="outline">
                        {alias}
                        <button
                          className="ml-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
                          disabled={profileMutationPending}
                          aria-label={`Eliminar variante ${alias}`}
                          onClick={() => void removeRoleAlias(role, alias)}
                          type="button"
                        >
                          {pendingActions[`profile:alias-remove-${role}-${alias}`] ? (
                            <LoaderCircle className="size-3 animate-spin" />
                          ) : (
                            <X className="size-3" />
                          )}
                        </button>
                      </Badge>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={aliasDrafts[role] ?? ""}
                      placeholder="Add variant or translation"
                      onChange={(event) =>
                        setAliasDrafts((current) => ({ ...current, [role]: event.target.value }))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void addRoleAlias(role)
                      }}
                    />
                    <Button
                      size="icon"
                      variant="outline"
                      aria-label={`Agregar variante para ${role}`}
                      disabled={profileMutationPending || !(aliasDrafts[role] ?? "").trim()}
                      onClick={() => void addRoleAlias(role)}
                    >
                      {pendingActions[`profile:alias-add-${role}`] ? <LoadingIcon /> : <Plus className="size-4" />}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Profile basics</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-foreground">Professional headline</span>
            <Input
              value={profile.headline}
              placeholder="Backend engineer focused on APIs and automation"
              onChange={(event) => patch({ headline: event.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-foreground">Real experience years</span>
            <Input
              type="number"
              min="0"
              step="0.5"
              value={profile.real_experience_years}
              onChange={(event) =>
                patch({ real_experience_years: Number(event.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-foreground">Industries or domains</span>
            <Textarea
              value={lines(profile.industries)}
              onChange={(event) => patch({ industries: listFromText(event.target.value) })}
              placeholder="Fintech&#10;Developer tools&#10;Healthcare"
              className="min-h-24 text-xs"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-foreground">Notes for ranking</span>
            <Textarea
              value={profile.notes}
              onChange={(event) => patch({ notes: event.target.value })}
              placeholder="Preferences, constraints, and context the ranker should respect."
              className="min-h-24 text-xs"
            />
          </label>
          <AsyncActionButton
            pending={Boolean(pendingActions["profile:save"])}
            pendingLabel="Guardando perfil…"
            disabled={profileMutationPending && !pendingActions["profile:save"]}
            onClick={() => void saveProfile()}
          >
            <Save data-icon="inline-start" />
            Guardar perfil
          </AsyncActionButton>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Application geography</CardTitle>
          <CardDescription className="text-xs">
            Define exactly where and how scans should search. Each target is sent to every enabled search API.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {(profile.application_targets ?? []).map((target, index) => (
            <div key={`${target.label}-${index}`} className="grid grid-cols-1 gap-3 rounded-lg border border-border p-3 2xl:grid-cols-[1fr_1.2fr_auto_auto]">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-foreground">Target name</span>
                <Input
                  value={target.label}
                  placeholder="Malaga"
                  onChange={(event) => updateApplicationTarget(index, { label: event.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-foreground">Geography</span>
                <Input
                  value={target.location}
                  placeholder="Malaga, Spain"
                  onChange={(event) => updateApplicationTarget(index, { location: event.target.value })}
                />
              </label>
              <fieldset className="flex flex-col gap-1.5">
                <legend className="text-xs font-medium text-foreground">Work modes</legend>
                <div className="flex flex-wrap gap-1">
                {(["onsite", "hybrid", "remote"] as WorkMode[]).map((mode) => (
                  <Button
                    key={mode}
                    type="button"
                    size="sm"
                    variant={target.work_modes.includes(mode) ? "default" : "outline"}
                    onClick={() => toggleTargetWorkMode(index, mode)}
                  >
                    {WORK_MODE_LABELS[mode]}
                  </Button>
                ))}
                </div>
              </fieldset>
              <Button
                aria-label={`Remove ${target.label}`}
                size="icon"
                variant="ghost"
                onClick={() =>
                  patch({
                    application_targets: profile.application_targets.filter((_, i) => i !== index),
                  })
                }
              >
                <X className="size-4" />
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() =>
                patch({
                  application_targets: [
                    ...(profile.application_targets ?? []),
                    { label: "New target", location: "", work_modes: ["remote"] },
                  ],
                })
              }
            >
              <Plus data-icon="inline-start" />
              Add target
            </Button>
            <AsyncActionButton
              pending={Boolean(pendingActions["profile:geography-save"])}
              pendingLabel="Guardando zonas…"
              disabled={profileMutationPending && !pendingActions["profile:geography-save"]}
              onClick={() => void saveProfile("profile:geography-save", "Zonas guardadas")}
            >
              <Save data-icon="inline-start" />
              Guardar zonas
            </AsyncActionButton>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Skills</CardTitle>
          <CardDescription className="text-xs">
            Edit each detected skill level. Add missing skills from the catalog.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {groupedSkills.length === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
              Upload a CV to detect skills automatically.
            </p>
          ) : (
            groupedSkills.map(([category, skills]) => (
              <section key={category} className="flex flex-col gap-2">
                <h3 className="text-xs font-semibold text-foreground">{category}</h3>
                <div className="flex flex-col gap-2">
                  {skills.map((skill) => {
                    const index = profile.skills.indexOf(skill)
                    return (
                      <div
                        key={`${skill.name}-${index}`}
                        className="grid grid-cols-1 gap-2 rounded-lg border border-border p-2 text-xs md:grid-cols-[1fr_8rem_2rem]"
                      >
                        <div className="min-w-0">
                          <p className="font-medium text-foreground">{skill.name}</p>
                          {skill.evidence && (
                            <p className="mt-0.5 line-clamp-2 text-muted-foreground">
                              {skill.evidence}
                            </p>
                          )}
                        </div>
                        <Select
                          value={skill.level}
                          disabled={profileMutationPending}
                          onValueChange={(value) =>
                            void updateSkill(index, { level: value as SkillLevel })
                          }
                        >
                          <SelectTrigger aria-busy={Boolean(pendingActions[`profile:skill-level-${index}`])}>
                            {pendingActions[`profile:skill-level-${index}`] ? (
                              <span className="flex items-center gap-2 text-muted-foreground">
                                <LoaderCircle className="size-3.5 animate-spin" />
                                Guardando…
                              </span>
                            ) : (
                              <SelectValue />
                            )}
                          </SelectTrigger>
                          <SelectContent>
                            {(["strong", "medium", "weak"] as SkillLevel[]).map(
                              (level) => (
                                <SelectItem key={level} value={level}>
                                  {LEVEL_LABELS[level]}
                                </SelectItem>
                              ),
                            )}
                          </SelectContent>
                        </Select>
                        <Button
                          aria-label={`Eliminar ${skill.name}`}
                          size="icon-sm"
                          variant="ghost"
                          disabled={profileMutationPending}
                          onClick={() => void removeSkill(index)}
                        >
                          {pendingActions[`profile:skill-remove-${index}`] ? <LoadingIcon /> : <X className="size-3.5" />}
                        </Button>
                      </div>
                    )
                  })}
                </div>
              </section>
            ))
          )}
          {groupedCatalog.length > 0 && (
            <section className="flex flex-col gap-3 border-t pt-4">
              <div>
                <h3 className="text-xs font-semibold text-foreground">Skill suggestions</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Add known skills without asking AI to infer them again.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_auto]">
                <Input
                  value={newCatalogSkill}
                  placeholder="Add skill"
                  onChange={(event) => setNewCatalogSkill(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addCustomCatalogSkill()
                  }}
                />
                <Input
                  value={newCatalogCategory}
                  placeholder="Category"
                  onChange={(event) => setNewCatalogCategory(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void addCustomCatalogSkill()
                  }}
                />
                <AsyncActionButton
                  variant="outline"
                  pending={Boolean(pendingActions["profile:catalog-skill-add"])}
                  pendingLabel="Agregando…"
                  disabled={!newCatalogSkill.trim() || profileMutationPending}
                  onClick={() => void addCustomCatalogSkill()}
                >
                  <Plus data-icon="inline-start" />
                  Agregar
                </AsyncActionButton>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {groupedCatalog.map(([category, skills]) => (
                  <div key={category} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                    <p className="text-xs font-semibold text-foreground">{category}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {skills.map((skill) => (
                        <Button
                          key={skill.id}
                          size="xs"
                          variant="outline"
                          disabled={profileMutationPending}
                          onClick={() => void addSkill(skill)}
                        >
                          {pendingActions[`profile:skill-add-${skillKey(skill.name)}`] ? (
                            <LoaderCircle className="size-3 animate-spin" data-icon="inline-start" />
                          ) : (
                            <Plus className="size-3" data-icon="inline-start" />
                          )}
                          {skill.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Answer library</CardTitle>
          <CardDescription className="text-xs">
            Keep reusable answers explicit. Preference and sensitive answers require review before future autofill.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_10rem_12rem]">
            <Input
              value={answerDraft.canonical_key}
              placeholder="canonical_key"
              onChange={(event) => setAnswerDraft((current) => ({ ...current, canonical_key: event.target.value }))}
            />
            <Input
              value={answerDraft.question_patterns.join("\n")}
              placeholder="Question patterns"
              onChange={(event) =>
                setAnswerDraft((current) => ({ ...current, question_patterns: listFromText(event.target.value) }))
              }
            />
            <Select
              value={answerDraft.sensitivity}
              onValueChange={(value) =>
                setAnswerDraft((current) => ({
                  ...current,
                  sensitivity: value as AnswerSensitivity,
                  requires_confirmation: value !== "public" || current.requires_confirmation,
                }))
              }
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="public">Stable</SelectItem>
                <SelectItem value="preference">Configurable</SelectItem>
                <SelectItem value="sensitive">Sensitive</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={answerDraft.status ?? "approved"}
              onValueChange={(value) =>
                setAnswerDraft((current) => ({
                  ...current,
                  status: value as AnswerStatus,
                  requires_confirmation: value === "requires_confirmation" || current.requires_confirmation,
                }))
              }
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="proposed">Proposed</SelectItem>
                <SelectItem value="requires_confirmation">Needs confirmation</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
                <SelectItem value="expired">Expired</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Textarea
            value={answerDraft.value ?? ""}
            placeholder="Approved answer value"
            className="min-h-20 text-xs"
            onChange={(event) => setAnswerDraft((current) => ({ ...current, value: event.target.value }))}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={answerDraft.requires_confirmation}
                onChange={(event) => setAnswerDraft((current) => ({ ...current, requires_confirmation: event.target.checked }))}
              />
              Requires confirmation
            </label>
            <AsyncActionButton
              pending={Boolean(pendingActions["answer:save"])}
              pendingLabel="Guardando respuesta…"
              onClick={() => void saveAnswerDraft()}
              disabled={!answerDraft.canonical_key.trim()}
            >
              <Save data-icon="inline-start" />
              Guardar respuesta
            </AsyncActionButton>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {groupedAnswers.map(([sensitivity, items]) => (
              <section key={sensitivity} className="rounded-lg border border-border p-3">
                <h3 className="text-xs font-semibold text-foreground">{ANSWER_CATEGORY[sensitivity]}</h3>
                <div className="mt-2 flex flex-col gap-2">
                  {items.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No answers yet.</p>
                  ) : (
                    items.map((answer) => (
                      <button
                        key={answer.canonical_key}
                        type="button"
                        className="rounded-md border border-border bg-muted/30 p-2 text-left text-xs"
                        onClick={() => setAnswerDraft(answer)}
                      >
                        <span className="font-medium text-foreground">{answer.canonical_key}</span>
                        <span className="mt-1 block line-clamp-2 text-muted-foreground">{answer.value}</span>
                        <span className="mt-1 block text-muted-foreground">
                          {(answer.status ?? "approved").replaceAll("_", " ")} - {answer.source}
                        </span>
                        {answer.requires_confirmation ? (
                          <span className="mt-1 block text-warning-foreground">review required</span>
                        ) : null}
                      </button>
                    ))
                  )}
                </div>
              </section>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Resume variants</CardTitle>
          <CardDescription className="text-xs">
            Track tailored CV versions and where they are used by applications.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <Input value={resumeDraft.label} placeholder="Variant label" onChange={(event) => setResumeDraft((current) => ({ ...current, label: event.target.value }))} />
            <Input value={resumeDraft.file_ref} placeholder="File reference" onChange={(event) => setResumeDraft((current) => ({ ...current, file_ref: event.target.value }))} />
            <Input value={resumeDraft.base_version} placeholder="Base version" onChange={(event) => setResumeDraft((current) => ({ ...current, base_version: event.target.value }))} />
            <Input value={resumeDraft.diff_summary} placeholder="Diff summary" onChange={(event) => setResumeDraft((current) => ({ ...current, diff_summary: event.target.value }))} />
          </div>
          <AsyncActionButton
            pending={Boolean(pendingActions["resume:save"])}
            pendingLabel="Guardando versión…"
            onClick={() => void createResumeVariant()}
            disabled={!resumeDraft.label.trim()}
          >
            <Plus data-icon="inline-start" />
            Agregar versión
          </AsyncActionButton>
          <div className="flex flex-col gap-2">
            {resumes.length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                Generated or manually added resume variants appear here.
              </p>
            ) : (
              resumes.map((resume) => (
                <div key={resume.id} className="rounded-lg border border-border p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-foreground">{resume.label}</p>
                    <span className="text-muted-foreground">{new Date(resume.created_at).toLocaleDateString()}</span>
                  </div>
                  <p className="mt-1 text-muted-foreground">{resume.diff_summary || "No diff summary recorded."}</p>
                  {resume.file_ref ? <p className="mt-1 font-mono text-[11px] text-muted-foreground">{resume.file_ref}</p> : null}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
      </div>
    </div>
  )
}
