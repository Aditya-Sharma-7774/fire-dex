import { useEffect, useState } from 'react'

import { Header } from './components/Header'
import { CHAIN_LIST } from './config/chains'
import { MarketTable } from './features/market/MarketTable'
import { BalanceCard } from './features/portfolio/BalanceCard'
import { HoldingsPanel } from './features/portfolio/HoldingsPanel'
import { isMockWalletRequested } from './features/wallet/devMockWallet'
import { WalletAlerts } from './features/wallet/WalletAlerts'
import { useWallet } from './features/wallet/WalletContext'
import { api, ApiError, API_BASE_URL, type HealthResponse } from './services/api'

/**
 * Milestone 2 dashboard.
 *
 * Everything shown is either real or explicitly marked as not built yet.
 * There are no placeholder balances, no sample prices and no mock charts.
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
    <div id="top" className="relative flex min-h-screen flex-col">
      <AmbientBackground />

      <MockWalletBanner />
      <Header health={health} healthError={healthError} loading={loading} />
      <WalletAlerts />

      <main className="relative mx-auto w-full max-w-7xl flex-1 px-4 py-10 sm:px-6 sm:py-12">
        <Hero />

        <div className="mt-10 sm:mt-12">
          <BalanceCard />
        </div>

        <HoldingsPanel />
        <MarketTable />
        <StatusGrid health={health} healthError={healthError} loading={loading} />
        <ChainGrid />
        <PipelinePreview />
      </main>

      <Footer />
    </div>
  )
}

/* ------------------------------------------------------------------ */

/**
 * Loud, permanent banner while the development mock wallet is active.
 *
 * Non-dismissible on purpose. A mock that can be hidden is a mock that can
 * be mistaken for the real thing in a screenshot or a demo.
 */
function MockWalletBanner() {
  if (!isMockWalletRequested()) return null

  return (
    <div className="relative z-50 bg-fire-600 px-4 py-1.5 text-center">
      <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-white">
        ⚠ Development mock wallet active — the wallet is simulated. Balances are still real
        on-chain data.
      </p>
    </div>
  )
}

/**
 * Slow-drifting glows behind the page.
 *
 * Fixed and pointer-events-none so they never interfere with scrolling or
 * clicking. The grid sits on top of them.
 */
function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className="grid-bg absolute inset-0" />
      <div className="absolute -left-32 top-16 h-96 w-96 animate-float-slow rounded-full bg-fire-600/[0.07] blur-3xl" />
      <div
        className="absolute -right-24 top-1/3 h-80 w-80 animate-float rounded-full bg-fire-500/[0.05] blur-3xl"
        style={{ animationDelay: '2s' }}
      />
    </div>
  )
}

function Hero() {
  const { status } = useWallet()

  return (
    <section className="animate-fade-up text-center">
      <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-fire-500/20 bg-fire-500/[0.07] px-3.5 py-1.5">
        <span className="h-1.5 w-1.5 animate-pulse-slow rounded-full bg-fire-400" />
        <span className="text-xs font-medium tracking-wide text-fire-300">
          {status === 'connected' ? 'Wallet connected · Live chain data' : 'Milestone 2 · Wallet'}
        </span>
      </div>

      <h1 className="mx-auto max-w-4xl text-4xl font-extrabold leading-[1.1] tracking-tight sm:text-5xl md:text-6xl">
        Agentic AI-Powered
        <br />
        <span className="fire-text-animated">Multi-Chain Smart Wallet</span>
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
    <section className="stagger mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
  const { chain: activeChain, switchToChain, status } = useWallet()

  return (
    <section className="mt-14">
      <SectionHeading title="Supported Networks" note="Read mainnet · write testnet" />

      {/*
        Three columns at lg, not five. At five, "BNB Smart Chain" was being
        truncated to "BNB Smart Cha…" -- a name being cut off in a wallet is
        exactly the kind of ambiguity to avoid.
      */}
      <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {CHAIN_LIST.map((chain) => {
          const selected = activeChain?.id === chain.id
          const selectable = chain.isActive && status === 'connected'

          return (
            <button
              key={chain.id}
              type="button"
              disabled={!selectable}
              onClick={() => void switchToChain(chain.id)}
              title={
                chain.isActive
                  ? status === 'connected'
                    ? `Switch to ${chain.name}`
                    : 'Connect a wallet to switch networks'
                  : 'Planned for a later milestone'
              }
              className={`glass p-4 text-left transition-all duration-300 ${
                selected
                  ? 'border-fire-500/40 bg-fire-500/[0.06] shadow-glow'
                  : selectable
                    ? 'hover:-translate-y-0.5 hover:border-fire-500/25 hover:bg-white/[0.05]'
                    : 'opacity-60'
              } disabled:cursor-not-allowed`}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[11px] font-bold"
                  style={{
                    background: `${chain.color}1f`,
                    border: `1px solid ${chain.color}55`,
                    color: chain.color,
                  }}
                >
                  {chain.shortName.slice(0, 3).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold leading-tight">{chain.name}</div>
                  <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-coal-500">
                    {chain.family}
                    {chain.chainId !== null && ` · ${chain.chainId}`}
                  </div>
                </div>
                {selected && <span className="shrink-0 text-xs text-fire-400">●</span>}
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {chain.isTestnet && (
                  <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                    Testnet
                  </span>
                )}
                <span
                  className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                    chain.isActive
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : 'bg-coal-800 text-coal-400'
                  }`}
                >
                  {chain.isActive ? 'Active' : 'Planned'}
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

const PIPELINE = ['Evidence', 'Agents', 'Orchestrator', 'Reviewer', 'Fire Auditor', 'SHA-256']

function PipelinePreview() {
  return (
    <section className="mt-14">
      <SectionHeading title="Analysis Pipeline" note="Built in phases 5–8" />

      <div className="glass p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-3">
          {PIPELINE.map((step, index) => (
            <div key={step} className="flex items-center gap-2">
              <div className="rounded-xl border hairline bg-coal-900/60 px-3 py-2 text-xs font-medium text-coal-300 transition-colors hover:border-fire-500/25 hover:text-coal-100">
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
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">{title}</h2>
      <span className="shrink-0 text-[11px] text-coal-500">{note}</span>
    </div>
  )
}

function Footer() {
  return (
    <footer className="relative border-t hairline">
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
