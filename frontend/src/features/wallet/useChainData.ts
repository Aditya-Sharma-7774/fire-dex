/**
 * Hooks for reading live chain data through our own backend.
 *
 * Note we deliberately fetch balances from the Fire DEX backend rather than
 * asking MetaMask directly, even though the wallet could answer. Reasons:
 *
 *   1. The backend adapter validates the address against that specific
 *      chain before any call is made.
 *   2. It is the same path the evidence collectors will use later, so the
 *      number an AI agent reasons about comes from the same source the user
 *      sees on screen.
 *   3. It keeps chain access behind one abstraction instead of two.
 *
 * If the backend is unreachable we say so. We never fall back to a stale
 * value and present it as current.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api, ApiError, type ChainStatusResponse, type NativeBalanceResponse } from '../../services/api'

interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** When this data was received in the browser. Drives the "live" indicator. */
  updatedAt: number | null
}

const IDLE: AsyncState<never> = { data: null, error: null, loading: false, updatedAt: null }

/**
 * Native balance for one address on one chain, refreshed on an interval.
 *
 * Passing a null address or chain leaves the hook idle -- it does not fire
 * a request for a disconnected wallet.
 */
export function useNativeBalance(chain: string | null, address: string | null, intervalMs = 15_000) {
  const [state, setState] = useState<AsyncState<NativeBalanceResponse>>(IDLE)

  // Held in a ref so the polling effect does not restart on every render.
  const requestRef = useRef(0)

  const refresh = useCallback(async () => {
    if (!chain || !address) {
      setState(IDLE)
      return
    }

    const requestId = ++requestRef.current
    setState((prev) => ({ ...prev, loading: true }))

    try {
      const data = await api.nativeBalance(chain, address)
      // Ignore a response that arrived after a newer request was issued --
      // otherwise switching chains quickly can show the previous chain's
      // balance under the new chain's name.
      if (requestId !== requestRef.current) return
      setState({ data, error: null, loading: false, updatedAt: Date.now() })
    } catch (error) {
      if (requestId !== requestRef.current) return
      setState({
        data: null,
        error: error instanceof ApiError ? error.message : 'Could not load balance',
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
 * Live status of a chain's RPC node, including the current block number.
 *
 * The block number is polled so the interface shows the chain advancing.
 * That is not decoration: a number that visibly increments is direct
 * evidence to anyone watching a demo that this is a real network
 * connection and not a mock.
 */
export function useChainStatus(chain: string | null, intervalMs = 12_000) {
  const [state, setState] = useState<AsyncState<ChainStatusResponse>>(IDLE)

  const refresh = useCallback(async () => {
    if (!chain) {
      setState(IDLE)
      return
    }
    try {
      const data = await api.chainStatus(chain)
      setState({ data, error: null, loading: false, updatedAt: Date.now() })
    } catch (error) {
      setState({
        data: null,
        error: error instanceof ApiError ? error.message : 'Chain unreachable',
        loading: false,
        updatedAt: null,
      })
    }
  }, [chain])

  useEffect(() => {
    void refresh()
    if (!chain) return

    // Ethereum produces a block roughly every 12 seconds, so polling faster
    // than that mostly returns the same number and wastes the rate limit.
    const timer = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(timer)
  }, [refresh, chain, intervalMs])

  return { ...state, refresh }
}
