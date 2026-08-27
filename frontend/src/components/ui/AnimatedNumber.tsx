import { useEffect, useRef, useState } from 'react'

interface AnimatedNumberProps {
  /** The target value, as a string (balances are strings to protect precision). */
  value: string
  /** Decimal places to display while animating. */
  decimals?: number
  durationMs?: number
  className?: string
}

/**
 * Counts up to a new value instead of snapping to it.
 *
 * Used for balances. The movement makes it obvious *which* number changed
 * when data refreshes, which is genuinely useful when several figures
 * update at once.
 *
 * Honesty note: this animates only the DISPLAY. The underlying value is
 * never interpolated or rounded for any purpose other than drawing this
 * element -- arithmetic always uses the exact string from the backend.
 */
export function AnimatedNumber({
  value,
  decimals = 4,
  durationMs = 700,
  className,
}: AnimatedNumberProps) {
  const target = Number.parseFloat(value)
  const [display, setDisplay] = useState(target)
  const fromRef = useRef(target)
  const frameRef = useRef<number>()

  useEffect(() => {
    if (!Number.isFinite(target)) {
      setDisplay(0)
      return
    }

    const from = fromRef.current
    if (from === target) return

    const start = performance.now()

    const tick = (now: number) => {
      const progress = Math.min((now - start) / durationMs, 1)
      // Ease-out cubic: fast at first, settling gently. Linear counting
      // reads as mechanical.
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(from + (target - from) * eased)

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = target
      }
    }

    frameRef.current = requestAnimationFrame(tick)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [target, durationMs])

  if (!Number.isFinite(target)) return <span className={className}>—</span>

  // Trim trailing zeros so a whole balance reads as "2" and not "2.0000",
  // but only once the animation has settled.
  const settled = Math.abs(display - target) < 1e-9
  const text = settled ? value : display.toFixed(decimals)

  return (
    <span className={className} style={{ fontVariantNumeric: 'tabular-nums' }}>
      {text}
    </span>
  )
}

/**
 * A number that ticks upward, for block heights.
 *
 * Block numbers are large and change by small amounts, so counting through
 * every intermediate value would be absurd. This just flashes on change.
 */
export function TickingNumber({ value, className }: { value: number; className?: string }) {
  const [flash, setFlash] = useState(false)
  const previous = useRef(value)

  useEffect(() => {
    if (previous.current !== value) {
      previous.current = value
      setFlash(true)
      const timer = setTimeout(() => setFlash(false), 600)
      return () => clearTimeout(timer)
    }
  }, [value])

  return (
    <span
      className={`transition-colors duration-300 ${flash ? 'text-fire-300' : ''} ${className ?? ''}`}
      style={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {value.toLocaleString()}
    </span>
  )
}
