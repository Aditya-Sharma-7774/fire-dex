import { useEffect, useState } from 'react'

import { ErrorBoundary } from './components/ErrorBoundary'
import { Header } from './components/Header'
import { CHAIN_LIST } from './config/chains'
import { FireAiPage } from './features/ai/FireAiPage'
import { HistoryPage } from './features/history/HistoryPage'
import { MarketTable } from './features/market/MarketTable'
import { PriceChart } from './features/market/PriceChart'
import { BalanceCard } from './features/portfolio/BalanceCard'
import { HoldingsPanel } from './features/portfolio/HoldingsPanel'
import { WatchAddressPanel } from './features/portfolio/WatchAddressPanel'
import { isMockWalletRequested } from './features/wallet/devMockWallet'
import { WalletAlerts } from './features/wallet/WalletAlerts'
import { useWallet } from './features/wallet/WalletContext'
import { api, ApiError, type HealthResponse } from './services/api'

/**
 * The application shell: wallet state, backend reachability and the three tabs.
 *
 * Everything shown is either real or explicitly marked as unavailable.
 * There are no placeholder balances, no sample prices and no mock charts.
 */
export type Tab = 'dashboard' | 'fire-ai' | 'history'

export default function App() {
  const [tab, setTab] = useState<Tab>('dashboard')
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
      <Header
        health={health}
        healthError={healthError}
        loading={loading}
        tab={tab}
        onTabChange={setTab}
      />
      <WalletAlerts />

      <main className="relative mx-auto w-full max-w-7xl flex-1 px-4 py-10 sm:px-6 sm:py-12">
        {/* One boundary per page, keyed on the tab so switching away from a
            broken page clears the error rather than stranding the user. */}
        {tab === 'dashboard' && (
          <ErrorBoundary section="the dashboard" resetKey={tab}>
            <Hero />

            <div className="mt-10 sm:mt-12">
              <ErrorBoundary section="your balance">
                <BalanceCard />
              </ErrorBoundary>
            </div>

            <ErrorBoundary section="your holdings">
              <HoldingsPanel />
            </ErrorBoundary>
            <ErrorBoundary section="address tracking">
              <WatchAddressPanel />
            </ErrorBoundary>
            <ErrorBoundary section="the price chart">
              <PriceChart symbol="ETH" />
            </ErrorBoundary>
            <ErrorBoundary section="the market table">
              <MarketTable />
            </ErrorBoundary>
            <ChainStrip />
          </ErrorBoundary>
        )}

        {tab === 'fire-ai' && (
          <ErrorBoundary section="Fire AI" resetKey={tab}>
            <FireAiPage />
          </ErrorBoundary>
        )}
        {tab === 'history' && (
          <ErrorBoundary section="history" resetKey={tab}>
            <HistoryPage />
          </ErrorBoundary>
        )}
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
    <section className="animate-fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b hairline pb-5">
        <div>
          <h1 className="text-3xl font-bold leading-none tracking-tight sm:text-4xl">
            Multi-Chain <span className="fire-text-animated">Smart Wallet</span>
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-coal-400">
            Live balances and prices, analysed by specialist agents that must cite their
            evidence.
          </p>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-coal-500">
          <span className="relative flex h-1.5 w-1.5">
            <span
              className={`absolute inline-flex h-full w-full rounded-full opacity-60 ${
                status === 'connected' ? 'animate-ping bg-emerald-400' : 'bg-coal-600'
              }`}
            />
            <span
              className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
                status === 'connected' ? 'bg-emerald-400' : 'bg-coal-600'
              }`}
            />
          </span>
          {status === 'connected' ? 'Wallet connected' : 'Wallet not connected'}
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */

function ChainStrip() {
  const { chain: active, switchToChain, status } = useWallet()

  return (
    <section className="mt-12">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[11px] uppercase tracking-[0.12em] text-coal-600">
          Networks
        </span>

        {CHAIN_LIST.map((chain) => {
          const selected = active?.id === chain.id
          const selectable = chain.isActive && status === 'connected'

          // MetaMask cannot switch to Solana or Bitcoin; they are read by
          // address, so their chip goes to the tracker instead.
          if (chain.family !== 'evm') {
            return (
              <a
                key={chain.id}
                href="#track-address"
                title={`Track a ${chain.name} address`}
                className="flex items-center gap-1.5 rounded-full border hairline px-2.5 py-1 text-[11px] text-coal-300 transition-all hover:border-fire-500/25 hover:bg-white/[0.04]"
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: chain.color }} />
                {chain.name}
                <span className="text-coal-600">by address</span>
              </a>
            )
          }

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
                  : 'Planned for a later phase'
              }
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-all ${
                selected
                  ? 'border-fire-500/40 bg-fire-500/10 text-fire-300'
                  : chain.isActive
                    ? 'hairline text-coal-300 hover:border-fire-500/25 hover:bg-white/[0.04]'
                    : 'hairline text-coal-600'
              } disabled:cursor-not-allowed`}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: chain.isActive ? chain.color : '#3e3e45' }}
              />
              {chain.name}
              {chain.isTestnet && <span className="text-amber-500/80">test</span>}
              {!chain.isActive && <span className="text-coal-700">soon</span>}
            </button>
          )
        })}
      </div>
    </section>
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
