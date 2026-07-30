import {
  BriefcaseBusiness,
  KanbanSquare,
  ListChecks,
  Settings,
  type LucideIcon,
} from "lucide-react"

export type Section =
  | "jobs"
  | "apply"
  | "applications"
  | "settings"
  | "profile"
  | "automations"
  | "insights"

export type PrimarySection = "jobs" | "apply" | "applications" | "settings"

export interface NavItem {
  id: PrimarySection
  label: string
  icon: LucideIcon
  href: string
}

export const NAV_ITEMS: NavItem[] = [
  { id: "jobs", label: "Jobs", icon: BriefcaseBusiness, href: "/jobs" },
  { id: "apply", label: "Aplicar", icon: ListChecks, href: "/apply" },
  { id: "applications", label: "Aplicaciones", icon: KanbanSquare, href: "/applications" },
  { id: "settings", label: "Configuración", icon: Settings, href: "/settings" },
]

export const SECTION_PATHS: Record<PrimarySection, string> = {
  jobs: "/jobs",
  apply: "/apply",
  applications: "/applications",
  settings: "/settings",
}

export const LEGACY_SECTION_ALIASES: Record<string, Section> = {
  today: "jobs",
  review: "jobs",
  pipeline: "apply",
  profile: "profile",
  automations: "automations",
  ops: "automations",
  insights: "insights",
}

export function isPrimarySection(section: Section): section is PrimarySection {
  return section === "jobs" || section === "apply" || section === "applications" || section === "settings"
}

export function primarySectionFor(section: Section): PrimarySection {
  if (section === "profile" || section === "automations" || section === "insights") return "settings"
  return isPrimarySection(section) ? section : "jobs"
}
