"use client"

import { useEffect, useRef } from "react"

export type PollingDecision = "continue" | "stop"

interface VisiblePollingOptions {
  enabled?: boolean
  initialDelayMs?: number
  intervalMs: number
  errorIntervalMs?: number
  poll: () => Promise<PollingDecision | void>
  onError?: (error: unknown) => PollingDecision | void
}

export function useVisiblePolling({
  enabled = true,
  initialDelayMs = 0,
  intervalMs,
  errorIntervalMs = intervalMs,
  poll,
  onError,
}: VisiblePollingOptions) {
  const pollRef = useRef(poll)
  const onErrorRef = useRef(onError)

  useEffect(() => {
    pollRef.current = poll
    onErrorRef.current = onError
  }, [onError, poll])

  useEffect(() => {
    if (!enabled) return

    let stopped = false
    let running = false
    let timer: number | undefined

    function clearTimer() {
      if (timer === undefined) return
      window.clearTimeout(timer)
      timer = undefined
    }

    function schedule(delayMs: number) {
      clearTimer()
      timer = window.setTimeout(() => {
        void run()
      }, delayMs)
    }

    async function run() {
      if (stopped || running || document.visibilityState !== "visible") return

      running = true
      let decision: PollingDecision = "continue"
      let nextDelayMs = intervalMs

      try {
        decision = (await pollRef.current()) ?? "continue"
      } catch (error) {
        nextDelayMs = errorIntervalMs
        decision = onErrorRef.current?.(error) ?? "continue"
      } finally {
        running = false
        if (
          !stopped &&
          decision !== "stop" &&
          document.visibilityState === "visible"
        ) {
          schedule(nextDelayMs)
        }
      }
    }

    function onVisibilityChange() {
      clearTimer()
      if (document.visibilityState === "visible") void run()
    }

    schedule(initialDelayMs)
    document.addEventListener("visibilitychange", onVisibilityChange)

    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [enabled, errorIntervalMs, initialDelayMs, intervalMs])
}
