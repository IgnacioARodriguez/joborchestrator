"use client"

import { useEffect, useMemo, useState } from "react"
import {
  BriefcaseBusiness,
  LoaderCircle,
  Save,
  Sparkles,
  Upload,
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
import { api } from "@/lib/api"
import type { CandidateProfile, ProfileSkill, SkillLevel } from "@/lib/types"

const EMPTY_PROFILE: CandidateProfile = {
  schema_version: 1,
  headline: "",
  target_roles: [],
  secondary_roles: [],
  skills: [],
  industries: [],
  preferred_locations: [],
  preferred_work_modes: [],
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

export function ProfileScreen() {
  const [profile, setProfile] = useState<CandidateProfile>(EMPTY_PROFILE)
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [busy, setBusy] = useState<"load" | "cv" | "save" | null>("load")

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const response = await api.getProfile()
        if (!cancelled && response.profile) setProfile(response.profile)
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

  const groupedSkills = useMemo(() => {
    const groups = new Map<string, ProfileSkill[]>()
    for (const skill of profile.skills) {
      const category = skill.category || "General"
      groups.set(category, [...(groups.get(category) ?? []), skill])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [profile.skills])

  function patch(update: Partial<CandidateProfile>) {
    setProfile((current) => ({ ...current, ...update }))
  }

  function updateSkill(index: number, update: Partial<ProfileSkill>) {
    setProfile((current) => ({
      ...current,
      skills: current.skills.map((skill, i) =>
        i === index ? { ...skill, ...update } : skill,
      ),
    }))
  }

  async function importCv() {
    if (!cvFile) return
    setBusy("cv")
    try {
      const response = await api.importProfileCv(cvFile)
      setProfile(response.profile)
      setCvFile(null)
      toast.success("CV analyzed", {
        description: `${response.profile.skills.length} skills detected.`,
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

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      {busy && (
        <Card className="border-primary/20 bg-primary/5 xl:col-span-2">
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <LoaderCircle className="size-5 animate-spin" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {busy === "cv"
                  ? "Reading your CV with AI"
                  : busy === "save"
                    ? "Saving profile"
                    : "Loading profile"}
              </p>
              <p className="text-xs text-muted-foreground">
                {busy === "cv"
                  ? "Extracting roles, skills, categories, and evidence."
                  : "Keeping your ranking profile in sync."}
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
            Upload a CV and let AI build an editable ranking profile.
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
            {busy === "cv" ? "Analyzing CV" : "Analyze CV"}
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
            AI suggestions based on the CV. Edit them to steer ranking.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-1.5">
            {profile.target_roles.map((role) => (
              <Badge key={role}>{role}</Badge>
            ))}
            {profile.secondary_roles.map((role) => (
              <Badge key={role} variant="secondary">
                {role}
              </Badge>
            ))}
          </div>
          {profile.suggested_roles_reasoning && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {profile.suggested_roles_reasoning}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Profile basics</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Input
            value={profile.headline}
            placeholder="Professional headline"
            onChange={(event) => patch({ headline: event.target.value })}
          />
          <Input
            type="number"
            min="0"
            step="0.5"
            value={profile.real_experience_years}
            onChange={(event) =>
              patch({ real_experience_years: Number(event.target.value) || 0 })
            }
          />
          <Textarea
            value={lines(profile.target_roles)}
            onChange={(event) => patch({ target_roles: listFromText(event.target.value) })}
            placeholder="Target roles, one per line"
            className="min-h-24 text-xs"
          />
          <Textarea
            value={lines(profile.secondary_roles)}
            onChange={(event) =>
              patch({ secondary_roles: listFromText(event.target.value) })
            }
            placeholder="Secondary roles, one per line"
            className="min-h-24 text-xs"
          />
          <Textarea
            value={profile.notes}
            onChange={(event) => patch({ notes: event.target.value })}
            placeholder="Notes for the ranker"
            className="min-h-24 text-xs"
          />
          <Button disabled={busy !== null} onClick={() => void saveProfile()}>
            {busy === "save" ? <LoadingIcon /> : <Save data-icon="inline-start" />}
            {busy === "save" ? "Saving profile" : "Save profile"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Skills</CardTitle>
          <CardDescription className="text-xs">
            Edit each detected skill level. Strong skills carry the most ranking weight.
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
                        className="grid grid-cols-1 gap-2 rounded-lg border border-border p-2 text-xs md:grid-cols-[1fr_8rem]"
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
                            updateSkill(index, { level: value as SkillLevel })
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
                      </div>
                    )
                  })}
                </div>
              </section>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
