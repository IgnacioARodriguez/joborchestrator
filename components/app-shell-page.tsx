import { AppShell } from "@/components/app-shell"
import { StoreProvider } from "@/lib/store"
import type { Section } from "@/lib/nav"

export function AppShellPage({ section = "jobs" }: { section?: Section }) {
  return (
    <StoreProvider>
      <AppShell initialSection={section} />
    </StoreProvider>
  )
}
