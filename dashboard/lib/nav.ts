import {
  LayoutDashboard,
  ListOrdered,
  KanbanSquare,
  Wrench,
  type LucideIcon,
} from "lucide-react"

export type Section = "dashboard" | "ranking" | "pipeline" | "ops"

export interface NavItem {
  id: Section
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "ranking", label: "Ranking", icon: ListOrdered },
  { id: "pipeline", label: "Pipeline", icon: KanbanSquare },
  { id: "ops", label: "Ops", icon: Wrench },
]
