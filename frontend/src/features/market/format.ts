/**
 * Display formatting for money and token amounts.
 *
 * Kept in one file so every figure on screen is formatted the same way, and
 * so the rules about what we will and will not show live in one place.
 */

/**
 * Format a USD price.
 *
 * Crypto prices span an enormous range -- PEPE trades around $0.000005 while
 * WBTC is in the tens of thousands. A fixed 2 decimal places would render
 * PEPE as "$0.00", which reads as worthless. Precision therefore scales with
 * magnitude.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value === 0) return '$0'

  const abs = Math.abs(value)

  if (abs >= 1000) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  if (abs >= 1) return `$${value.toFixed(2)}`
  if (abs >= 0.01) return `$${value.toFixed(4)}`
  if (abs >= 0.0001) return `$${value.toFixed(6)}`

  // Meme-coin territory. Plain decimals stay readable down to 1e-8 and are
  // far friendlier than "$5.12e-6" for a general audience, so we only fall
  // back to scientific notation below that.
  if (abs >= 1e-8) return `$${value.toFixed(8).replace(/0+$/, '')}`

  return `$${value.toExponential(2)}`
}

/** Format a USD portfolio or holding value. */
export function formatUsd(value: number | null | undefined): string {
  if (value == null) return '—'
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Compact form for large numbers: market caps, volumes. */
export function formatCompact(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`
  if (value >= 1e3) return `$${(value / 1e3).toFixed(2)}K`
  return `$${value.toFixed(2)}`
}

/** Percentage change with an explicit sign. */
export function formatChange(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

/**
 * Shorten a token amount for display.
 *
 * The exact value is always available in the raw string; this is only for
 * the visible column, which must not wrap.
 */
export function formatAmount(formatted: string): string {
  if (formatted === 'unavailable') return 'unavailable'

  const value = Number.parseFloat(formatted)
  if (!Number.isFinite(value)) return formatted

  if (value === 0) return '0'
  if (value >= 1_000_000) return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (value >= 1) return value.toLocaleString('en-US', { maximumFractionDigits: 4 })
  if (value >= 0.0001) return value.toFixed(6)
  return value.toExponential(2)
}

/** Tailwind text colour for a change value. */
export function changeColour(value: number | null | undefined): string {
  if (value == null) return 'text-coal-500'
  if (value > 0) return 'text-emerald-400'
  if (value < 0) return 'text-red-400'
  return 'text-coal-400'
}
