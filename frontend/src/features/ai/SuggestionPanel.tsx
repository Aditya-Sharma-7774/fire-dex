import { Gauge } from '../../components/charts/Charts'

/**
 * The Suggestion Agent's output.
 *
 * Three things a user actually wants to know, in order:
 *   1. What do the indicators currently agree on?  (the signal)
 *   2. How well supported is any of this?          (groundedness)
 *   3. Why did the agents and the reviewer say what they said?
 *
 * The signal and groundedness are COMPUTED, not model opinions, and the
 * panel says so explicitly — otherwise a reader would reasonably assume the
 * AI decided to say "Buy", which is exactly the impression this project
 * exists to avoid creating.
 */

export interface Suggestion {
  signal: string | null
  signal_score: number | null
  signal_basis: string[]
  buy_votes: number
  sell_votes: number
  neutral_votes: number
  groundedness: number
  groundedness_band: string
  claim_support: number
  evidence_use: number
  anchoring: number
  basis_summary: string
  reviewer_explanation: string
  trust_summary: string
  key_drivers: string[]
  caveats: string[]
  disclaimer: string
}

const SIGNAL_STYLE: Record<string, { text: string; bg: string; ring: string; colour: string }> = {
  STRONG_BUY: {
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    ring: 'ring-emerald-500/30',
    colour: '#34d399',
  },
  BUY: {
    text: 'text-emerald-400',
    bg: 'bg-emerald-500/[0.07]',
    ring: 'ring-emerald-500/20',
    colour: '#34d399',
  },
  NEUTRAL: {
    text: 'text-coal-300',
    bg: 'bg-white/[0.04]',
    ring: 'ring-white/10',
    colour: '#8a8a94',
  },
  SELL: {
    text: 'text-red-400',
    bg: 'bg-red-500/[0.07]',
    ring: 'ring-red-500/20',
    colour: '#f87171',
  },
  STRONG_SELL: {
    text: 'text-red-300',
    bg: 'bg-red-500/10',
    ring: 'ring-red-500/30',
    colour: '#f87171',
  },
}

const BAND_COLOUR: Record<string, string> = {
  strong: '#34d399',
  adequate: '#60a5fa',
  weak: '#fbbf24',
  poor: '#f87171',
}

export function SuggestionPanel({ suggestion }: { suggestion: Suggestion }) {
  const style = SIGNAL_STYLE[suggestion.signal ?? 'NEUTRAL'] ?? SIGNAL_STYLE.NEUTRAL
  const bandColour = BAND_COLOUR[suggestion.groundedness_band] ?? '#8a8a94'
  const totalVotes =
    suggestion.buy_votes + suggestion.sell_votes + suggestion.neutral_votes

  return (
    <section className="animate-fade-up space-y-4">
      {/* ---- signal + groundedness ---- */}
      <div className="glass overflow-hidden">
        <div className="flex flex-wrap items-center gap-6 p-5 sm:p-6">
          {/* the signal itself */}
          <div
            className={`rounded-2xl px-6 py-4 text-center ring-1 ${style.bg} ${style.ring}`}
          >
            <div className="text-[10px] uppercase tracking-[0.14em] text-coal-500">
              Indicator signal
            </div>
            <div className={`mt-1 text-2xl font-extrabold tracking-tight ${style.text}`}>
              {(suggestion.signal ?? 'NO SIGNAL').replace('_', ' ')}
            </div>
            {suggestion.signal_score != null && (
              <div className="mt-0.5 font-mono text-[11px] text-coal-500">
                {suggestion.signal_score > 0 ? '+' : ''}
                {suggestion.signal_score.toFixed(2)} on −1…+1
              </div>
            )}
          </div>

          {/* the vote breakdown that produced it */}
          <div className="min-w-[200px] flex-1">
            <div className="mb-2 text-[10px] uppercase tracking-wide text-coal-500">
              Indicator vote ({totalVotes} indicators)
            </div>
            <div className="flex h-3 overflow-hidden rounded-full bg-white/[0.04]">
              {suggestion.buy_votes > 0 && (
                <div
                  style={{ width: `${(suggestion.buy_votes / totalVotes) * 100}%` }}
                  className="bg-emerald-400"
                  title={`${suggestion.buy_votes} buy`}
                />
              )}
              {suggestion.neutral_votes > 0 && (
                <div
                  style={{ width: `${(suggestion.neutral_votes / totalVotes) * 100}%` }}
                  className="bg-coal-600"
                  title={`${suggestion.neutral_votes} neutral`}
                />
              )}
              {suggestion.sell_votes > 0 && (
                <div
                  style={{ width: `${(suggestion.sell_votes / totalVotes) * 100}%` }}
                  className="bg-red-400"
                  title={`${suggestion.sell_votes} sell`}
                />
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 text-[10px]">
              <span className="text-emerald-400">{suggestion.buy_votes} buy</span>
              <span className="text-coal-500">{suggestion.neutral_votes} neutral</span>
              <span className="text-red-400">{suggestion.sell_votes} sell</span>
            </div>
          </div>

          {/* groundedness */}
          <Gauge
            value={suggestion.groundedness * 100}
            label={suggestion.groundedness.toFixed(2)}
            sublabel={`groundedness · ${suggestion.groundedness_band}`}
            colour={bandColour}
            size={92}
          />
        </div>

        {/* the crucial framing */}
        <p className="border-t hairline bg-coal-900/40 px-5 py-3 text-[11px] leading-relaxed text-coal-500">
          <span className="font-semibold text-coal-400">This signal was computed, not decided by the AI.</span>{' '}
          It is a vote across {totalVotes} technical indicators using published thresholds — the
          same approach as a conventional technical rating. The language model explains it; it
          does not choose it.
        </p>
      </div>

      {/* ---- why: the vote basis ---- */}
      {suggestion.signal_basis.length > 0 && (
        <details className="glass group p-4" open>
          <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
            Why this signal — every vote
            <span className="ml-2 font-normal normal-case tracking-normal text-coal-600 group-open:hidden">
              (click to expand)
            </span>
          </summary>
          <div className="mt-3 space-y-1.5">
            {suggestion.signal_basis.map((basis, index) => {
              const isBuy = basis.includes(': BUY')
              const isSell = basis.includes(': SELL')
              return (
                <div key={index} className="flex items-start gap-2 text-[11px]">
                  <span
                    className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                      isBuy ? 'bg-emerald-400' : isSell ? 'bg-red-400' : 'bg-coal-600'
                    }`}
                  />
                  <span className="text-coal-300">{basis}</span>
                </div>
              )
            })}
          </div>
        </details>
      )}

      {/* ---- explanations ---- */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Explanation
          title="On what basis"
          note="what drove the agents"
          body={suggestion.basis_summary}
        />
        <Explanation
          title="Why that rating"
          note="the reviewer's score"
          body={suggestion.reviewer_explanation}
        />
        <Explanation
          title="How much to trust it"
          note="honest limitations"
          body={suggestion.trust_summary}
        />
      </div>

      {/* ---- drivers and caveats ---- */}
      {(suggestion.key_drivers.length > 0 || suggestion.caveats.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {suggestion.key_drivers.length > 0 && (
            <div className="glass p-4">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
                Key drivers
              </h3>
              {suggestion.key_drivers.map((driver, index) => (
                <p key={index} className="mt-1.5 text-[11px] leading-relaxed text-coal-300">
                  <span className="mr-1 text-fire-400">→</span>
                  {driver}
                </p>
              ))}
            </div>
          )}

          {suggestion.caveats.length > 0 && (
            <div className="glass p-4">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-amber-500">
                Caveats
              </h3>
              {suggestion.caveats.map((caveat, index) => (
                <p key={index} className="mt-1.5 text-[11px] leading-relaxed text-amber-200/70">
                  <span className="mr-1">⚠</span>
                  {caveat}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ---- groundedness breakdown ---- */}
      <div className="glass p-4">
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
          Groundedness breakdown
        </h3>
        <div className="grid gap-3 sm:grid-cols-3">
          <Component
            label="Claim support"
            value={suggestion.claim_support}
            note="claims fully traceable to evidence"
          />
          <Component
            label="Evidence use"
            value={suggestion.evidence_use}
            note="of the facts gathered, how many were cited"
          />
          <Component
            label="Anchoring"
            value={suggestion.anchoring}
            note="distinct evidence per claim"
          />
        </div>
        <p className="mt-3 border-t hairline pt-3 text-[10px] leading-relaxed text-coal-600">
          Groundedness measures whether what was <em>said</em> is supported by what was{' '}
          <em>known</em>. It is computed, not judged — asking a model to grade its own
          grounding would be circular.
        </p>
      </div>

      {/* ---- the disclaimer, unmissable ---- */}
      <div className="rounded-2xl border border-amber-500/25 bg-amber-500/[0.06] p-4">
        <p className="text-[11px] leading-relaxed text-amber-200/80">
          <span className="font-semibold uppercase tracking-wide text-amber-400">
            Not financial advice ·{' '}
          </span>
          {suggestion.disclaimer}
        </p>
      </div>
    </section>
  )
}

function Explanation({
  title,
  note,
  body,
}: {
  title: string
  note: string
  body: string
}) {
  return (
    <div className="glass p-4">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
          {title}
        </h3>
        <span className="text-[10px] text-coal-600">{note}</span>
      </div>
      <p className="text-[11px] leading-relaxed text-coal-300">
        {body || <span className="text-coal-600">Not available.</span>}
      </p>
    </div>
  )
}

function Component({
  label,
  value,
  note,
}: {
  label: string
  value: number
  note: string
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] text-coal-400">{label}</span>
        <span className="font-mono text-xs text-coal-200">{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.05]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-fire-600 to-fire-400 transition-[width] duration-700"
          style={{ width: `${Math.max(value * 100, 1)}%` }}
        />
      </div>
      <div className="mt-1 text-[9px] leading-tight text-coal-600">{note}</div>
    </div>
  )
}
