import { useState } from 'react'

import type { AgentPhase, AgentProgress } from './useAnalysis'

/**
 * Live view of the multi-agent pipeline.
 *
 * This is the most important screen in the project to get right. An
 * analysis takes 30-90 seconds; without this the interface would sit blank
 * and look broken. With it, the audience watches the architecture work --
 * agents starting, finishing, reporting how many observations they made and
 * how many tokens they used.
 *
 * A failed agent is shown as failed, in red, with its error. That is the
 * point: the system reports reduced coverage rather than quietly filling
 * the gap.
 */

const PHASE_STYLES: Record<AgentPhase, { dot: string; text: string; label: string }> = {
  waiting: { dot: 'bg-coal-600', text: 'text-coal-500', label: 'Waiting' },
  running: { dot: 'bg-amber-400 animate-pulse', text: 'text-amber-300', label: 'Running' },
  completed: { dot: 'bg-emerald-400', text: 'text-emerald-400', label: 'Completed' },
  failed: { dot: 'bg-red-500', text: 'text-red-400', label: 'Failed' },
  skipped: { dot: 'bg-coal-600', text: 'text-coal-500', label: 'Skipped' },
}

const AGENT_PURPOSE: Record<string, string> = {
  market_intelligence: 'Price, volume and market structure',
  technical_analysis: 'Interprets computed indicator values',
  risk: 'Explains the computed risk score',
  portfolio: 'Composition and concentration of holdings',
  onchain: 'Network and address-level state',
  reviewer: 'Critiques the analysis; score is mostly computed',
  fire_auditor: 'Records metrics, canonicalises and hashes the result',
}

function prettyName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function AgentGrid({
  agents,
  running,
  reviewerDone,
  auditDone,
}: {
  agents: AgentProgress[]
  running: boolean
  reviewerDone: boolean
  auditDone: boolean
}) {
  if (agents.length === 0 && !running) return null

  // The reviewer and auditor are pipeline stages rather than specialists,
  // so they are shown separately below the agent grid.
  const specialists = agents.filter((a) => a.name !== 'reviewer' && a.name !== 'fire_auditor')
  const reviewer = agents.find((a) => a.name === 'reviewer')

  return (
    <div className="space-y-3">
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {specialists.map((agent) => (
          <AgentCard key={agent.name} agent={agent} />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <StageChip
          label="Orchestrator"
          active={running}
          done={specialists.every((a) => a.status !== 'waiting' && a.status !== 'running')}
        />
        <span className="text-coal-700">→</span>
        <StageChip
          label="Reviewer"
          active={reviewer?.status === 'running'}
          done={reviewerDone}
        />
        <span className="text-coal-700">→</span>
        <StageChip label="Fire Auditor" active={reviewerDone && !auditDone} done={auditDone} />
        <span className="text-coal-700">→</span>
        <StageChip label="SHA-256" active={false} done={auditDone} />
      </div>
    </div>
  )
}

function AgentCard({ agent }: { agent: AgentProgress }) {
  const [open, setOpen] = useState(false)
  const style = PHASE_STYLES[agent.status] ?? PHASE_STYLES.waiting
  const hasDetail = Boolean(
    agent.durationMs || agent.observations !== undefined || agent.errors?.length,
  )

  return (
    <button
      type="button"
      onClick={() => hasDetail && setOpen((v) => !v)}
      disabled={!hasDetail}
      className={`glass w-full p-3.5 text-left transition-all duration-300 ${
        agent.status === 'running'
          ? 'border-amber-500/30 bg-amber-500/[0.04]'
          : agent.status === 'failed'
            ? 'border-red-500/25 bg-red-500/[0.04]'
            : hasDetail
              ? 'hover:border-fire-500/25 hover:bg-white/[0.05]'
              : ''
      } disabled:cursor-default`}
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-coal-100">
          {prettyName(agent.name)}
        </span>
        <span className={`shrink-0 text-[10px] font-medium uppercase tracking-wide ${style.text}`}>
          {style.label}
        </span>
      </div>

      <p className="mt-1 truncate text-[11px] text-coal-500">
        {AGENT_PURPOSE[agent.name] ?? 'Specialist analyst'}
      </p>

      {(agent.durationMs || agent.tokens) && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-coal-500">
          {agent.durationMs != null && <span>{(agent.durationMs / 1000).toFixed(1)}s</span>}
          {agent.tokens != null && <span>{agent.tokens} tok</span>}
          {agent.observations != null && <span>{agent.observations} obs</span>}
          {agent.interpretations != null && <span>{agent.interpretations} interp</span>}
        </div>
      )}

      {open && agent.errors && agent.errors.length > 0 && (
        <div className="mt-2 border-t border-red-500/20 pt-2">
          {agent.errors.map((error, index) => (
            <p key={index} className="text-[10px] leading-relaxed text-red-300/80">
              {error}
            </p>
          ))}
        </div>
      )}
    </button>
  )
}

function StageChip({
  label,
  active,
  done,
}: {
  label: string
  active: boolean
  done: boolean
}) {
  return (
    <span
      className={`rounded-lg border px-2.5 py-1.5 font-medium transition-colors duration-300 ${
        active
          ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
          : done
            ? 'border-emerald-500/25 bg-emerald-500/[0.07] text-emerald-400'
            : 'hairline text-coal-500'
      }`}
    >
      {done && !active ? '✓ ' : ''}
      {label}
    </span>
  )
}
