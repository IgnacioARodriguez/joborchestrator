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
import { api } from "@/lib/api"
import type {
  ApplicationTarget,
  AnswerDefinition,
  AnswerSensitivity,
  CandidateProfile,
  OperationRun,
  ProfileSkill,
  ResumeVariant,
  SkillCatalogItem,
  SkillLevel,
  WorkMode,
} from "@/lib/types"

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

export function ProfileScreen() {
  const [profile, setProfile] = useState<CandidateProfile>(EMPTY_PROFILE)
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [busy, setBusy] = useState<"load" | "cv" | "save" | null>("load")
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
        if (
          !cancelled &&
          latest.operation &&
          ["queued", "running"].includes(latest.operation.status)
        ) {
          setOperation(latest.operation)
        }
      } catch (e) {
        toast.error("Could not load profile", {
          description: e instanceof Error ? e.message : "Backend request failed.",
        })
      } finally {
        if (!cancelled) setBusy(null)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

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
            toast.success("Profile ready", {
              description: "The local worker finished reading your CV.",
            })
          }
          return
        }
        if (response.operation.status === "failed") {
          toast.error("CV analysis failed", {
            description: response.operation.error ?? "Check local worker logs.",
          })
          return
        }
        timer = window.setTimeout(poll, 2500)
      } catch (e) {
        if (!stopped) {
          toast.error("Could not check operation", {
            description: e instanceof Error ? e.message : "Backend request failed.",
          })
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

  function patch(update: Partial<CandidateProfile>) {
    setProfile((current) => ({ ...current, ...update }))
  }

  async function persistProfile(nextProfile: CandidateProfile, successMessage?: string) {
    setProfile(nextProfile)
    setBusy("save")
    try {
      const response = await api.saveProfile(nextProfile)
      setProfile(response.profile)
      if (successMessage) {
        toast.success(successMessage, {
          description: "Profile changes are saved.",
        })
      }
    } catch (e) {
      toast.error("Could not save profile", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function updateSkill(index: number, update: Partial<ProfileSkill>) {
    const nextProfile = {
      ...profile,
      skills: profile.skills.map((skill, i) =>
        i === index ? { ...skill, ...update } : skill,
      ),
    }
    await persistProfile(nextProfile)
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
    await persistProfile(nextProfile, `${skill.name} added`)
  }

  async function addCustomCatalogSkill() {
    const name = newCatalogSkill.trim()
    const category = newCatalogCategory.trim() || "General"
    if (!name) return
    try {
      const response = await api.addSkillCatalogItem({ category, name })
      setSkillCatalog(response.skills)
      setNewCatalogSkill("")
      await addSkill({ name: response.skill.name, category: response.skill.category })
    } catch (e) {
      toast.error("Could not add skill", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    }
  }

  async function removeSkill(index: number) {
    const skillName = profile.skills[index]?.name ?? "Skill"
    const nextProfile = {
      ...profile,
      skills: profile.skills.filter((_, i) => i !== index),
    }
    await persistProfile(nextProfile, `${skillName} removed`)
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
    await persistProfile(nextProfile, `${role} added`)
  }

  async function removeRole(field: "target_roles" | "secondary_roles", role: string) {
    const aliases = { ...(profile.role_aliases ?? {}) }
    delete aliases[role]
    const nextProfile = {
      ...profile,
      [field]: profile[field].filter((item) => item !== role),
      role_aliases: aliases,
    }
    await persistProfile(nextProfile, `${role} removed`)
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
    await persistProfile(nextProfile, `${alias} added`)
  }

  async function removeRoleAlias(role: string, alias: string) {
    const nextProfile = {
      ...profile,
      role_aliases: {
        ...(profile.role_aliases ?? {}),
        [role]: (profile.role_aliases?.[role] ?? []).filter((item) => item !== alias),
      },
    }
    await persistProfile(nextProfile, `${alias} removed`)
  }

  async function importCv() {
    if (!cvFile) return
    setBusy("cv")
    try {
      const response = await api.importProfileCv(cvFile)
      const op = await api.getOperation(response.operation_id)
      setOperation(op.operation)
      setCvFile(null)
      toast.success("CV queued", {
        description: "Keep the local worker running on your PC.",
      })
    } catch (e) {
      toast.error("Could not analyze CV", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function saveProfile() {
    setBusy("save")
    try {
      const response = await api.saveProfile(profile)
      setProfile(response.profile)
      toast.success("Profile saved", {
        description: "Future rankings will use this profile.",
      })
    } catch (e) {
      toast.error("Could not save profile", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    } finally {
      setBusy(null)
    }
  }

  async function saveAnswerDraft() {
    const canonical_key = answerDraft.canonical_key.trim()
    if (!canonical_key) return
    try {
      const payload = {
        ...answerDraft,
        canonical_key,
        question_patterns: answerDraft.question_patterns.filter(Boolean),
        requires_confirmation:
          answerDraft.requires_confirmation || answerDraft.sensitivity !== "public",
      }
      const response = await api.saveAnswer(payload)
      setAnswers((current) => {
        const others = current.filter((answer) => answer.canonical_key !== response.answer.canonical_key)
        return [...others, response.answer].sort((a, b) => a.canonical_key.localeCompare(b.canonical_key))
      })
      setAnswerDraft(EMPTY_ANSWER)
      toast.success("Answer saved", { description: canonical_key })
    } catch (e) {
      toast.error("Could not save answer", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
    }
  }

  async function createResumeVariant() {
    const label = resumeDraft.label.trim()
    if (!label) return
    try {
      const response = await api.createResume({
        label,
        file_ref: resumeDraft.file_ref || null,
        base_version: resumeDraft.base_version || null,
        diff_summary: resumeDraft.diff_summary || null,
      })
      setResumes((current) => [response.resume, ...current])
      setResumeDraft({ label: "", file_ref: "", base_version: "", diff_summary: "" })
      toast.success("Resume variant saved", { description: label })
    } catch (e) {
      toast.error("Could not save resume variant", {
        description: e instanceof Error ? e.message : "Backend request failed.",
      })
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
        eyebrow="Profile"
        title="Candidate profile"
        description="Roles, geography, skills, and ranking context."
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {busy && (
        <Card className="border-primary/20 bg-primary/5 xl:col-span-2">
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <LoaderCircle className="size-5 animate-spin" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {busy === "cv"
                  ? "Queueing CV analysis"
                  : busy === "save"
                    ? "Saving profile"
                    : "Loading profile"}
              </p>
              <p className="text-xs text-muted-foreground">
                {busy === "cv"
                  ? "Preparing your CV text for the local worker."
                  : "Keeping your ranking profile in sync."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {operation && ["queued", "running", "failed"].includes(operation.status) && (
        <Card className="border-primary/20 bg-primary/5 xl:col-span-2">
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              {operation.status === "failed" ? (
                <span className="text-sm font-semibold">!</span>
              ) : (
                <LoaderCircle className="size-5 animate-spin" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">
                {operation.status === "queued"
                  ? "Waiting for local worker"
                  : operation.status === "running"
                    ? "Local worker is analyzing your CV"
                    : "CV analysis failed"}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {operation.status === "failed"
                  ? operation.error || "Check logs/worker.log on your PC."
                  : operation.progress_message ||
                    "Start run_worker.bat on your PC to process this task."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

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
            onChange={(event) => setCvFile(event.target.files?.[0] ?? null)}
          />
          <Button disabled={!cvFile || busy !== null} onClick={() => void importCv()}>
            {busy === "cv" ? <LoadingIcon /> : <Sparkles data-icon="inline-start" />}
            {busy === "cv" ? "Queueing CV" : "Analyze CV"}
          </Button>
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
              <Button size="icon" variant="outline" onClick={() => void addRole("target_roles", newTargetRole)}>
                <Plus className="size-4" />
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
              <Button size="icon" variant="outline" onClick={() => void addRole("secondary_roles", newSecondaryRole)}>
                <Plus className="size-4" />
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
                      aria-label={`Remove ${role}`}
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => void removeRole(field, role)}
                    >
                      <X className="size-3.5" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {(profile.role_aliases?.[role] ?? []).map((alias) => (
                      <Badge key={alias} variant="outline">
                        {alias}
                        <button
                          className="ml-1 text-muted-foreground hover:text-foreground"
                          onClick={() => void removeRoleAlias(role, alias)}
                          type="button"
                        >
                          <X className="size-3" />
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
                    <Button size="icon" variant="outline" onClick={() => void addRoleAlias(role)}>
                      <Plus className="size-4" />
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
          <Button disabled={busy !== null} onClick={() => void saveProfile()}>
            {busy === "save" ? <LoadingIcon /> : <Save data-icon="inline-start" />}
            {busy === "save" ? "Saving profile" : "Save profile"}
          </Button>
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
            <Button disabled={busy !== null} onClick={() => void saveProfile()}>
              {busy === "save" ? <LoadingIcon /> : <Save data-icon="inline-start" />}
              Save geography
            </Button>
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
                          onValueChange={(value) =>
                            void updateSkill(index, { level: value as SkillLevel })
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
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
                          aria-label={`Remove ${skill.name}`}
                          size="icon-sm"
                          variant="ghost"
                          onClick={() => void removeSkill(index)}
                        >
                          <X className="size-3.5" />
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
                <Button
                  variant="outline"
                  disabled={!newCatalogSkill.trim()}
                  onClick={() => void addCustomCatalogSkill()}
                >
                  <Plus data-icon="inline-start" />
                  Add
                </Button>
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
                          onClick={() => void addSkill(skill)}
                        >
                          <Plus className="size-3" data-icon="inline-start" />
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
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_10rem]">
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
            <Button onClick={() => void saveAnswerDraft()} disabled={!answerDraft.canonical_key.trim()}>
              <Save data-icon="inline-start" />
              Save answer
            </Button>
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
          <Button onClick={() => void createResumeVariant()} disabled={!resumeDraft.label.trim()}>
            <Plus data-icon="inline-start" />
            Add variant
          </Button>
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
