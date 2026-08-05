"use client"

import { useCallback, useEffect, useRef } from "react"
import { api } from "./api"
import type { SyncResource, SyncStatus } from "./types"
import { useVisiblePolling } from "./use-visible-polling"

const SYNC_RESOURCES: SyncResource[] = [
  "jobs",
  "applications",
  "sessions",
  "operations",
]

export interface SyncRevisionCheck {
  current: SyncStatus
  previous: SyncStatus | null
  changedResources: SyncResource[]
}

interface SyncRevisionsOptions {
  intervalMs?: number
  onStatus: (check: SyncRevisionCheck) => Promise<void> | void
}

export function getChangedSyncResources(
  previous: SyncStatus | null,
  current: SyncStatus,
): SyncResource[] {
  if (!previous) return []
  return SYNC_RESOURCES.filter(
    (resource) =>
      previous.resources[resource].revision !==
      current.resources[resource].revision,
  )
}

export function useSyncRevisions({
  intervalMs = 5000,
  onStatus,
}: SyncRevisionsOptions) {
  const previousRef = useRef<SyncStatus | null>(null)
  const onStatusRef = useRef(onStatus)
  const inFlightRef = useRef<Promise<SyncRevisionCheck> | null>(null)

  useEffect(() => {
    onStatusRef.current = onStatus
  }, [onStatus])

  const checkNow = useCallback((): Promise<SyncRevisionCheck> => {
    if (inFlightRef.current) return inFlightRef.current

    const request = (async () => {
      const current = await api.getSyncStatus()
      const previous = previousRef.current
      const check = {
        current,
        previous,
        changedResources: getChangedSyncResources(previous, current),
      }

      await onStatusRef.current(check)
      previousRef.current = current
      return check
    })().finally(() => {
      if (inFlightRef.current === request) inFlightRef.current = null
    })

    inFlightRef.current = request
    return request
  }, [])

  useVisiblePolling({
    intervalMs,
    poll: async () => {
      await checkNow()
    },
  })

  return checkNow
}
