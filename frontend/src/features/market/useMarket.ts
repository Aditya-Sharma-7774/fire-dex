/**
 * Hooks for live market data.
 *
 * Prices poll every 20 seconds. The backend caches for 45, so most polls
 * are served from cache and cost no external quota -- the interface still
 * feels live without exhausting the provider's free tier.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api,
  ApiError,
  type PortfolioResponse,
  type PriceResponse,
} from '../../services/api'

interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
  updatedAt: number | null
}

const IDLE = { data: null, error: null, loading: false, updatedAt: null }

/** Live USD prices for everything the backend tracks. */
export function usePrices(intervalMs = 30_000) {
  const [state, setState] = useState<AsyncState<Record<string, PriceResponse>>>(IDLE)

  const refresh = useCallback(async () => {
    try {
      const data = await api.prices()
      setState({ data, error: null, loading: false, updatedAt: Date.now() })
    } catch (error) {
      // Keep whatever we already have on screen, but record the error so the
      // UI can show that refreshing failed. We do not blank the prices --
      // and we do not pretend the old ones are new either.
      setState((prev) => ({
        ...prev,
        loading: false,
        error: error instanceof ApiError ? error.message : 'Could not load prices',
      }))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(timer)
  }, [refresh, intervalMs])

  return { ...state, refresh }
}

/** Full portfolio for an address: balances joined with prices, valued in USD. */
export function usePortfolio(chain: string | null, address: string | null, intervalMs = 30_000) {
  const [state, setState] = useState<AsyncState<PortfolioResponse>>(IDLE)
  const requestRef = useRef(0)

  const refresh = useCallback(async () => {
    if (!chain || !address) {
      setState(IDLE)
      return
    }

    const requestId = ++requestRef.current
    setState((prev) => ({ ...prev, loading: true }))

    try {
      const data = await api.portfolio(chain, address)
      // Discard a response that arrived after a newer request was issued,
      // otherwise switching chains quickly shows the previous chain's
      // holdings under the new chain's name.
      if (requestId !== requestRef.current) return
      setState({ data, error: null, loading: false, updatedAt: Date.now() })
    } catch (error) {
      if (requestId !== requestRef.current) return
      setState({
        data: null,
        error: error instanceof ApiError ? error.message : 'Could not load portfolio',
        loading: false,
        updatedAt: null,
      })
    }
  }, [chain, address])

  useEffect(() => {
    void refresh()
    if (!chain || !address) return
    const timer = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(timer)
  }, [refresh, chain, address, intervalMs])

  return { ...state, refresh }
}

/**
 * Track which way a value last moved, so the UI can flash green or red.
 *
 * Returns 'up' | 'down' | null. Resets to null after the flash so the colour
 * marks a *change*, not a permanent state.
 */
export function usePriceDirection(value: number | null | undefined, flashMs = 900) {
  const [direction, setDirection] = useState<'up' | 'down' | null>(null)
  const previous = useRef<number | null | undefined>(value)

  useEffect(() => {
    if (value == null || previous.current == null) {
      previous.current = value
      return
    }
    if (value === previous.current) return

    setDirection(value > previous.current ? 'up' : 'down')
    previous.current = value

    const timer = setTimeout(() => setDirection(null), flashMs)
    return () => clearTimeout(timer)
  }, [value, flashMs])

  return direction
}
