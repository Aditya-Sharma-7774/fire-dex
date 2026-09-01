import { useCallback, useEffect, useMemo, useState } from 'react'

import { BarRows, Gauge, StackedBar, TrendLine } from '../../components/charts/Charts'
import {
  api,
  ApiError,
  type AnalysisDetailResponse,
  type AnalysisHistoryItem,
  type VerificationResponse,
} from '../../services/api'
import { AgentTimeline } from '../ai/AgentTimeline'
import { SuggestionPanel, type Suggestion } from '../ai/SuggestionPanel'

/**
 * Analysis history: recorded analytics across all runs, plus a full
 * drill-down into any single one.
 *
 * This page is where auditability stops being a claim and becomes something
 * a person can check. For any past result you can see which model produced
 * it and what it cost, when each agent ran, exactly what each one said and
 * which evidence it cited, the reviewer's verdict and reasoning, and
 * whether the stored record still hashes to its recorded fingerprint.
 */
export function HistoryPage() {
  const [items, setItems] = useState<AnalysisHistoryItem[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const rows = await api.history(50)
      setItems(rows)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-8">
      <header className="border-b hairline pb-5">
        <h1 className="text-3xl font-bold tracking-tight">
          Analysis <span className="fire-text">History</span>
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-coal-400">
          Every analysis is recorded with the model that produced it, what it cost, and a
          SHA-256 hash chained to the record before it.
        </p>
      </header>

      {error && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/[0.07] p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {loading && <div className="h-40 animate-shimmer rounded-2xl" />}

      {!loading && items.length === 0 && !error && (
        <section className="glass p-10 text-center">
          <p className="text-sm text-coal-400">
            No analyses recorded yet. Run one from the Fire AI page.
          </p>
        </section>
      )}

      {items.length > 0 && <Analytics items={items} />}

      {items.length > 0 && (
        <section>
          <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-500">
            Recorded analyses ({items.length})
          </h2>
          <div className="space-y-2">
            {items.map((item) => (
              <HistoryRow
                key={item.result_id}
                item={item}
                expanded={selected === item.result_id}
                onToggle={() =>
                  setSelected(selected === item.result_id ? null : item.result_id)
                }
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Recorded analytics across every run                                 */
/* ------------------------------------------------------------------ */

function Analytics({ items }: { items: AnalysisHistoryItem[] }) {
  const stats = useMemo(() => {
    // History arrives newest first; charts read left-to-right in time.
    const chronological = [...items].reverse()

    const scored = chronological.filter((i) => i.reviewer_score != null)
    const inputTokens = items.reduce((sum, i) => sum + (i.input_tokens ?? 0), 0)
    const outputTokens = items.reduce((sum, i) => sum + (i.output_tokens ?? 0), 0)

    // Group by the exact model that produced each analysis, so a run's
    // cost can be attributed rather than averaged into one blur.
    const byModel = new Map<string, { runs: number; tokens: number; scoreSum: number; scored: number }>()
    for (const item of items) {
      const key = item.model ?? 'unknown'
      const entry = byModel.get(key) ?? { runs: 0, tokens: 0, scoreSum: 0, scored: 0 }
      entry.runs += 1
      entry.tokens += (item.input_tokens ?? 0) + (item.output_tokens ?? 0)
      if (item.reviewer_score != null) {
        entry.scoreSum += item.reviewer_score
        entry.scored += 1
      }
      byModel.set(key, entry)
    }

    return {
      scoreTrend: scored.map((i, n) => ({
        label: i.result_id ?? `#${n}`,
        value: i.reviewer_score as number,
      })),
      coverageTrend: chronological
        .filter((i) => i.evidence_coverage != null)
        .map((i) => ({ label: i.result_id, value: (i.evidence_coverage as number) * 100 })),
      durationTrend: chronological
        .filter((i) => i.duration_ms != null)
        .map((i) => ({ label: i.result_id, value: (i.duration_ms as number) / 1000 })),
      inputTokens,
      outputTokens,
      avgScore: scored.length
        ? scored.reduce((s, i) => s + (i.reviewer_score as number), 0) / scored.length
        : 0,
      avgCoverage:
        items.reduce((s, i) => s + (i.evidence_coverage ?? 0), 0) / Math.max(items.length, 1),
      verdicts: {
        approved: items.filter((i) => i.reviewer_verdict === 'APPROVED').length,
        reanalyze: items.filter((i) => i.reviewer_verdict === 'REANALYZE').length,
        rejected: items.filter((i) => i.reviewer_verdict === 'REJECTED').length,
      },
      models: [...byModel.entries()].map(([model, e]) => ({
        model,
        runs: e.runs,
        tokens: e.tokens,
        avgScore: e.scored ? e.scoreSum / e.scored : null,
      })),
    }
  }, [items])

  return (
    <section className="space-y-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-500">
        Recorded analytics
      </h2>

      {/* headline gauges */}
      <div className="glass flex flex-wrap items-center justify-around gap-6 p-6">
        <Gauge
          value={stats.avgScore}
          label={stats.avgScore.toFixed(0)}
          sublabel="avg reviewer score"
          colour="#f97316"
        />
        <Gauge
          value={stats.avgCoverage * 100}
          label={`${(stats.avgCoverage * 100).toFixed(0)}%`}
          sublabel="avg evidence coverage"
          colour="#34d399"
        />
        <Gauge
          value={items.length}
          max={Math.max(items.length, 10)}
          label={String(items.length)}
          sublabel="analyses recorded"
          colour="#60a5fa"
        />

        <div className="min-w-[190px] flex-1">
          <div className="mb-2 text-[10px] uppercase tracking-wide text-coal-500">
            Token consumption
          </div>
          <StackedBar
            segments={[
              { label: 'input', value: stats.inputTokens, colour: '#60a5fa' },
              { label: 'output', value: stats.outputTokens, colour: '#f97316' },
            ]}
          />
          <div className="mt-2 text-[10px] text-coal-600">
            {(stats.inputTokens + stats.outputTokens).toLocaleString()} tokens across{' '}
            {items.length} {items.length === 1 ? 'analysis' : 'analyses'}
          </div>
        </div>
      </div>

      {/* trends */}
      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Reviewer score" note="higher is better">
          <TrendLine data={stats.scoreTrend} colour="#f97316" />
        </ChartCard>
        <ChartCard title="Evidence coverage" note="% of facts actually cited">
          <TrendLine data={stats.coverageTrend} colour="#34d399" suffix="%" />
        </ChartCard>
        <ChartCard title="Duration" note="seconds per analysis">
          <TrendLine data={stats.durationTrend} colour="#60a5fa" suffix="s" />
        </ChartCard>
      </div>

      {/* per-model attribution */}
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Models used" note="which model produced which analyses">
          <div className="space-y-3">
            {stats.models.map((m) => (
              <div key={m.model} className="rounded-xl border hairline bg-coal-900/40 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-mono text-xs text-coal-100">{m.model}</span>
                  <span className="text-[10px] text-coal-500">
                    {m.runs} {m.runs === 1 ? 'run' : 'runs'}
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 text-[10px] text-coal-500">
                  <span>
                    <span className="text-coal-300">{m.tokens.toLocaleString()}</span> tokens
                  </span>
                  <span>
                    avg score{' '}
                    <span className="text-coal-300">
                      {m.avgScore != null ? m.avgScore.toFixed(1) : '—'}
                    </span>
                  </span>
                  <span>
                    <span className="text-coal-300">
                      {m.runs ? Math.round(m.tokens / m.runs).toLocaleString() : 0}
                    </span>{' '}
                    tokens/run
                  </span>
                </div>
              </div>
            ))}
          </div>
        </ChartCard>

        <ChartCard title="Reviewer verdicts" note="the reviewer can and does reject">
          <StackedBar
            segments={[
              { label: 'approved', value: stats.verdicts.approved, colour: '#34d399' },
              { label: 'reanalyze', value: stats.verdicts.reanalyze, colour: '#fbbf24' },
              { label: 'rejected', value: stats.verdicts.rejected, colour: '#f87171' },
            ]}
          />
          <p className="mt-3 text-[10px] leading-relaxed text-coal-600">
            A reviewer that never rejects is not reviewing. Rejections are kept in the record
            rather than hidden.
          </p>
        </ChartCard>
      </div>
    </section>
  )
}

function ChartCard({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <div className="glass p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
          {title}
        </h3>
        {note && <span className="text-[10px] text-coal-600">{note}</span>}
      </div>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* One row + drill-down                                                */
/* ------------------------------------------------------------------ */

function HistoryRow({
  item,
  expanded,
  onToggle,
}: {
  item: AnalysisHistoryItem
  expanded: boolean
  onToggle: () => void
}) {
  const verdictStyle =
    item.reviewer_verdict === 'APPROVED'
      ? 'text-emerald-400 bg-emerald-500/10'
      : item.reviewer_verdict === 'REANALYZE'
        ? 'text-amber-400 bg-amber-500/10'
        : 'text-red-400 bg-red-500/10'

  const totalTokens = (item.input_tokens ?? 0) + (item.output_tokens ?? 0)

  return (
    <div className={`glass overflow-hidden transition-colors ${expanded ? 'border-fire-500/25' : ''}`}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 p-4 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="font-mono text-xs text-fire-300">{item.result_id}</span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-coal-100">{item.query}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] text-coal-500">
            <span className="rounded bg-white/[0.05] px-1.5 py-px text-coal-300">
              {item.model ?? 'no model'}
            </span>
            <span className={item.mode === 'local' ? 'text-blue-400' : 'text-fire-400'}>
              {item.mode ?? '—'}
            </span>
            <span>{totalTokens.toLocaleString()} tok</span>
            <span>{item.duration_ms ? `${(item.duration_ms / 1000).toFixed(1)}s` : ''}</span>
            <span>{new Date(item.created_at).toLocaleString()}</span>
          </span>
        </span>

        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${verdictStyle}`}
        >
          {item.reviewer_verdict ?? '—'}
        </span>

        <span className="shrink-0 text-right">
          <span className="block font-mono text-sm text-coal-100">
            {item.reviewer_score?.toFixed(1) ?? '—'}
          </span>
          <span className="block text-[10px] text-coal-600">score</span>
        </span>

        <span
          className={`shrink-0 text-coal-600 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      {expanded && <AnalysisDetail resultId={item.result_id} />}
    </div>
  )
}

function AnalysisDetail({ resultId }: { resultId: string }) {
  const [detail, setDetail] = useState<AnalysisDetailResponse | null>(null)
  const [verification, setVerification] = useState<VerificationResponse | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .analysis(resultId)
      .then(setDetail)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : 'Could not load analysis'),
      )
  }, [resultId])

  const verify = async () => {
    setVerifying(true)
    try {
      setVerification(await api.verify(resultId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed')
    } finally {
      setVerifying(false)
    }
  }

  if (error) {
    return <div className="border-t hairline p-4 text-xs text-red-300">{error}</div>
  }

  if (!detail) {
    return (
      <div className="border-t hairline p-4">
        <div className="h-24 animate-shimmer rounded" />
      </div>
    )
  }

  const reviewer = (detail.reviewer_result ?? {}) as Record<string, any>
  const executions = detail.executions as any[]
  const agents = detail.agent_results as any[]

  const durationBars = executions
    .filter((e) => e.duration_ms != null)
    .map((e) => ({ label: prettyName(e.agent), value: e.duration_ms / 1000 }))

  const tokenBars = executions
    .filter((e) => (e.input_tokens ?? 0) + (e.output_tokens ?? 0) > 0)
    .map((e) => ({
      label: prettyName(e.agent),
      value: (e.input_tokens ?? 0) + (e.output_tokens ?? 0),
    }))

  return (
    <div className="space-y-6 border-t hairline p-4 sm:p-5">
      {/* ---- model and cost ---- */}
      <section>
        <SectionTitle>Model and cost</SectionTitle>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border hairline bg-coal-900/40 p-3">
          <Field label="Model" value={detail.model ?? '—'} mono />
          <Field label="Provider" value={detail.provider ?? '—'} />
          <Field
            label="Mode"
            value={detail.mode ?? '—'}
            tone={detail.mode === 'local' ? 'text-blue-400' : 'text-fire-400'}
          />
          <Field label="Input tokens" value={(detail.input_tokens ?? 0).toLocaleString()} mono />
          <Field label="Output tokens" value={(detail.output_tokens ?? 0).toLocaleString()} mono />
          <Field
            label="Total"
            value={((detail.input_tokens ?? 0) + (detail.output_tokens ?? 0)).toLocaleString()}
            mono
          />
        </div>
      </section>

      {/* ---- suggestion: signal, groundedness and the explanations ---- */}
      {detail.suggestion_result && (
        <section>
          <SectionTitle>Suggestion &amp; groundedness</SectionTitle>
          <SuggestionPanel suggestion={detail.suggestion_result as unknown as Suggestion} />
        </section>
      )}

      {/* ---- agents working: timeline ---- */}
      <section>
        <SectionTitle>Agent execution</SectionTitle>
        <div className="rounded-xl border hairline bg-coal-900/40 p-3">
          <AgentTimeline executions={executions} />
        </div>
      </section>

      {/* ---- per-agent charts ---- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border hairline bg-coal-900/40 p-3">
          <SectionTitle>Time per agent</SectionTitle>
          <BarRows
            data={durationBars}
            colour="#60a5fa"
            formatValue={(v) => v.toFixed(1)}
            unit="s"
          />
        </div>
        <div className="rounded-xl border hairline bg-coal-900/40 p-3">
          <SectionTitle>Tokens per agent</SectionTitle>
          <BarRows
            data={tokenBars}
            colour="#f97316"
            formatValue={(v) => v.toLocaleString()}
          />
        </div>
      </div>

      {/* ---- reviewer verdict ---- */}
      <section>
        <SectionTitle>Reviewer verdict</SectionTitle>
        <div className="rounded-xl border hairline bg-coal-900/40 p-4">
          <div className="flex flex-wrap items-center gap-6">
            <Gauge
              value={Number(reviewer.score ?? 0)}
              label={Number(reviewer.score ?? 0).toFixed(0)}
              sublabel={String(reviewer.verdict ?? '—')}
              colour={
                reviewer.verdict === 'APPROVED'
                  ? '#34d399'
                  : reviewer.verdict === 'REANALYZE'
                    ? '#fbbf24'
                    : '#f87171'
              }
              size={84}
            />
            <Gauge
              value={Number(reviewer.confidence ?? 0) * 100}
              label={Number(reviewer.confidence ?? 0).toFixed(2)}
              sublabel="confidence"
              colour="#a78bfa"
              size={84}
            />

            <div className="min-w-[200px] flex-1 space-y-1.5">
              <ScoreLine
                label="Computed score"
                value={Number(reviewer.computed_score ?? 0).toFixed(1)}
              />
              <ScoreLine
                label="Model penalty"
                value={`− ${Number(reviewer.model_penalty ?? 0).toFixed(1)}`}
              />
              <ScoreLine
                label="Citation validity"
                value={`${(Number(reviewer.citation_validity ?? 0) * 100).toFixed(0)}%`}
              />
              <ScoreLine
                label="Agent agreement"
                value={`${(Number(reviewer.agent_agreement ?? 0) * 100).toFixed(0)}%`}
              />
            </div>
          </div>

          {reviewer.reasoning && (
            <p className="mt-3 border-t hairline pt-3 text-[11px] leading-relaxed text-coal-300">
              {String(reviewer.reasoning)}
            </p>
          )}

          {Array.isArray(reviewer.concerns) && reviewer.concerns.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wide text-amber-500">Concerns</div>
              {reviewer.concerns.map((c: string, i: number) => (
                <p key={i} className="mt-1 text-[11px] text-amber-200/70">
                  · {c}
                </p>
              ))}
            </div>
          )}

          {Array.isArray(reviewer.strengths) && reviewer.strengths.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wide text-emerald-500">Strengths</div>
              {reviewer.strengths.map((c: string, i: number) => (
                <p key={i} className="mt-1 text-[11px] text-emerald-200/70">
                  · {c}
                </p>
              ))}
            </div>
          )}

          <p className="mt-3 border-t hairline pt-2 text-[10px] leading-relaxed text-coal-600">
            The score is mostly computed — coverage, citation validity, completion and
            agreement. The model may only apply a penalty of up to 25 points, because letting a
            model grade its own output would be circular.
          </p>
        </div>
      </section>

      {/* ---- what each agent said ---- */}
      <section>
        <SectionTitle>What each agent said</SectionTitle>
        <div className="space-y-2">
          {agents.map((agent, index) => (
            <AgentOutput key={index} agent={agent} />
          ))}
        </div>
      </section>

      {/* ---- integrity ---- */}
      <section>
        <SectionTitle>Integrity</SectionTitle>
        <div className="space-y-2 rounded-xl border hairline bg-coal-900/40 p-3">
          <HashLine label="This record" value={detail.result_hash} />
          <HashLine label="Previous record" value={detail.prev_hash} />

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => void verify()}
              disabled={verifying}
              className="rounded-lg border border-fire-500/30 bg-fire-500/10 px-3 py-1.5 text-xs font-medium text-fire-300 transition-colors hover:bg-fire-500/20 disabled:opacity-50"
            >
              {verifying ? 'Verifying…' : 'Verify integrity'}
            </button>

            {verification && (
              <span
                className={`text-xs font-medium ${verification.valid ? 'text-emerald-400' : 'text-red-400'}`}
              >
                {verification.valid ? '✓ ' : '⚠ '}
                {verification.message}
              </span>
            )}
          </div>

          <p className="pt-1 text-[10px] leading-relaxed text-coal-600">
            Hashing proves this record has not changed since it was written (tamper-evidence).
            It is not immutability — that would require anchoring the chain on a blockchain,
            which we have not done.
          </p>
        </div>
      </section>

      {/* ---- evidence ---- */}
      <section>
        <SectionTitle>Evidence used ({detail.evidence.length} facts)</SectionTitle>
        <div className="max-h-72 space-y-1 overflow-y-auto rounded-xl border hairline bg-coal-900/40 p-3">
          {detail.evidence.map((raw, index) => {
            const item = raw as Record<string, any>
            return (
              <div key={index} className="flex flex-wrap gap-x-2 text-[11px]">
                <span className="font-mono text-fire-500/70">{item.evidence_id}</span>
                <span className="text-coal-400">{item.label}:</span>
                <span className="font-mono text-coal-200">
                  {String(item.value)}
                  {item.unit ? ` ${item.unit}` : ''}
                </span>
                <span className="ml-auto font-mono text-[9px] text-coal-600">
                  {item.source?.provider}
                </span>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}

function AgentOutput({ agent }: { agent: Record<string, any> }) {
  const completed = agent.status === 'completed'
  const observations = (agent.observations ?? []) as any[]
  const interpretations = (agent.interpretations ?? []) as any[]

  return (
    <div className="rounded-xl border hairline bg-coal-900/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ background: completed ? '#34d399' : '#f87171' }}
        />
        <span className="text-xs font-semibold text-coal-100">{prettyName(agent.agent)}</span>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
            completed ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
          }`}
        >
          {String(agent.status)}
        </span>
        <span className="ml-auto flex gap-3 font-mono text-[10px] text-coal-500">
          {agent.duration_ms != null && <span>{(agent.duration_ms / 1000).toFixed(1)}s</span>}
          {agent.input_tokens != null && (
            <span>
              {((agent.input_tokens ?? 0) + (agent.output_tokens ?? 0)).toLocaleString()} tok
            </span>
          )}
        </span>
      </div>

      {observations.map((o, i) => (
        <p key={`o${i}`} className="mt-2 text-[11px] leading-relaxed text-coal-300">
          <span className="mr-1 rounded bg-white/[0.06] px-1 text-[9px] uppercase text-coal-500">
            obs
          </span>
          {o.text}{' '}
          <span className="font-mono text-[9px] text-fire-500/70">
            [{(o.evidence_ids ?? []).join(', ')}]
          </span>
        </p>
      ))}

      {interpretations.map((it, i) => (
        <p key={`i${i}`} className="mt-2 text-[11px] leading-relaxed text-coal-400">
          <span className="mr-1 rounded bg-fire-500/10 px-1 text-[9px] uppercase text-fire-400">
            interp
          </span>
          <em>{it.text}</em>{' '}
          <span className="font-mono text-[9px] text-fire-500/70">
            [{(it.evidence_ids ?? []).join(', ')}]
          </span>
          {it.confidence != null && (
            <span className="ml-1 text-[9px] text-coal-600">conf {Number(it.confidence).toFixed(2)}</span>
          )}
        </p>
      ))}

      {(agent.warnings ?? []).map((w: string, i: number) => (
        <p key={`w${i}`} className="mt-2 text-[11px] text-amber-300/70">
          ⚠ {w}
        </p>
      ))}

      {(agent.errors ?? []).map((e: string, i: number) => (
        <p key={`e${i}`} className="mt-2 text-[11px] text-red-300/80">
          {e}
        </p>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */

function prettyName(name: string): string {
  return String(name).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-coal-500">
      {children}
    </h3>
  )
}

function Field({
  label,
  value,
  mono,
  tone,
}: {
  label: string
  value: string
  mono?: boolean
  tone?: string
}) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wide text-coal-600">{label}</div>
      <div className={`mt-0.5 text-xs ${mono ? 'font-mono' : ''} ${tone ?? 'text-coal-200'}`}>
        {value}
      </div>
    </div>
  )
}

function ScoreLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[11px]">
      <span className="text-coal-500">{label}</span>
      <span className="font-mono text-coal-200">{value}</span>
    </div>
  )
}

function HashLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <span className="w-28 shrink-0 text-[10px] uppercase tracking-wide text-coal-600">
        {label}
      </span>
      <span className="break-all font-mono text-[10px] text-coal-300">{value}</span>
    </div>
  )
}
