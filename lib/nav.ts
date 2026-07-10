import {
  CalendarCheck,
  ChartNoAxesCombined,
  ClipboardList,
  KanbanSquare,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react"

export type Section = "today" | "review" | "applications" | "profile" | "automations" | "insights"

export interface NavItem {
  id: Section
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: NavItem[] = [
  { id: "today", label: "Today", icon: CalendarCheck },
  { id: "review", label: "Review", icon: ClipboardList },
  { id: "applications", label: "Applications", icon: KanbanSquare },
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "automations", label: "Automations", icon: Wrench },
  { id: "insights", label: "Insights", icon: ChartNoAxesCombined },
]
