import { describe, expect, it } from 'vitest'

import {
  changeColour,
  formatAmount,
  formatChange,
  formatCompact,
  formatPrice,
  formatUsd,
} from './format'

/**
 * Tests for the money formatters.
 *
 * These matter more than they look. Every figure a user reads passes
 * through here, and a formatting bug is indistinguishable from a data bug
 * to the person looking at the screen — "$0.00" next to a real holding
 * reads as "worthless", not as "rounded badly".
 */

describe('formatPrice', () => {
  it('formats ordinary prices with two decimals', () => {
    expect(formatPrice(2462.7)).toBe('$2,463')
    expect(formatPrice(5.66)).toBe('$5.66')
  })

  it('uses thousands separators above 1000', () => {
    expect(formatPrice(2462.7)).toContain(',')
  })

  it('scales precision down as the price shrinks', () => {
    expect(formatPrice(0.9998)).toBe('$0.9998')
    expect(formatPrice(0.001234)).toBe('$0.001234')
  })

  it('never renders a real price as $0.00', () => {
    // The bug this guards: PEPE at 0.00000348 displayed as "$0.00" reads
    // as worthless. Meme coins are a real part of the token registry.
    const shib = formatPrice(0.00000512)
    expect(shib).not.toBe('$0.00')
    expect(shib).toBe('$0.00000512')
  })

  it('avoids scientific notation down to 1e-8', () => {
    // Plain decimals are far friendlier than "$5.12e-6" for a general
    // audience, and stay readable to eight places.
    expect(formatPrice(0.00000512)).not.toContain('e')
  })

  it('falls back to scientific notation below 1e-8', () => {
    expect(formatPrice(0.0000000001)).toContain('e')
  })

  it('distinguishes a genuine zero from an unknown price', () => {
    expect(formatPrice(0)).toBe('$0')
    expect(formatPrice(null)).toBe('—')
    expect(formatPrice(undefined)).toBe('—')
  })
})

describe('formatUsd', () => {
  it('always shows exactly two decimals', () => {
    expect(formatUsd(16335.5)).toBe('$16,335.50')
    expect(formatUsd(4)).toBe('$4.00')
  })

  it('shows a dash for an unknown value, never $0.00', () => {
    // null means "we could not price this". Rendering it as $0.00 would
    // claim the holding is worthless, which is a different statement.
    expect(formatUsd(null)).toBe('—')
    expect(formatUsd(undefined)).toBe('—')
  })

  it('renders a real zero as $0.00', () => {
    expect(formatUsd(0)).toBe('$0.00')
  })
})

describe('formatCompact', () => {
  it('abbreviates large figures', () => {
    expect(formatCompact(295_918_236_153)).toBe('$295.92B')
    expect(formatCompact(11_421_903_813)).toBe('$11.42B')
    expect(formatCompact(407_991_540)).toBe('$407.99M')
    expect(formatCompact(5_400)).toBe('$5.40K')
  })

  it('handles trillions', () => {
    expect(formatCompact(2_500_000_000_000)).toBe('$2.50T')
  })

  it('shows a dash when unknown', () => {
    expect(formatCompact(null)).toBe('—')
  })
})

describe('formatChange', () => {
  it('marks positive changes with an explicit plus', () => {
    expect(formatChange(0.23)).toBe('+0.23%')
    expect(formatChange(11.1)).toBe('+11.10%')
  })

  it('keeps the minus on negative changes', () => {
    expect(formatChange(-2.42)).toBe('-2.42%')
  })

  it('shows a dash when unknown', () => {
    expect(formatChange(null)).toBe('—')
  })
})

describe('changeColour', () => {
  it('is green up, red down, neutral flat', () => {
    expect(changeColour(1)).toContain('emerald')
    expect(changeColour(-1)).toContain('red')
    expect(changeColour(0)).toContain('coal')
  })

  it('does not imply a direction when the value is unknown', () => {
    expect(changeColour(null)).toContain('coal')
  })
})

describe('formatAmount', () => {
  it('formats ordinary token amounts', () => {
    expect(formatAmount('6.642178')).toBe('6.6422')
    expect(formatAmount('290.268219')).toBe('290.2682')
  })

  it('separates thousands on large balances', () => {
    expect(formatAmount('548537.226')).toContain(',')
  })

  it('keeps small amounts visible rather than rounding to zero', () => {
    expect(formatAmount('0.000117')).toBe('0.000117')
  })

  it('passes through the unavailable marker unchanged', () => {
    // "unavailable" means the chain read failed. It must not be coerced
    // into a number and shown as 0, which would understate a holding.
    expect(formatAmount('unavailable')).toBe('unavailable')
  })

  it('renders a genuine zero as 0', () => {
    expect(formatAmount('0')).toBe('0')
  })
})
