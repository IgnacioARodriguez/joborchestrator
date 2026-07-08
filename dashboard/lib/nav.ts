import {
  LayoutDashboard,
  ListOrdered,
  ClipboardCheck,
  KanbanSquare,
  Wrench,
  type LucideIcon,
} from "lucide-react"

export type Section = "dashboard" | "ranking" | "review" | "pipeline" | "ops"

export interface NavItem {
  id: Section
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "ranking", label: "Ranking", icon: ListOrdered },
  { id: "review", label: "Needs Review", icon: ClipboardCheck },
  { id: "pipeline", label: "Pipeline", icon: KanbanSquare },
  { id: "ops", label: "Ops", icon: Wrench },
]
