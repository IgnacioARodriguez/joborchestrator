"use client"

import { Dialog } from "@base-ui/react/dialog"
import { AlertCircle, CheckCircle2, ExternalLink, LoaderCircle, Play, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { getApplicationAssistantState } from "@/lib/application-assistant"
import type { ApplicationSession } from "@/lib/types"

interface ApplicationAssistantDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  session: ApplicationSession | null
  progressMessage?: string | null
  fallbackPortalUrl?: string | null
  busy?: boolean
  onOpenPortal: (url: string | null) => void
  onResume: () => void
  onMarkSubmitted: () => void
}

export function ApplicationAssistantDialog({
  open,
  onOpenChange,
  session,
  progressMessage,
  fallbackPortalUrl,
  busy = false,
  onOpenPortal,
  onResume,
  onMarkSubmitted,
}: ApplicationAssistantDialogProps) {
  const state = getApplicationAssistantState(session, progressMessage)
  const portalUrl = state.portalUrl ?? fallbackPortalUrl ?? null
  const working = state.kind === "progress"

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-[70] bg-black/40 transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Viewport className="fixed inset-0 z-[70] flex items-end justify-center p-3 sm:items-center">
          <Dialog.Popup className="relative w-full max-w-lg rounded-xl border border-border bg-card p-4 shadow-2xl outline-none transition data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 sm:p-5">
            <Dialog.Close
              aria-label="Cerrar"
              className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </Dialog.Close>

            <div className="flex items-start gap-3 pr-8">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                {working ? <LoaderCircle className="size-5 animate-spin" /> : <AlertCircle className="size-5" />}
              </span>
              <div className="min-w-0">
                <Dialog.Title className="text-base font-semibold text-foreground">
                  {state.title}
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {state.description}
                </Dialog.Description>
              </div>
            </div>

            {state.fields.length > 0 ? (
              <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3">
                <p className="text-xs font-semibold text-foreground">Pendiente</p>
                <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {state.fields.map((field) => (
                    <li key={field} className="flex items-start gap-2">
                      <span className="mt-1 size-1.5 shrink-0 rounded-full bg-current" />
                      <span>{field}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {session && !working && state.kind !== "complete" ? (
              <div className="mt-4 flex items-start gap-2 rounded-lg border border-border bg-background p-3 text-xs leading-relaxed text-muted-foreground">
                {state.browserAvailable ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                ) : (
                  <AlertCircle className="mt-0.5 size-4 shrink-0 text-warning" />
                )}
                <span>
                  {state.browserAvailable
                    ? "La sesión automática sigue abierta en el navegador local. No cierres esa ventana."
                    : "No pudimos confirmar una ventana automática visible. Abrí el portal manualmente como respaldo."}
                </span>
              </div>
            ) : null}

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Dialog.Close render={<Button variant="outline" />}>Cerrar</Dialog.Close>
              {!working && state.kind !== "complete" ? (
                <Button variant="outline" onClick={() => onOpenPortal(portalUrl)}>
                  <ExternalLink data-icon="inline-start" />
                  Abrir portal
                </Button>
              ) : null}
              {state.canResume ? (
                <Button disabled={busy} onClick={onResume}>
                  {busy ? <LoaderCircle className="animate-spin" data-icon="inline-start" /> : <Play data-icon="inline-start" />}
                  Ya resolví el paso
                </Button>
              ) : null}
              {state.canMarkSubmitted ? (
                <Button disabled={busy} onClick={onMarkSubmitted}>
                  <CheckCircle2 data-icon="inline-start" />
                  Marcar como enviada
                </Button>
              ) : null}
            </div>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
