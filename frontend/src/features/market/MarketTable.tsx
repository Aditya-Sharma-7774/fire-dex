import { useEffect, useState } from 'react'

import { TokenIcon } from '../../components/ui/TokenIcon'
import type { PriceResponse, TokenConfigResponse } from '../../services/api'
import { api } from '../../services/api'
import { changeColour, formatChange, formatCompact, formatPrice } from './format'
import { usePriceDirection, usePrices } from './useMarket'

/**
 * Live market table.
 *
 * Prices update every 20 seconds and each row flashes green or red on
 * change, so movement is visible without watching the numbers. The flash is
 * driven by an actual value comparison -- it is a signal, not decoration.
 */
export function MarketTable() {
  const [tokens, setTokens] = useState<TokenConfigResponse[]>([])
  const { data: prices, error, updatedAt } = usePrices()

  useEffect(() => {
    // The token list is configuration, not market data: it changes when we
    // deploy, not every 20 seconds. One fetch is enough.
    api
      .tokens('ethereum')
      .then(setTokens)
      .catch(() => setTokens([]))
  }, [])

  const rows = tokens.filter((t) => t.coingecko_id)

  return (
    <section className="mt-14">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">
          Live Market
        </h2>
        <div className="flex items-center gap-2 text-[11px] text-coal-500">
          {error ? (
            <span className="text-amber-400">Refresh failed — showing last known prices</span>
          ) : (
            <>
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
              </span>
              <span>{updatedAt ? 'Live · updates every 30s' : 'Connecting…'}</span>
            </>
          )}
        </div>
      </div>

      <div className="glass overflow-hidden">
        {/* Horizontal scroll lives on the table container, so the page body
            never scrolls sideways on a narrow screen. */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b hairline text-[10px] uppercase tracking-[0.12em] text-coal-500">
                <th className="px-4 py-3 text-left font-medium">Asset</th>
                <th className="px-4 py-3 text-right font-medium">Price</th>
                <th className="px-4 py-3 text-right font-medium">24h</th>
                <th className="hidden px-4 py-3 text-right font-medium sm:table-cell">
                  Market Cap
                </th>
                <th className="hidden px-4 py-3 text-right font-medium md:table-cell">
                  Volume 24h
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0
                ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.map((token) => (
                    <MarketRow
                      key={token.symbol}
                      token={token}
                      price={prices?.[token.coingecko_id ?? ''] ?? null}
                    />
                  ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

function MarketRow({
  token,
  price,
}: {
  token: TokenConfigResponse
  price: PriceResponse | null
}) {
  const direction = usePriceDirection(price?.usd)

  return (
    <tr
      className={`border-b border-white/[0.04] transition-colors duration-500 last:border-0 ${
        direction === 'up'
          ? 'bg-emerald-500/[0.07]'
          : direction === 'down'
            ? 'bg-red-500/[0.07]'
            : 'hover:bg-white/[0.02]'
      }`}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <TokenIcon symbol={token.symbol} size="sm" />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-coal-100">{token.symbol}</span>
              {token.is_stablecoin && (
                <span className="rounded bg-blue-500/10 px-1 py-px text-[9px] font-medium uppercase text-blue-400">
                  Stable
                </span>
              )}
            </div>
            <div className="truncate text-[11px] text-coal-500">{token.name}</div>
          </div>
        </div>
      </td>

      <td className="px-4 py-3 text-right">
        {price ? (
          <span
            className={`font-mono text-sm transition-colors duration-500 ${
              direction === 'up'
                ? 'text-emerald-300'
                : direction === 'down'
                  ? 'text-red-300'
                  : 'text-coal-100'
            }`}
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {formatPrice(price.usd)}
          </span>
        ) : (
          <span className="text-xs text-coal-600">unavailable</span>
        )}
        {price?.is_stale && (
          <div className="text-[9px] uppercase tracking-wide text-amber-500">stale</div>
        )}
      </td>

      <td className="px-4 py-3 text-right">
        {price?.change_24h != null ? (
          <span
            className={`inline-flex items-center gap-0.5 font-mono text-xs ${changeColour(price.change_24h)}`}
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            <span aria-hidden="true">{price.change_24h > 0 ? '▲' : price.change_24h < 0 ? '▼' : ''}</span>
            {formatChange(price.change_24h)}
          </span>
        ) : (
          <span className="text-xs text-coal-600">—</span>
        )}
      </td>

      <td className="hidden px-4 py-3 text-right font-mono text-xs text-coal-400 sm:table-cell">
        {formatCompact(price?.market_cap)}
      </td>
      <td className="hidden px-4 py-3 text-right font-mono text-xs text-coal-400 md:table-cell">
        {formatCompact(price?.volume_24h)}
      </td>
    </tr>
  )
}

function SkeletonRow() {
  return (
    <tr className="border-b border-white/[0.04] last:border-0">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 animate-shimmer rounded-lg" />
          <div className="space-y-1.5">
            <div className="h-3 w-12 animate-shimmer rounded" />
            <div className="h-2 w-20 animate-shimmer rounded" />
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="ml-auto h-3 w-16 animate-shimmer rounded" />
      </td>
      <td className="px-4 py-3">
        <div className="ml-auto h-3 w-12 animate-shimmer rounded" />
      </td>
      <td className="hidden px-4 py-3 sm:table-cell">
        <div className="ml-auto h-3 w-16 animate-shimmer rounded" />
      </td>
      <td className="hidden px-4 py-3 md:table-cell">
        <div className="ml-auto h-3 w-16 animate-shimmer rounded" />
      </td>
    </tr>
  )
}
