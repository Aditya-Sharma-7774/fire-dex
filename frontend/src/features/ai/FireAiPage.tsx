import { useEffect, useState } from 'react'

import { api, type AiStatusResponse } from '../../services/api'
import { useWallet } from '../wallet/WalletContext'
import { BarRows, Gauge } from '../../components/charts/Charts'
import { AgentGrid } from './AgentGrid'
import { LiveAgentBars } from './LiveAgentBars'
import { useAnalysis } from './useAnalysis'

const SUGGESTIONS = [
  { label: 'Analyse ETH', request: { symbol: 'ETH' } },
  { label: 'Analyse LINK', request: { symbol: 'LINK' } },
  { label: 'Analyse WBTC', request: { symbol: 'WBTC' } },
  { label: 'Analyse UNI', request: { symbol: 'UNI' } },
]

/**
 * The Fire AI workspace.
 *
 * Everything the pipeline does is made visible: which evidence was
 * collected, which agents ran, how long each took, what the reviewer
 * concluded, and the hash of the stored record.
 */
export function FireAiPage() {
  const { status, address, chain, isUnsupportedNetwork } = useWallet()
  const analysis = useAnalysis()

  const [symbol, setSymbol] = useState('ETH')
  const [includePortfolio, setIncludePortfolio] = useState(false)
  // null means "let the backend use its configured preference".
  //
  // This was previously initialised to 'local', which created a race: the
  // AI-status request had not resolved yet, so clicking Run immediately
  // sent the request down the slow local path even though an online
  // provider was configured and preferred. Defaulting to null removes the
  // race rather than papering over it with a loading guard.
  const [prefer, setPrefer] = useState<'local' | 'online' | null>(null)
  const [ai, setAi] = useState<AiStatusResponse | null>(null)

  const walletReady = status === 'connected' && address && chain && !isUnsupportedNetwork

  useEffect(() => {
    api
      .aiStatus()
      .then(setAi)
      .catch(() => setAi(null))
  }, [])

  const start = () => {
    void analysis.run({
      symbol: symbol.trim().toUpperCase() || undefined,
      chain: includePortfolio && walletReady ? chain.id : undefined,
      address: includePortfolio && walletReady ? address : undefined,
      prefer: prefer ?? undefined,
      query: `Analyse ${symbol.trim().toUpperCase()}${includePortfolio ? ' and my portfolio' : ''}`,
    })
  }

  return (
    <div className="space-y-8">
      <section className="glass p-5 sm:p-6">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[140px] flex-1">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
              Asset
            </span>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !analysis.running && start()}
              placeholder="ETH"
              className="w-full rounded-xl border hairline bg-coal-900/60 px-3 py-2.5 font-mono text-sm uppercase text-coal-100 outline-none transition-colors focus:border-fire-500/50"
            />
          </label>

          <label className="min-w-[130px]">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
              Model
            </span>
            <select
              value={prefer ?? 'auto'}
              onChange={(e) =>
                setPrefer(e.target.value === 'auto' ? null : (e.target.value as 'local' | 'online'))
              }
              className="w-full rounded-xl border hairline bg-coal-900/60 px-3 py-2.5 text-sm text-coal-100 outline-none transition-colors focus:border-fire-500/50"
            >
              <option value="auto">Auto{ai ? ` (${ai.preference})` : ''}</option>
              <option value="local">
                Local{ai && !ai.local.available ? ' (offline)' : ''}
              </option>
              <option value="online">
                Online{ai && !ai.online.available ? ' (no key)' : ''}
              </option>
            </select>
          </label>

          <button
            type="button"
            onClick={analysis.running ? analysis.cancel : start}
            className={`group relative overflow-hidden rounded-xl px-5 py-2.5 text-sm font-semibold transition-all ${
              analysis.running
                ? 'border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20'
                : 'bg-gradient-to-br from-fire-500 to-fire-700 text-white shadow-glow hover:shadow-glow-lg'
            }`}
          >
            {!analysis.running && (
              <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
            )}
            <span className="relative">{analysis.running ? 'Cancel' : 'Run Analysis'}</span>
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t hairline pt-4">
          <label
            className={`flex items-center gap-2 text-xs ${walletReady ? 'text-coal-300' : 'cursor-not-allowed text-coal-600'}`}
            title={walletReady ? undefined : 'Connect a wallet on a supported network'}
          >
            <input
              type="checkbox"
              disabled={!walletReady}
              checked={includePortfolio && Boolean(walletReady)}
              onChange={(e) => setIncludePortfolio(e.target.checked)}
              className="h-3.5 w-3.5 accent-fire-500"
            />
            Include my portfolio
          </label>

          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                type="button"
                disabled={analysis.running}
                onClick={() => setSymbol(s.request.symbol)}
                className="rounded-lg border hairline px-2.5 py-1 text-[11px] text-coal-400 transition-colors hover:border-fire-500/30 hover:text-coal-200 disabled:opacity-40"
              >
                {s.label}
              </button>
            ))}
          </div>

          {ai && (
            <span className="ml-auto font-mono text-[10px] text-coal-600">
              {(prefer ?? ai.preference) === 'local' ? ai.local.model : ai.online.model}
            </span>
          )}
        </div>
      </section>

      {analysis.error && (
        <div className="animate-fade-up rounded-2xl border border-red-500/30 bg-red-500/[0.07] p-4">
          <div className="text-sm font-semibold text-red-300">Analysis failed</div>
          <p className="mt-1 text-xs leading-relaxed text-red-200/70">{analysis.error}</p>
        </div>
      )}

      {(analysis.running || analysis.agents.length > 0) && (
        <div className="space-y-3">
          <AgentGrid
            agents={analysis.agents}
            running={analysis.running}
            reviewerDone={analysis.reviewer !== null}
            auditDone={analysis.hash !== null}
          />
          <LiveAgentBars agents={analysis.agents} running={analysis.running} />
        </div>
      )}

      {analysis.summary && <ResultPanel analysis={analysis} />}

      {!analysis.running && !analysis.summary && !analysis.error && <EmptyState />}
    </div>
  )
}

/* ------------------------------------------------------------------ */

function EmptyState() {
  return (
    <section className="glass p-8 text-center sm:p-10">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-fire-500/20 to-fire-700/10 ring-1 ring-fire-500/20">
        <span className="text-2xl" aria-hidden="true">
          🔥
        </span>
      </div>
      <h2 className="mt-4 text-lg font-bold tracking-tight">Run an analysis</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-coal-400">
        Deterministic collectors gather real market and chain data into an evidence bundle.
        Specialist agents then interpret it — and may only make claims that cite that evidence.
        Every result is recorded, hashed and independently verifiable.
      </p>
      <p className="mx-auto mt-3 max-w-lg text-[11px] text-coal-600">
        A run against a local model takes roughly 30–90 seconds per agent. You will see each
        agent start and finish as it happens.
      </p>
    </section>
  )
}

function ResultPanel({ analysis }: { analysis: ReturnType<typeof useAnalysis> }) {
  const reviewer = analysis.reviewer

  return (
    <section className="animate-fade-up space-y-4">
      {reviewer && (
        <div className="glass p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
                Reviewer verdict
              </div>
              <div className="mt-2 flex items-center gap-3">
                <VerdictBadge verdict={reviewer.verdict} />
                <span className="text-3xl font-extrabold tracking-tight text-coal-50">
                  {reviewer.score.toFixed(1)}
                  <span className="text-base font-medium text-coal-500">/100</span>
                </span>
              </div>
              <p className="mt-1.5 text-[11px] text-coal-500">
                {reviewer.computed_score.toFixed(1)} computed
                {reviewer.model_penalty > 0 && ` − ${reviewer.model_penalty.toFixed(1)} model penalty`}
              </p>
            </div>

            {analysis.resultId && (
              <div className="text-right">
                <div className="font-mono text-sm text-fire-300">{analysis.resultId}</div>
                <div className="mt-0.5 font-mono text-[10px] text-coal-600">
                  {analysis.hash?.slice(0, 24)}…
                </div>
                <div className="mt-1 text-[10px] uppercase tracking-wide text-coal-600">
                  SHA-256 · tamper-evident
                </div>
              </div>
            )}
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-6 border-t hairline pt-4">
            <Gauge
              value={reviewer.score}
              label={reviewer.score.toFixed(0)}
              sublabel="reviewer score"
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
              value={reviewer.evidence_coverage * 100}
              label={`${(reviewer.evidence_coverage * 100).toFixed(0)}%`}
              sublabel="evidence used"
              colour="#34d399"
              size={84}
            />
            <Gauge
              value={reviewer.confidence * 100}
              label={reviewer.confidence.toFixed(2)}
              sublabel="confidence"
              colour="#a78bfa"
              size={84}
            />

            <div className="min-w-[220px] flex-1">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-coal-500">
                Work done per agent
              </div>
              <BarRows
                data={analysis.agents
                  .filter((a) => a.durationMs != null)
                  .map((a) => ({
                    label: a.name.replace(/_/g, ' '),
                    value: (a.durationMs ?? 0) / 1000,
                  }))}
                colour="#60a5fa"
                formatValue={(v) => v.toFixed(1)}
                unit="s"
              />
            </div>
          </div>

          <div className="mt-5 grid gap-3 border-t hairline pt-4 sm:grid-cols-4">
            <Metric label="Evidence coverage" value={`${(reviewer.evidence_coverage * 100).toFixed(0)}%`} />
            <Metric label="Citation validity" value={`${(reviewer.citation_validity * 100).toFixed(0)}%`} />
            <Metric label="Agent agreement" value={`${(reviewer.agent_agreement * 100).toFixed(0)}%`} />
            <Metric
              label="Data freshness"
              value={reviewer.data_freshness_ok ? 'Current' : 'Stale'}
              tone={reviewer.data_freshness_ok ? undefined : 'warn'}
            />
          </div>

          {reviewer.reasoning && (
            <p className="mt-4 border-t hairline pt-4 text-xs leading-relaxed text-coal-400">
              {reviewer.reasoning}
            </p>
          )}
        </div>
      )}

      {analysis.summary && (
        <div className="glass p-5 sm:p-6">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
            Analysis
          </h3>
          <div className="mt-3 space-y-1 text-sm leading-relaxed text-coal-200">
            {analysis.summary.split('\n').map((line, i) => (
              <SummaryLine key={i} line={line} />
            ))}
          </div>
        </div>
      )}

      {reviewer && reviewer.concerns.length > 0 && (
        <div className="glass border-amber-500/20 p-5">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.12em] text-amber-400">
            Reviewer concerns
          </h3>
          <ul className="mt-2.5 space-y-1.5">
            {reviewer.concerns.map((concern, i) => (
              <li key={i} className="text-xs leading-relaxed text-amber-200/70">
                • {concern}
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.conflicts.length > 0 && (
        <div className="glass border-fire-500/20 p-5">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.12em] text-fire-400">
            Disagreement between agents
          </h3>
          <ul className="mt-2.5 space-y-1.5">
            {analysis.conflicts.map((conflict, i) => (
              <li key={i} className="text-xs text-coal-300">
                • {conflict}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-coal-500">
            Surfaced rather than resolved. A conflict is information, not an error.
          </p>
        </div>
      )}

      <p className="px-1 text-[11px] leading-relaxed text-coal-600">
        Fire DEX provides AI-assisted analytical information for educational and research
        purposes. It does not provide guaranteed financial returns or personalized financial
        advice.
      </p>
    </section>
  )
}

function SummaryLine({ line }: { line: string }) {
  const trimmed = line.trim()
  if (!trimmed) return <div className="h-2" />

  if (trimmed.startsWith('**') && trimmed.endsWith('**')) {
    return (
      <div className="pt-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-fire-300">
        {trimmed.replace(/\*\*/g, '')}
      </div>
    )
  }

  // Interpretations are wrapped in underscores by the summary builder, so
  // opinion stays visually distinct from measurement even in the final text.
  if (trimmed.startsWith('- _') && trimmed.endsWith('_')) {
    return (
      <div className="pl-3 text-coal-400">
        <span className="italic">{trimmed.slice(3, -1)}</span>
      </div>
    )
  }

  if (trimmed.startsWith('- ')) {
    return <div className="pl-3 text-coal-200">{trimmed.slice(2)}</div>
  }

  return <div>{trimmed}</div>
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const styles: Record<string, string> = {
    APPROVED: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    REANALYZE: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    REJECTED: 'bg-red-500/15 text-red-400 border-red-500/30',
  }
  return (
    <span
      className={`rounded-lg border px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${styles[verdict] ?? styles.REJECTED}`}
    >
      {verdict}
    </span>
  )
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'warn'
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.1em] text-coal-600">{label}</div>
      <div
        className={`mt-0.5 font-mono text-sm ${tone === 'warn' ? 'text-amber-400' : 'text-coal-200'}`}
      >
        {value}
      </div>
    </div>
  )
}
