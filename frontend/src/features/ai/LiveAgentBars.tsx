import { useEffect, useRef, useState } from 'react'

import type { AgentProgress } from './useAnalysis'

/**
 * Live activity bars while agents are working.
 *
 * The agent grid says *what* each agent is doing. This says *how long it
 * has been doing it* — a bar that grows in real time while an agent thinks,
 * then freezes at its final duration when it finishes.
 *
 * That matters for a demo: a 30-second wait with nothing moving reads as
 * broken. A bar that visibly advances reads as work in progress, and the
 * relative bar lengths afterwards show where the time actually went.
 */
export function LiveAgentBars({
  agents,
  running,
}: {
  agents: AgentProgress[]
  running: boolean
}) {
  // Ticks while anything is running so elapsed time advances on screen.
  const [, forceTick] = useState(0)
  const startedRef = useRef<Record<string, number>>({})

  useEffect(() => {
    for (const agent of agents) {
      if (agent.status === 'running' && startedRef.current[agent.name] == null) {
        startedRef.current[agent.name] = Date.now()
      }
    }
  }, [agents])

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => forceTick((n) => n + 1), 120)
    return () => clearInterval(timer)
  }, [running])

  const visible = agents.filter((a) => a.name !== 'reviewer' && a.name !== 'fire_auditor')
  if (visible.length === 0) return null

  // Scale bars against the longest elapsed time so far, with a floor so a
  // single fast agent does not fill the whole width.
  const elapsedFor = (agent: AgentProgress): number => {
    if (agent.durationMs != null) return agent.durationMs
    const started = startedRef.current[agent.name]
    if (agent.status === 'running' && started) return Date.now() - started
    return 0
  }

  const max = Math.max(...visible.map(elapsedFor), 3000)

  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
          Agents working
        </h3>
        <span className="text-[10px] text-coal-600">
          {running ? 'live' : 'final durations'}
        </span>
      </div>

      <div className="space-y-2">
        {visible.map((agent) => {
          const elapsed = elapsedFor(agent)
          const pct = Math.min((elapsed / max) * 100, 100)
          const isRunning = agent.status === 'running'
          const failed = agent.status === 'failed'

          const colour = failed ? '#f87171' : isRunning ? '#fbbf24' : '#34d399'

          return (
            <div key={agent.name} className="flex items-center gap-3">
              <span className="w-32 shrink-0 truncate text-[11px] text-coal-400">
                {agent.name.replace(/_/g, ' ')}
              </span>

              <div className="relative h-5 flex-1 overflow-hidden rounded-md bg-white/[0.04]">
                <div
                  className="h-full rounded-md"
                  style={{
                    width: `${Math.max(pct, elapsed > 0 ? 3 : 0)}%`,
                    background: `linear-gradient(90deg, ${colour}44, ${colour})`,
                    transition: isRunning ? 'none' : 'width 500ms ease-out',
                  }}
                />
                {isRunning && (
                  // Sheen sweeping along the bar, so a slow agent still
                  // looks alive rather than stalled.
                  <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-md">
                    <div className="h-full w-1/3 animate-[shimmer_1.4s_linear_infinite] bg-gradient-to-r from-transparent via-white/15 to-transparent" />
                  </div>
                )}
              </div>

              <span
                className="w-16 shrink-0 text-right font-mono text-[11px] text-coal-300"
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {elapsed > 0 ? `${(elapsed / 1000).toFixed(1)}s` : '—'}
              </span>

              <span className="w-16 shrink-0 text-right font-mono text-[10px] text-coal-600">
                {agent.tokens != null ? `${agent.tokens} tok` : ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
