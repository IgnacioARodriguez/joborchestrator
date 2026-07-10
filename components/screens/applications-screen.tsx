"use client"

import { useEffect, useMemo, useState } from "react"
import { Building2, Inbox, Plus, Send } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { PageHeader } from "@/components/page-chrome"
import { useStore } from "@/lib/store"
import { api } from "@/lib/api"
import type { ApplicationRecord, ApplicationStatus, FollowUp, JobContact } from "@/lib/types"
import { cn } from "@/lib/utils"

const APPLICATION_COLUMNS: ApplicationStatus[] = [
  "preparing",
  "submitted",
  "recruiter_screen",
  "interview",
  "technical",
  "offer",
  "rejected",
  "withdrawn",
]

const LABELS: Record<ApplicationStatus, string> = {
  preparing: "Preparing",
  submitted: "Submitted",
  recruiter_screen: "Recruiter screen",
  interview: "Interview",
  technical: "Technical",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
}

function ApplicationCard({ application }: { application: ApplicationRecord }) {
  const { setApplicationStatus } = useStore()
  return (
    <article className="rounded-lg border border-border bg-card p-3 shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
      <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
        {application.job_title || `Application ${application.id}`}
      </h3>
      <p className="mt-1 flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        <Building2 className="size-3.5 shrink-0" />
        <span className="truncate">{application.company || "Unknown company"}</span>
      </p>
      <p className="mt-1 text-[11px] uppercase text-muted-foreground/80">{application.channel.replace("_", " ")}</p>
      <div className="mt-3 flex flex-wrap gap-1">
        {APPLICATION_COLUMNS.filter((status) => status !== application.status).map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => {
              setApplicationStatus(application.id, status)
              toast.success(`Moved to ${LABELS[status]}`, { description: application.job_title || undefined })
            }}
            className="rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {LABELS[status]}
          </button>
        ))}
      </div>
    </article>
  )
}

export function ApplicationsScreen() {
  const { applications } = useStore()
  const [contacts, setContacts] = useState<JobContact[]>([])
  const [followUps, setFollowUps] = useState<FollowUp[]>([])
  const [contactDraft, setContactDraft] = useState({ company: "", name: "", role: "", linkedin_url: "" })
  const [followUpDraft, setFollowUpDraft] = useState({ application_id: "", due_at: "", note: "" })
  const [suggestion, setSuggestion] = useState("")

  useEffect(() => {
    let cancelled = false
    async function loadCrm() {
      try {
        const [contactData, followUpData] = await Promise.all([api.getContacts(), api.getFollowUps()])
        if (!cancelled) {
          setContacts(contactData.contacts)
          setFollowUps(followUpData.follow_ups)
        }
      } catch {
        // The kanban remains useful if CRM data is temporarily unavailable.
      }
    }
    void loadCrm()
    return () => {
      cancelled = true
    }
  }, [])

  const byStatus = (status: ApplicationStatus) =>
    applications
      .filter((application) => application.status === status)
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())

  const contactsByCompany = useMemo(() => {
    const groups = new Map<string, JobContact[]>()
    for (const contact of contacts) {
      const company = contact.company || "Unknown company"
      groups.set(company, [...(groups.get(company) ?? []), contact])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [contacts])

  async function createContact() {
    if (!contactDraft.name.trim()) return
    try {
      const response = await api.createContact({
        ...contactDraft,
        source: "manual",
        contacted_at: new Date().toISOString(),
      })
      setContacts((current) => [response.contact, ...current])
      setContactDraft({ company: "", name: "", role: "", linkedin_url: "" })
      toast.success("Contact recorded", { description: response.contact.name || undefined })
    } catch (e) {
      toast.error("Could not save contact", { description: e instanceof Error ? e.message : "Backend request failed." })
    }
  }

  async function createFollowUp() {
    const application_id = Number(followUpDraft.application_id)
    if (!application_id || !followUpDraft.due_at) return
    try {
      const response = await api.createFollowUp({
        application_id,
        due_at: followUpDraft.due_at,
        note: followUpDraft.note,
      })
      setFollowUps((current) => [response.follow_up, ...current])
      setFollowUpDraft({ application_id: "", due_at: "", note: "" })
      toast.success("Follow-up recorded")
    } catch (e) {
      toast.error("Could not save follow-up", { description: e instanceof Error ? e.message : "Backend request failed." })
    }
  }

  function suggestFollowUp(followUp: FollowUp) {
    const application = applications.find((item) => item.id === followUp.application_id)
    const company = application?.company || "your team"
    setSuggestion(
      `Hi ${company} team,\n\nI wanted to follow up on my application for ${application?.job_title || "the role"}. I'm still interested and would be happy to share any additional context that helps with the process.\n\nBest,\nIgnacio`,
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        eyebrow="Applications"
        title="Application kanban"
        description="Only real applications live here, separate from discovered opportunities."
      />
      <div className="min-h-[420px] overflow-x-auto pb-2">
        <div className="grid min-w-[1320px] grid-cols-8 gap-3">
          {APPLICATION_COLUMNS.map((status) => {
            const items = byStatus(status)
            return (
              <section
                key={status}
                className={cn("flex h-[calc(100dvh-190px)] min-h-[420px] flex-col rounded-lg border border-border bg-muted/25", (status === "rejected" || status === "withdrawn") && "opacity-90")}
              >
                <div className="shrink-0 border-b border-border bg-card px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold text-foreground">{LABELS[status]}</h2>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">{items.length}</span>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
                  {items.length === 0 ? (
                    <Empty className="h-full border border-dashed bg-background/70">
                      <EmptyHeader>
                        <EmptyMedia variant="icon"><Inbox /></EmptyMedia>
                        <EmptyTitle>Empty lane</EmptyTitle>
                        <EmptyDescription>{LABELS[status]} applications appear here.</EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {items.map((application) => <ApplicationCard key={application.id} application={application} />)}
                    </div>
                  )}
                </div>
              </section>
            )
          })}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Contacts</CardTitle>
            <CardDescription className="text-xs">Recruiter CRM grouped by company.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <Input placeholder="Company" value={contactDraft.company} onChange={(event) => setContactDraft((current) => ({ ...current, company: event.target.value }))} />
              <Input placeholder="Name" value={contactDraft.name} onChange={(event) => setContactDraft((current) => ({ ...current, name: event.target.value }))} />
              <Input placeholder="Role" value={contactDraft.role} onChange={(event) => setContactDraft((current) => ({ ...current, role: event.target.value }))} />
              <Input placeholder="LinkedIn URL" value={contactDraft.linkedin_url} onChange={(event) => setContactDraft((current) => ({ ...current, linkedin_url: event.target.value }))} />
            </div>
            <Button onClick={() => void createContact()} disabled={!contactDraft.name.trim()}>
              <Plus data-icon="inline-start" />
              Add contact
            </Button>
            <div className="flex max-h-80 flex-col gap-2 overflow-y-auto">
              {contactsByCompany.map(([company, items]) => (
                <div key={company} className="rounded-lg border border-border p-3">
                  <p className="text-xs font-semibold text-foreground">{company}</p>
                  {items.map((contact) => (
                    <p key={contact.id} className="mt-1 text-xs text-muted-foreground">
                      {contact.name} {contact.role ? `- ${contact.role}` : ""} {contact.last_reply_at ? "- replied" : ""}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Follow-ups</CardTitle>
            <CardDescription className="text-xs">Suggested text only; nothing is sent automatically.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr]">
              <Input placeholder="Application ID" value={followUpDraft.application_id} onChange={(event) => setFollowUpDraft((current) => ({ ...current, application_id: event.target.value }))} />
              <Input type="datetime-local" value={followUpDraft.due_at} onChange={(event) => setFollowUpDraft((current) => ({ ...current, due_at: event.target.value }))} />
            </div>
            <Input placeholder="Note" value={followUpDraft.note} onChange={(event) => setFollowUpDraft((current) => ({ ...current, note: event.target.value }))} />
            <Button onClick={() => void createFollowUp()} disabled={!followUpDraft.application_id || !followUpDraft.due_at}>
              <Plus data-icon="inline-start" />
              Add follow-up
            </Button>
            <div className="flex max-h-52 flex-col gap-2 overflow-y-auto">
              {followUps.map((followUp) => (
                <button key={followUp.id} type="button" onClick={() => suggestFollowUp(followUp)} className="rounded-lg border border-border p-3 text-left text-xs hover:bg-muted/40">
                  <span className="font-medium text-foreground">Application #{followUp.application_id}</span>
                  <span className="ml-2 text-muted-foreground">{followUp.due_at}</span>
                  <span className="mt-1 block text-muted-foreground">{followUp.note}</span>
                </button>
              ))}
            </div>
            {suggestion ? (
              <div className="rounded-lg border border-border bg-muted/30 p-3">
                <p className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground"><Send className="size-3.5" /> Suggested follow-up</p>
                <Textarea readOnly value={suggestion} className="min-h-32 text-xs" />
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
