import { AnimatedNumber } from '../../components/ui/AnimatedNumber'
import { TokenIcon } from '../../components/ui/TokenIcon'
import type { TokenBalanceResponse } from '../../services/api'
import {
  changeColour,
  formatAmount,
  formatChange,
  formatPrice,
  formatUsd,
} from '../market/format'
import { usePortfolio } from '../market/useMarket'
import { useWallet } from '../wallet/WalletContext'

/**
 * The user's actual holdings, valued in USD.
 *
 * The honesty rules for this panel:
 *   - a holding we could not price shows "—", never $0
 *   - a balance we could not read shows "unavailable", never 0
 *   - a total is null, not zero, when nothing could be priced
 *   - stale prices are labelled
 */
export function HoldingsPanel() {
  const { status, address, chain, isUnsupportedNetwork } = useWallet()

  const readable = status === 'connected' && address && chain && !isUnsupportedNetwork
  const portfolio = usePortfolio(readable ? chain.id : null, readable ? address : null)

  if (!readable) return null

  const data = portfolio.data

  return (
    <section className="mt-14">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">
          Your Holdings
        </h2>
        <span className="text-[11px] text-coal-500">
          {chain.isTestnet ? 'Testnet assets have no real value' : 'Valued at live market prices'}
        </span>
      </div>

      {/* ---- total value ---- */}
      <div className="glass glass-hover p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-coal-400">
              Total portfolio value
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              {portfolio.loading && !data ? (
                <div className="h-10 w-48 animate-shimmer rounded-lg" />
              ) : portfolio.error ? (
                <span className="text-2xl font-bold text-red-400">Unavailable</span>
              ) : data?.total_value_usd != null ? (
                <>
                  <span className="text-3xl font-extrabold tracking-tight text-coal-50 sm:text-4xl">
                    <AnimatedNumber
                      value={data.total_value_usd.toFixed(2)}
                      decimals={2}
                      format={formatUsd}
                      className="tabular-nums"
                    />
                  </span>
                  <span className="text-sm font-medium text-coal-500">USD</span>
                </>
              ) : (
                <span className="text-2xl font-bold text-coal-400">—</span>
              )}
            </div>

            {data && (
              <p className="mt-1.5 text-[11px] text-coal-500">
                {data.priced_count} priced
                {data.unpriced_count > 0 && ` · ${data.unpriced_count} unpriced`}
                {data.contains_stale_prices && (
                  <span className="text-amber-500"> · includes stale prices</span>
                )}
              </p>
            )}

            {portfolio.error && (
              <p className="mt-1.5 max-w-md text-[11px] text-red-300/70">{portfolio.error}</p>
            )}
          </div>

          {chain.isTestnet && (
            <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2">
              <p className="text-[11px] leading-relaxed text-amber-300">
                Sepolia is a test network.
                <br />
                These assets are worthless.
              </p>
            </div>
          )}
        </div>

        {/* ---- holdings list ---- */}
        {data && data.balances.length > 0 && (
          <div className="mt-6 space-y-1 border-t hairline pt-4">
            {data.balances.map((balance) => (
              <HoldingRow key={`${balance.chain}-${balance.symbol}`} balance={balance} />
            ))}
          </div>
        )}

        {data && data.balances.length === 0 && (
          <p className="mt-6 border-t hairline pt-4 text-sm text-coal-500">
            No tracked tokens held by this address on {chain.name}.
          </p>
        )}
      </div>
    </section>
  )
}

function HoldingRow({ balance }: { balance: TokenBalanceResponse }) {
  const unreadable = balance.formatted === 'unavailable'

  return (
    <div className="flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors hover:bg-white/[0.03]">
      <TokenIcon symbol={balance.symbol} />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-semibold text-coal-100">{balance.symbol}</span>
          {balance.is_native && (
            <span className="rounded bg-fire-500/10 px-1 py-px text-[9px] font-medium uppercase text-fire-400">
              Native
            </span>
          )}
        </div>
        <div className="truncate text-[11px] text-coal-500">{balance.name}</div>
      </div>

      <div className="shrink-0 text-right">
        <div
          className={`font-mono text-sm ${unreadable ? 'text-amber-400' : 'text-coal-100'}`}
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {formatAmount(balance.formatted)}
        </div>
        <div className="text-[11px] text-coal-500">
          {balance.price_usd != null ? formatPrice(balance.price_usd) : 'no price'}
        </div>
      </div>

      <div className="hidden w-24 shrink-0 text-right sm:block">
        <div
          className="font-mono text-sm text-coal-100"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {/* null value renders as a dash, never as $0.00 */}
          {balance.value_usd != null ? formatUsd(balance.value_usd) : '—'}
        </div>
        {balance.change_24h != null && (
          <div className={`text-[11px] ${changeColour(balance.change_24h)}`}>
            {formatChange(balance.change_24h)}
          </div>
        )}
        {balance.price_is_stale && (
          <div className="text-[9px] uppercase text-amber-500">stale</div>
        )}
      </div>
    </div>
  )
}
