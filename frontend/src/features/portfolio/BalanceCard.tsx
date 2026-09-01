import { useEffect, useState } from 'react'

import { AnimatedNumber, TickingNumber } from '../../components/ui/AnimatedNumber'
import { explorerAddressUrl } from '../../config/chains'
import { usePortfolio } from '../market/useMarket'
import { shortenAddress } from '../wallet/provider'
import { useChainStatus } from '../wallet/useChainData'
import { useWallet } from '../wallet/WalletContext'

/**
 * The main balance panel.
 *
 * Every state here is explicit -- not connected, unsupported network,
 * loading, failed, and loaded. There is deliberately no state in which a
 * previously-fetched number is shown as though it were current.
 */
export function BalanceCard() {
  const { status, address, chain, isUnsupportedNetwork } = useWallet()

  const connected = status === 'connected' && address !== null
  const readable = connected && chain !== null && !isUnsupportedNetwork

  // Reads the native balance out of the portfolio rather than fetching it
  // separately. HoldingsPanel already loads the portfolio, and the API
  // client deduplicates identical in-flight GETs, so both components share
  // a single request instead of each issuing their own.
  const portfolio = usePortfolio(readable ? chain.id : null, readable ? address : null)
  const chainStatus = useChainStatus(readable ? chain.id : null)

  const native = portfolio.data?.balances.find((b) => b.is_native) ?? null
  const balance = {
    loading: portfolio.loading,
    error: portfolio.error,
    updatedAt: portfolio.updatedAt,
    refresh: portfolio.refresh,
    data: native,
  }

  if (!connected) return <DisconnectedCard />

  if (!readable) {
    return (
      <section className="glass animate-fade-up p-6 sm:p-7">
        <SectionLabel>Portfolio</SectionLabel>
        <p className="mt-4 text-sm text-coal-400">
          Balances are hidden while your wallet is on an unsupported network.
        </p>
      </section>
    )
  }

  return (
    <section className="glass glass-hover animate-fade-up overflow-hidden p-6 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <SectionLabel>Native balance</SectionLabel>

          <div className="mt-3 flex items-baseline gap-2">
            {balance.loading && !balance.data ? (
              <div className="h-10 w-44 animate-shimmer rounded-lg" />
            ) : balance.error ? (
              <span className="text-2xl font-bold text-red-400">Unavailable</span>
            ) : balance.data ? (
              <>
                <AnimatedNumber
                  value={balance.data.formatted}
                  className="text-4xl font-extrabold tracking-tight text-coal-50 sm:text-5xl"
                />
                <span className="text-lg font-semibold text-fire-400">{balance.data.symbol}</span>
              </>
            ) : null}
          </div>

          {balance.error && (
            <p className="mt-2 max-w-md text-xs leading-relaxed text-red-300/70">
              {balance.error}
            </p>
          )}

          {balance.data && (
            <p className="mt-2 font-mono text-[11px] text-coal-500">
              {balance.data.raw} wei
            </p>
          )}
        </div>

        {/* Live chain indicator. A block number that visibly advances is
            direct evidence to anyone watching that this is a real network
            connection, not a mock. */}
        <div className="shrink-0 text-right">
          <div className="flex items-center justify-end gap-1.5">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
            <span className="text-[10px] uppercase tracking-[0.12em] text-coal-500">Live</span>
          </div>

          {chainStatus.data?.block_number ? (
            <div className="mt-1.5">
              <div className="font-mono text-sm text-coal-300">
                #<TickingNumber value={chainStatus.data.block_number} />
              </div>
              <div className="text-[10px] text-coal-600">block height</div>
            </div>
          ) : (
            <div className="mt-1.5 h-4 w-20 animate-shimmer rounded" />
          )}
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-t hairline pt-4">
        <Detail label="Network">
          <span className="flex items-center gap-1.5">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: chain.color }}
            />
            {chain.name}
          </span>
        </Detail>

        <Detail label="Account">
          <a
            href={explorerAddressUrl(chain, address)}
            target="_blank"
            rel="noreferrer noopener"
            className="font-mono transition-colors hover:text-fire-300"
          >
            {shortenAddress(address, 6)} ↗
          </a>
        </Detail>

        <Detail label="Updated">
          {balance.updatedAt ? <RelativeTime timestamp={balance.updatedAt} /> : '—'}
        </Detail>

        <button
          type="button"
          onClick={() => void balance.refresh()}
          disabled={balance.loading}
          className="ml-auto rounded-lg border hairline px-2.5 py-1.5 text-[11px] text-coal-400 transition-colors hover:border-fire-500/30 hover:text-coal-200 disabled:opacity-50"
        >
          {balance.loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
    </section>
  )
}

function DisconnectedCard() {
  const { connect, status } = useWallet()

  return (
    <section className="glass animate-fade-up p-8 text-center sm:p-10">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-fire-500/20 to-fire-700/10 ring-1 ring-fire-500/20">
        <span className="text-2xl" aria-hidden="true">
          🔌
        </span>
      </div>

      <h2 className="mt-4 text-lg font-bold tracking-tight">Connect your wallet</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-coal-400">
        Fire DEX reads your public address to show balances. It never asks for, receives or stores a
        private key or seed phrase — your wallet keeps those and does all signing itself.
      </p>

      {status !== 'unavailable' && (
        <button
          type="button"
          onClick={() => void connect()}
          className="group relative mt-5 overflow-hidden rounded-xl bg-gradient-to-br from-fire-500 to-fire-700 px-5 py-2.5 text-sm font-semibold text-white shadow-glow transition-all hover:shadow-glow-lg"
        >
          <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
          <span className="relative">Connect MetaMask</span>
        </button>
      )}

      {status === 'unavailable' && (
        <p className="mt-5 text-sm text-amber-300">
          No wallet extension detected in this browser.
        </p>
      )}
    </section>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
      {children}
    </span>
  )
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-[0.1em] text-coal-600">{label}</div>
      <div className="mt-0.5 truncate text-xs text-coal-300">{children}</div>
    </div>
  )
}

/**
 * "12s ago", ticking on its own second by second.
 *
 * It re-renders itself rather than only updating when the parent refetches,
 * because a freshness indicator that is itself stale is worse than none.
 */
function RelativeTime({ timestamp }: { timestamp: number }) {
  const [, forceTick] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000))
  const text =
    seconds < 5 ? 'just now' : seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`

  return <span>{text}</span>
}
