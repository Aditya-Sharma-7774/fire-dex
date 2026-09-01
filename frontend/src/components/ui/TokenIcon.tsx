interface TokenIconProps {
  symbol: string
  size?: 'sm' | 'md'
  /** Optional accent colour, e.g. from the chain config. */
  color?: string
}

/**
 * Placeholder token badge showing the symbol.
 *
 * Deliberately NOT truncated to three characters: "USDT" and "USDC" both
 * shorten to "USD", which makes two different assets look identical. The
 * font size steps down instead, so the full symbol always fits.
 *
 * Real token logos arrive with the asset pipeline later; until then a
 * legible symbol is better than a wrong or missing image.
 */
export function TokenIcon({ symbol, size = 'md', color }: TokenIconProps) {
  const box = size === 'sm' ? 'h-7 w-7' : 'h-8 w-8'

  // Step the type down as the symbol gets longer so it never overflows.
  const fontSize =
    symbol.length <= 3 ? 'text-[10px]' : symbol.length === 4 ? 'text-[9px]' : 'text-[8px]'

  return (
    <span
      title={symbol}
      className={`grid ${box} shrink-0 place-items-center rounded-lg font-bold tracking-tight ${fontSize}`}
      style={{
        background: color ? `${color}1f` : 'rgba(255,255,255,0.05)',
        border: color ? `1px solid ${color}55` : undefined,
        color: color ?? '#a0a0a9',
      }}
    >
      {symbol.slice(0, 5)}
    </span>
  )
}
