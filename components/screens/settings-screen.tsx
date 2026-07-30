"use client"

import { Activity, ChartNoAxesCombined, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { PageHeader } from "@/components/page-chrome"
import type { Section } from "@/lib/nav"

const SETTINGS_LINKS: Array<{
  title: string
  description: string
  action: string
  section: Section
  icon: typeof UserRound
}> = [
  {
    title: "Perfil",
    description: "Datos del candidato, roles objetivo, habilidades y preferencias.",
    action: "Abrir perfil",
    section: "profile",
    icon: UserRound,
  },
  {
    title: "Automatización y fuentes",
    description: "Cuentas, fuentes, workers, scans y diagnóstico operativo.",
    action: "Abrir configuración",
    section: "automations",
    icon: Activity,
  },
  {
    title: "Insights",
    description: "Lecturas y métricas avanzadas fuera del flujo principal.",
    action: "Abrir insights",
    section: "insights",
    icon: ChartNoAxesCombined,
  },
]

export function SettingsScreen({ onNavigate }: { onNavigate: (section: Section) => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Configuración"
        description="Perfil, preferencias, fuentes y diagnóstico operativo."
      />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {SETTINGS_LINKS.map((item) => {
          const Icon = item.icon
          return (
            <Card key={item.section} className="gap-3">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Icon className="size-4 text-primary" />
                  {item.title}
                </CardTitle>
                <CardDescription className="text-xs">{item.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button variant="outline" onClick={() => onNavigate(item.section)}>
                  {item.action}
                </Button>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
