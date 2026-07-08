import { AppShell } from "@/components/app-shell"
import { StoreProvider } from "@/lib/store"

export default function Page() {
  return (
    <StoreProvider>
      <AppShell />
    </StoreProvider>
  )
}
