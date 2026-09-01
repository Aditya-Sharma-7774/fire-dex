import { useCallback, useEffect, useState } from 'react'

import {
  api,
  ApiError,
  type AnalysisDetailResponse,
  type AnalysisHistoryItem,
  type VerificationResponse,
} from '../../services/api'

/**
 * Analysis history with full drill-down and hash verification.
 *
 * This page is where auditability stops being a claim and becomes something
 * a person can check. For any past result you can see the evidence that was
 * gathered, what each agent said, which evidence each claim cited, what the
 * reviewer thought, and whether the stored record still hashes to its
 * recorded fingerprint.
 */
export function HistoryPage() {
  const [items, setItems] = useState<AnalysisHistoryItem[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      setItems(await api.history(50))
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="text-2xl font-bold tracking-tight">
          Analysis <span className="fire-text">History</span>
        </h1>
        <span className="text-[11px] text-coal-500">
          Every result is hashed and chained to the one before it
        </span>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/[0.07] p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {loading && <div className="h-24 animate-shimmer rounded-2xl" />}

      {!loading && items.length === 0 && !error && (
        <section className="glass p-8 text-center">
          <p className="text-sm text-coal-400">
            No analyses recorded yet. Run one from the Fire AI page.
          </p>
        </section>
      )}

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
    </div>
  )
}

function HistoryRow({
  item,
  expanded,
  onToggle,
}: {
  item: AnalysisHistoryItem
  expanded: boolean
  onToggle: () => void
}) {
  const verdictColour =
    item.reviewer_verdict === 'APPROVED'
      ? 'text-emerald-400 bg-emerald-500/10'
      : item.reviewer_verdict === 'REANALYZE'
        ? 'text-amber-400 bg-amber-500/10'
        : 'text-red-400 bg-red-500/10'

  return (
    <div className="glass overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 p-4 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="font-mono text-xs text-fire-300">{item.result_id}</span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-coal-100">
            {item.query}
          </span>
          <span className="block font-mono text-[10px] text-coal-500">
            {item.model ?? 'no model'} · {item.mode ?? '—'} ·{' '}
            {new Date(item.created_at).toLocaleString()}
          </span>
        </span>

        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${verdictColour}`}
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
    return <div className="border-t hairline p-4"><div className="h-16 animate-shimmer rounded" /></div>
  }

  return (
    <div className="space-y-5 border-t hairline p-4 sm:p-5">
      {/* --- audit metrics --- */}
      <section>
        <SectionTitle>Fire Auditor metrics</SectionTitle>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="Evidence" value={String(detail.evidence_count)} />
          <Metric
            label="Coverage"
            value={
              detail.evidence_coverage != null
                ? `${(detail.evidence_coverage * 100).toFixed(1)}%`
                : '—'
            }
          />
          <Metric
            label="Agents"
            value={`${detail.agents_completed}/${detail.agents_completed + detail.agents_failed}`}
          />
          <Metric
            label="Duration"
            value={detail.duration_ms ? `${(detail.duration_ms / 1000).toFixed(1)}s` : '—'}
          />
          <Metric label="Input tokens" value={String(detail.input_tokens ?? '—')} />
          <Metric label="Output tokens" value={String(detail.output_tokens ?? '—')} />
          <Metric
            label="Confidence"
            value={detail.confidence != null ? detail.confidence.toFixed(2) : '—'}
          />
          <Metric label="Stale data" value={detail.data_stale ? 'Yes' : 'No'} />
        </div>
      </section>

      {/* --- integrity --- */}
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
            Hashing proves this record has not changed since it was written
            (tamper-evidence). It is not immutability — that would require anchoring the
            chain on a blockchain, which we have not done.
          </p>
        </div>
      </section>

      {/* --- summary --- */}
      {detail.summary && (
        <section>
          <SectionTitle>Final answer</SectionTitle>
          <div className="whitespace-pre-wrap rounded-xl border hairline bg-coal-900/40 p-3 text-xs leading-relaxed text-coal-300">
            {detail.summary}
          </div>
        </section>
      )}

      {/* --- agent detail --- */}
      <section>
        <SectionTitle>Agents</SectionTitle>
        <div className="space-y-2">
          {detail.agent_results.map((raw, index) => {
            const agent = raw as Record<string, any>
            return (
              <div key={index} className="rounded-xl border hairline bg-coal-900/40 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold text-coal-100">
                    {String(agent.agent).replace(/_/g, ' ')}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                      agent.status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-red-500/10 text-red-400'
                    }`}
                  >
                    {String(agent.status)}
                  </span>
                  <span className="font-mono text-[10px] text-coal-500">
                    {agent.duration_ms ? `${(agent.duration_ms / 1000).toFixed(1)}s` : ''}
                  </span>
                </div>

                {(agent.observations as any[])?.map((o: any, i: number) => (
                  <p key={`o${i}`} className="mt-1.5 text-[11px] text-coal-300">
                    <span className="text-coal-600">OBS</span> {o.text}{' '}
                    <span className="font-mono text-[9px] text-fire-500/70">
                      [{(o.evidence_ids ?? []).join(', ')}]
                    </span>
                  </p>
                ))}

                {(agent.interpretations as any[])?.map((i2: any, i: number) => (
                  <p key={`i${i}`} className="mt-1.5 text-[11px] italic text-coal-400">
                    <span className="not-italic text-coal-600">INT</span> {i2.text}{' '}
                    <span className="font-mono text-[9px] not-italic text-fire-500/70">
                      [{(i2.evidence_ids ?? []).join(', ')}]
                    </span>
                  </p>
                ))}

                {(agent.errors as string[])?.map((e, i) => (
                  <p key={`e${i}`} className="mt-1.5 text-[11px] text-red-300/80">
                    {e}
                  </p>
                ))}
              </div>
            )
          })}
        </div>
      </section>

      {/* --- evidence --- */}
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

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-coal-500">
      {children}
    </h3>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border hairline bg-coal-900/40 p-2.5">
      <div className="text-[9px] uppercase tracking-wide text-coal-600">{label}</div>
      <div className="mt-0.5 font-mono text-sm text-coal-100">{value}</div>
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
