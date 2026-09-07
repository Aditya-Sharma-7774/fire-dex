import { useState } from 'react'

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
  basis_technical?: string
  reviewer_technical?: string
  trust_technical?: string
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

      {/* ---- explanations, each flippable to a technical reading ---- */}
      <div className="grid gap-4 lg:grid-cols-3">
        <FlipExplanation
          title="On what basis"
          note="what drove the agents"
          plain={suggestion.basis_summary}
          technical={suggestion.basis_technical}
        />
        <FlipExplanation
          title="Why that rating"
          note="the reviewer's score"
          plain={suggestion.reviewer_explanation}
          technical={suggestion.reviewer_technical}
        />
        <FlipExplanation
          title="How much to trust it"
          note="honest limitations"
          plain={suggestion.trust_summary}
          technical={suggestion.trust_technical}
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

/**
 * An explanation card that flips between two readings of the same finding.
 *
 * Front: plain language, for someone who has never heard of RSI.
 * Back:  the same finding named precisely, for someone who trades.
 *
 * They are two REGISTERS, never two conclusions. If the technical side
 * says the evidence is thin, the plain side says so too — the vocabulary
 * changes, the finding does not.
 *
 * Implemented with a real 3D flip because the gesture communicates
 * "same card, other side" in a way a tab or a toggle does not.
 */
function FlipExplanation({
  title,
  note,
  plain,
  technical,
}: {
  title: string
  note: string
  plain: string
  technical?: string
}) {
  const [flipped, setFlipped] = useState(false)
  const hasTechnical = Boolean(technical?.trim())

  return (
    <div className="[perspective:1200px]">
      <div
        className="relative transition-transform duration-500 [transform-style:preserve-3d]"
        style={{
          transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
          minHeight: '190px',
        }}
      >
        {/* front — plain */}
        <Face
          hidden={flipped}
          title={title}
          note={note}
          body={plain}
          badge="In plain words"
          badgeClass="bg-emerald-500/10 text-emerald-400"
          action={hasTechnical ? 'Show the technical version →' : undefined}
          onFlip={() => setFlipped(true)}
        />

        {/* back — technical */}
        <Face
          back
          hidden={!flipped}
          title={title}
          note="for a professional reader"
          body={technical ?? ''}
          badge="Technical"
          badgeClass="bg-blue-500/10 text-blue-400"
          action="← Back to plain words"
          onFlip={() => setFlipped(false)}
          mono
        />
      </div>
    </div>
  )
}

function Face({
  title,
  note,
  body,
  badge,
  badgeClass,
  action,
  onFlip,
  back,
  hidden,
  mono,
}: {
  title: string
  note: string
  body: string
  badge: string
  badgeClass: string
  action?: string
  onFlip: () => void
  back?: boolean
  hidden: boolean
  mono?: boolean
}) {
  return (
    <div
      className={`glass flex flex-col p-4 [backface-visibility:hidden] ${back ? 'absolute inset-0' : ''}`}
      style={{ transform: back ? 'rotateY(180deg)' : undefined }}
      // Keep the hidden face out of the tab order and off the screen
      // reader, or every card would be announced twice.
      aria-hidden={hidden}
      {...(hidden ? { inert: '' } : {})}
    >
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-coal-400">
          {title}
        </h3>
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-medium ${badgeClass}`}>
          {badge}
        </span>
      </div>

      <p
        className={`flex-1 leading-relaxed text-coal-300 ${mono ? 'font-mono text-[10px]' : 'text-[12px]'}`}
      >
        {body || <span className="text-coal-600">Not available.</span>}
      </p>

      <div className="mt-3 flex items-center justify-between gap-2 border-t hairline pt-2">
        <span className="text-[10px] text-coal-600">{note}</span>
        {action && (
          <button
            type="button"
            onClick={onFlip}
            className="shrink-0 rounded-lg px-2 py-1 text-[10px] font-medium text-fire-400 transition-colors hover:bg-fire-500/10"
          >
            {action}
          </button>
        )}
      </div>
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
