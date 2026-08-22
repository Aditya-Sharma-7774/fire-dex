import { useEffect, useState } from 'react'

import { Header } from './components/Header'
import { CHAIN_LIST } from './config/chains'
import { api, ApiError, API_BASE_URL, type HealthResponse } from './services/api'

/**
 * Milestone 1 shell.
 *
 * The page proves three things at a glance:
 *   1. the frontend builds and renders,
 *   2. the backend is reachable (live /health poll, not a hard-coded badge),
 *   3. the fire theme and layout language are settled.
 *
 * Everything shown as "planned" is honest -- no fake balances, no fake
 * prices, no placeholder charts pretending to be data.
 */
export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const check = async () => {
      try {
        const result = await api.health()
        if (cancelled) return
        setHealth(result)
        setHealthError(null)
      } catch (error) {
        if (cancelled) return
        setHealth(null)
        setHealthError(
          error instanceof ApiError ? error.message : 'Unexpected error contacting the backend',
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void check()
    const interval = setInterval(check, 10_000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="grid-bg flex min-h-full flex-col">
      <Header health={health} healthError={healthError} loading={loading} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-10 sm:px-6 sm:py-14">
        <Hero />
        <StatusGrid health={health} healthError={healthError} loading={loading} />
        <ChainGrid />
        <PipelinePreview />
      </main>

      <Footer />
    </div>
  )
}

/* ------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="animate-fade-up text-center">
      <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-fire-500/20 bg-fire-500/[0.07] px-3.5 py-1.5">
        <span className="h-1.5 w-1.5 animate-pulse-slow rounded-full bg-fire-400" />
        <span className="text-xs font-medium tracking-wide text-fire-300">
          Milestone 1 · Foundation
        </span>
      </div>

      <h1 className="mx-auto max-w-4xl text-4xl font-extrabold leading-[1.1] tracking-tight sm:text-5xl md:text-6xl">
        Agentic AI-Powered
        <br />
        <span className="fire-text">Multi-Chain Smart Wallet</span>
      </h1>

      <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-coal-400">
        A multi-chain wallet with an auditable multi-agent intelligence layer. Market, technical,
        portfolio and on-chain evidence is combined into explainable decision support — every
        result signed, hashed and independently verifiable.
      </p>
    </section>
  )
}

/* ------------------------------------------------------------------ */

function StatusGrid({
  health,
  healthError,
  loading,
}: {
  health: HealthResponse | null
  healthError: string | null
  loading: boolean
}) {
  return (
    <section className="mt-12 grid gap-4 sm:mt-16 sm:grid-cols-2 lg:grid-cols-3">
      <StatusCard
        label="Backend API"
        value={loading ? 'Checking…' : healthError ? 'Offline' : 'Online'}
        tone={loading ? 'neutral' : healthError ? 'bad' : 'good'}
        detail={healthError ?? API_BASE_URL}
      />
      <StatusCard
        label="Safety Mode"
        value={health ? health.mode.toUpperCase() : '—'}
        tone={health?.mode === 'production' ? 'warn' : 'good'}
        detail={
          health?.mode === 'development'
            ? 'No mainnet writes permitted'
            : health?.mode === 'testnet'
              ? 'Sepolia signing enabled'
              : 'Waiting for backend'
        }
      />
      <StatusCard
        label="Version"
        value={health ? `v${health.version}` : '—'}
        tone="neutral"
        detail={health ? health.app : 'Waiting for backend'}
      />
    </section>
  )
}

type Tone = 'good' | 'bad' | 'warn' | 'neutral'

const TONE_STYLES: Record<Tone, { text: string; dot: string }> = {
  good: { text: 'text-emerald-400', dot: 'bg-emerald-400' },
  bad: { text: 'text-red-400', dot: 'bg-red-500' },
  warn: { text: 'text-amber-400', dot: 'bg-amber-400' },
  neutral: { text: 'text-coal-200', dot: 'bg-coal-500' },
}

function StatusCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail: string
  tone: Tone
}) {
  const styles = TONE_STYLES[tone]

  return (
    <div className="glass glass-hover p-5">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} />
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
          {label}
        </span>
      </div>
      <div className={`mt-3 text-2xl font-bold tracking-tight ${styles.text}`}>{value}</div>
      <div className="mt-1.5 truncate font-mono text-[11px] text-coal-500" title={detail}>
        {detail}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

function ChainGrid() {
  return (
    <section className="mt-14">
      <SectionHeading
        title="Supported Networks"
        note="Read mainnet · write testnet"
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {CHAIN_LIST.map((chain) => (
          <div key={chain.id} className="glass glass-hover p-4">
            <div className="flex items-center gap-2.5">
              <span
                className="h-7 w-7 shrink-0 rounded-lg"
                style={{ background: `${chain.color}22`, border: `1px solid ${chain.color}55` }}
              />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{chain.name}</div>
                <div className="font-mono text-[10px] uppercase tracking-wider text-coal-500">
                  {chain.family}
                  {chain.chainId !== null && ` · ${chain.chainId}`}
                </div>
              </div>
            </div>

            <div className="mt-3 flex items-center gap-1.5">
              {chain.isTestnet && (
                <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                  Testnet
                </span>
              )}
              <span className="rounded-md bg-coal-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-coal-400">
                {chain.status === 'active' ? 'Active' : 'Milestone 2+'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

const PIPELINE = [
  'Evidence',
  'Agents',
  'Orchestrator',
  'Reviewer',
  'Fire Auditor',
  'SHA-256',
] as const

function PipelinePreview() {
  return (
    <section className="mt-14">
      <SectionHeading title="Analysis Pipeline" note="Built in milestones 5–8" />

      <div className="glass p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-3">
          {PIPELINE.map((step, index) => (
            <div key={step} className="flex items-center gap-2">
              <div className="rounded-xl border hairline bg-coal-900/60 px-3 py-2 text-xs font-medium text-coal-300">
                {step}
              </div>
              {index < PIPELINE.length - 1 && (
                <span className="text-coal-700" aria-hidden="true">
                  →
                </span>
              )}
            </div>
          ))}
        </div>

        <p className="mt-5 border-t hairline pt-4 text-xs leading-relaxed text-coal-500">
          Agents never fetch data and never produce numbers. Deterministic collectors build a
          typed, timestamped evidence bundle; agents may only emit observations and interpretations
          that cite evidence IDs. A validator rejects any output containing an untraceable figure.
        </p>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

function SectionHeading({ title, note }: { title: string; note: string }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-4">
      <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">{title}</h2>
      <span className="shrink-0 text-[11px] text-coal-500">{note}</span>
    </div>
  )
}

function Footer() {
  return (
    <footer className="border-t hairline">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <p className="text-center text-[11px] leading-relaxed text-coal-500">
          Fire DEX provides AI-assisted analytical information for educational and research
          purposes. It does not provide guaranteed financial returns or personalized financial
          advice.
        </p>
      </div>
    </footer>
  )
}
