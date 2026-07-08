import {
  LayoutDashboard,
  ListOrdered,
  KanbanSquare,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react"

export type Section = "dashboard" | "ranking" | "pipeline" | "profile" | "ops"

export interface NavItem {
  id: Section
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "ranking", label: "Ranking", icon: ListOrdered },
  { id: "pipeline", label: "Pipeline", icon: KanbanSquare },
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "ops", label: "Ops", icon: Wrench },
]
