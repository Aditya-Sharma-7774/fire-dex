/**
 * Runs an analysis and streams its progress.
 *
 * Uses fetch with a ReadableStream rather than EventSource, because
 * EventSource cannot send a POST body and our request carries parameters.
 * The wire format is still server-sent events.
 *
 * The analysis takes 30-90 seconds against a local model. Without streaming
 * the interface would sit frozen and look broken; with it, the user watches
 * the architecture work, which is the most convincing thing this project
 * can show.
 */

import { useCallback, useRef, useState } from 'react'

import { API_BASE_URL } from '../../services/api'
import type { Suggestion } from './SuggestionPanel'

export type AgentPhase = 'waiting' | 'running' | 'completed' | 'failed' | 'skipped'

export interface AgentProgress {
  name: string
  status: AgentPhase
  durationMs?: number
  observations?: number
  interpretations?: number
  tokens?: number
  errors?: string[]
}

export interface ReviewerOutcome {
  verdict: string
  score: number
  computed_score: number
  model_penalty: number
  confidence: number
  evidence_coverage: number
  citation_validity: number
  agent_agreement: number
  data_freshness_ok: boolean
  concerns: string[]
  strengths: string[]
  unsupported_claims: string[]
  reasoning: string
}

export interface AnalysisState {
  running: boolean
  error: string | null
  subject: string | null
  evidenceCount: number | null
  evidenceFailures: string[]
  dataStale: boolean
  model: { model: string; provider: string; mode: string; fallbackReady?: boolean } | null
  /** Every automatic failover, so a switch is never invisible. */
  providerSwitches: {
    at: string
    from_provider: string
    from_model: string
    to_provider: string
    to_model: string
    reason: string
  }[]
  agents: AgentProgress[]
  reanalysisReason: string | null
  summary: string | null
  reviewer: ReviewerOutcome | null
  suggestion: Suggestion | null
  /** Signal and groundedness arrive before the explanation, so the UI can
   *  show them the moment they are computed. */
  liveSignal: { signal: string | null; score: number | null; groundedness: number } | null
  conflicts: string[]
  resultId: string | null
  hash: string | null
  metrics: Record<string, unknown> | null
  durationMs: number | null
}

const INITIAL: AnalysisState = {
  running: false,
  error: null,
  subject: null,
  evidenceCount: null,
  evidenceFailures: [],
  dataStale: false,
  model: null,
  providerSwitches: [],
  agents: [],
  reanalysisReason: null,
  summary: null,
  reviewer: null,
  suggestion: null,
  liveSignal: null,
  conflicts: [],
  resultId: null,
  hash: null,
  metrics: null,
  durationMs: null,
}

export interface AnalysisRequest {
  symbol?: string
  chain?: string
  address?: string
  interval?: string
  prefer?: 'local' | 'online'
  query?: string
}

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL)
  const abortRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    setState((prev) => ({ ...prev, running: false }))
  }, [])

  const run = useCallback(async (request: AnalysisRequest) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState({ ...INITIAL, running: true })

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/analysis/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: controller.signal,
      })

      if (!response.ok || !response.body) {
        throw new Error(`Analysis request failed (${response.status})`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line. A frame can arrive
        // split across chunks, so we only consume complete ones.
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          try {
            applyEvent(JSON.parse(line.slice(5).trim()), setState)
          } catch {
            /* a malformed frame must not kill the stream */
          }
        }
      }

      setState((prev) => ({ ...prev, running: false }))
    } catch (error) {
      if (controller.signal.aborted) return
      setState((prev) => ({
        ...prev,
        running: false,
        error: error instanceof Error ? error.message : 'Analysis failed',
      }))
    }
  }, [])

  return { ...state, run, cancel }
}

type Setter = React.Dispatch<React.SetStateAction<AnalysisState>>

function upsertAgent(agents: AgentProgress[], next: AgentProgress): AgentProgress[] {
  const index = agents.findIndex((a) => a.name === next.name)
  if (index === -1) return [...agents, next]
  const copy = [...agents]
  copy[index] = { ...copy[index], ...next }
  return copy
}

function applyEvent(event: Record<string, unknown>, setState: Setter) {
  const type = event.type as string

  switch (type) {
    case 'evidence':
      setState((prev) => ({
        ...prev,
        subject: (event.subject as string) ?? null,
        evidenceCount: (event.count as number) ?? null,
        evidenceFailures: (event.failures as string[]) ?? [],
        dataStale: Boolean(event.stale),
      }))
      break

    case 'model':
      setState((prev) => ({
        ...prev,
        model: {
          model: event.model as string,
          provider: event.provider as string,
          mode: event.mode as string,
          fallbackReady: Boolean(event.fallback_ready),
        },
      }))
      break

    case 'plan':
      // Seed the grid so every planned agent is visible as "waiting"
      // before it starts. Showing the plan up front is what makes the
      // pipeline legible rather than a series of surprises.
      setState((prev) => ({
        ...prev,
        agents: (event.agents as string[]).map((name) => ({
          name,
          status: 'waiting' as AgentPhase,
        })),
      }))
      break

    case 'agent_status':
      setState((prev) => ({
        ...prev,
        agents: upsertAgent(prev.agents, {
          name: event.agent as string,
          status: (event.status as AgentPhase) ?? 'waiting',
          durationMs: event.duration_ms as number | undefined,
          observations: event.observations as number | undefined,
          interpretations: event.interpretations as number | undefined,
          tokens: event.tokens as number | undefined,
          errors: (event.errors as string[]) ?? undefined,
        }),
      }))
      break

    case 'provider_switch':
      setState((prev) => ({
        ...prev,
        providerSwitches: [
          ...prev.providerSwitches,
          event as unknown as AnalysisState['providerSwitches'][number],
        ],
        // The model in use has genuinely changed, so the header must
        // follow it rather than keep showing the one we started with.
        model: {
          model: event.to_model as string,
          provider: event.to_provider as string,
          mode: (event.to_provider as string) === 'ollama' ? 'local' : 'online',
          fallbackReady: false,
        },
      }))
      break

    case 'signal':
      setState((prev) => ({
        ...prev,
        liveSignal: {
          signal: (event.signal as string) ?? null,
          score: (event.score as number) ?? null,
          groundedness: (event.groundedness as number) ?? 0,
        },
      }))
      break

    case 'reanalysis':
      setState((prev) => ({ ...prev, reanalysisReason: event.reason as string }))
      break

    case 'audit':
      setState((prev) => ({
        ...prev,
        resultId: event.result_id as string,
        hash: event.hash as string,
        metrics: event.metrics as Record<string, unknown>,
      }))
      break

    case 'complete':
      setState((prev) => ({
        ...prev,
        running: false,
        summary: event.summary as string,
        reviewer: event.reviewer as unknown as ReviewerOutcome,
        suggestion: (event.suggestion as unknown as Suggestion) ?? null,
        conflicts: (event.conflicts as string[]) ?? [],
        resultId: event.result_id as string,
        hash: event.hash as string,
        durationMs: event.duration_ms as number,
      }))
      break

    case 'error':
      setState((prev) => ({
        ...prev,
        running: false,
        error: [event.message, event.detail].filter(Boolean).join(' — '),
      }))
      break
  }
}
