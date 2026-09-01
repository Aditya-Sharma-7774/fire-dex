/**
 * Gantt view of one analysis: when each agent ran and for how long.
 *
 * This makes two things visible that a list of results cannot:
 *
 *   1. Agents genuinely run CONCURRENTLY. Overlapping bars are the proof.
 *      With a local model the bars are sequential instead, which is a real
 *      and visible difference worth being able to point at.
 *   2. Where the time actually went, so "why did that take 8 seconds" has
 *      an answer you can see rather than guess at.
 */

interface Execution {
  agent: string
  status: string
  started_at: string
  ended_at: string | null
  duration_ms: number | null
  model?: string | null
  input_tokens?: number | null
  output_tokens?: number | null
  observation_count?: number
  interpretation_count?: number
  validation_passed?: boolean
  error?: string | null
}

const STATUS_COLOUR: Record<string, string> = {
  completed: '#34d399',
  failed: '#f87171',
  skipped: '#61616b',
  running: '#fbbf24',
}

function prettyName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function AgentTimeline({ executions }: { executions: Execution[] }) {
  const withTimes = executions.filter((e) => e.started_at)
  if (withTimes.length === 0) {
    return <p className="text-xs text-coal-600">No execution timing recorded.</p>
  }

  const starts = withTimes.map((e) => new Date(e.started_at).getTime())
  const ends = withTimes.map((e) =>
    e.ended_at ? new Date(e.ended_at).getTime() : new Date(e.started_at).getTime(),
  )
  const t0 = Math.min(...starts)
  const t1 = Math.max(...ends)
  const span = Math.max(t1 - t0, 1)

  const overlapping = withTimes.some((a, i) =>
    withTimes.some((b, j) => {
      if (i >= j) return false
      const aStart = new Date(a.started_at).getTime()
      const aEnd = a.ended_at ? new Date(a.ended_at).getTime() : aStart
      const bStart = new Date(b.started_at).getTime()
      const bEnd = b.ended_at ? new Date(b.ended_at).getTime() : bStart
      return aStart < bEnd && bStart < aEnd
    }),
  )

  return (
    <div>
      <div className="space-y-1.5">
        {withTimes.map((execution) => {
          const start = new Date(execution.started_at).getTime()
          const end = execution.ended_at ? new Date(execution.ended_at).getTime() : start
          const left = ((start - t0) / span) * 100
          const width = Math.max(((end - start) / span) * 100, 1.5)
          const colour = STATUS_COLOUR[execution.status] ?? '#61616b'

          return (
            <div key={execution.agent} className="flex items-center gap-3">
              <span className="w-32 shrink-0 truncate text-[11px] text-coal-400">
                {prettyName(execution.agent)}
              </span>

              <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-white/[0.03]">
                <div
                  className="absolute top-0 flex h-full items-center rounded-md px-2"
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                    background: `linear-gradient(90deg, ${colour}33, ${colour}55)`,
                    borderLeft: `2px solid ${colour}`,
                  }}
                  title={`${prettyName(execution.agent)} · ${execution.status}`}
                >
                  <span className="truncate font-mono text-[9px] text-coal-200">
                    {execution.duration_ms != null
                      ? `${(execution.duration_ms / 1000).toFixed(1)}s`
                      : ''}
                  </span>
                </div>
              </div>

              <span
                className="w-14 shrink-0 text-right text-[10px] font-medium uppercase"
                style={{ color: colour }}
              >
                {execution.status}
              </span>
            </div>
          )
        })}
      </div>

      <div className="mt-2 flex items-center justify-between text-[9px] text-coal-600">
        <span>0s</span>
        <span>
          {overlapping
            ? 'bars overlap — agents ran concurrently'
            : 'bars are sequential — agents ran one at a time'}
        </span>
        <span>{(span / 1000).toFixed(1)}s</span>
      </div>
    </div>
  )
}
