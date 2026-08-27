/**
 * Wallet connection state, shared across the app.
 *
 * Uses React context rather than a state library: there is exactly one
 * wallet connection, it is read in several places, and this keeps the whole
 * lifecycle -- connect, disconnect, account switch, chain switch -- visible
 * in one readable file.
 *
 * The three wallet events we subscribe to are the ones that cause real bugs
 * when ignored:
 *
 *   accountsChanged  the user switched to a different account, or revoked
 *                    access entirely (empty array = disconnected)
 *   chainChanged     the user switched network in MetaMask itself, not in
 *                    our UI. Balances now refer to a different chain.
 *   disconnect       the wallet closed the connection
 *
 * An app that reads the account once on connect and never listens will
 * happily show account A's balance while the user is operating account B.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { getChain, getEvmChainByChainId, toHexChainId, type ChainConfig } from '../../config/chains'
import {
  describeWalletError,
  getAuthorisedAccounts,
  getChainId,
  getErrorCode,
  getMetaMaskProvider,
  requestAccounts,
  switchChain,
  WalletErrorCode,
  type Eip1193Provider,
} from './provider'

export type WalletStatus =
  /** No wallet extension found in this browser. */
  | 'unavailable'
  /** Wallet present, not connected. */
  | 'disconnected'
  /** Waiting for the user to approve in the popup. */
  | 'connecting'
  /** Connected, address known. */
  | 'connected'

export interface WalletState {
  status: WalletStatus
  address: string | null
  /** EIP-155 chain ID the wallet is currently on. */
  chainId: number | null
  /** The matching chain from our registry, or null if we do not support it. */
  chain: ChainConfig | null
  /** True when the wallet is on a network Fire DEX does not support. */
  isUnsupportedNetwork: boolean
  error: string | null
}

interface WalletContextValue extends WalletState {
  connect: () => Promise<void>
  disconnect: () => void
  switchToChain: (chainKey: string) => Promise<void>
  clearError: () => void
}

const WalletContext = createContext<WalletContextValue | null>(null)

const INITIAL_STATE: WalletState = {
  status: 'disconnected',
  address: null,
  chainId: null,
  chain: null,
  isUnsupportedNetwork: false,
  error: null,
}

export function WalletProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WalletState>(INITIAL_STATE)
  const providerRef = useRef<Eip1193Provider | null>(null)

  /** Recompute the derived chain fields from a raw chain ID. */
  const applyChainId = useCallback((chainId: number | null) => {
    const chain = chainId === null ? null : (getEvmChainByChainId(chainId) ?? null)
    return {
      chainId,
      chain,
      // Only meaningful once we know the chain ID. An unknown chain ID means
      // the wallet is on a network we do not support.
      isUnsupportedNetwork: chainId !== null && chain === null,
    }
  }, [])

  // -------------------------------------------------------------------
  // Startup: detect the wallet and restore an existing session
  // -------------------------------------------------------------------
  useEffect(() => {
    const provider = getMetaMaskProvider()

    if (!provider) {
      setState({ ...INITIAL_STATE, status: 'unavailable' })
      return
    }

    providerRef.current = provider
    let cancelled = false

    // eth_accounts does not open a popup, so this silently restores the
    // session if the user connected on a previous visit.
    const restore = async () => {
      try {
        const [accounts, chainId] = await Promise.all([
          getAuthorisedAccounts(provider),
          getChainId(provider),
        ])
        if (cancelled) return

        setState((prev) => ({
          ...prev,
          ...applyChainId(chainId),
          status: accounts.length > 0 ? 'connected' : 'disconnected',
          address: accounts[0] ?? null,
        }))
      } catch {
        // A failure here is not worth showing the user -- it just means we
        // could not restore a session, and they can click Connect.
        if (!cancelled) setState((prev) => ({ ...prev, status: 'disconnected' }))
      }
    }

    void restore()

    // ---- live wallet events ----
    const onAccountsChanged = (...args: never[]) => {
      const accounts = args[0] as unknown as string[]
      setState((prev) =>
        accounts.length === 0
          ? { ...prev, status: 'disconnected', address: null, error: null }
          : { ...prev, status: 'connected', address: accounts[0], error: null },
      )
    }

    const onChainChanged = (...args: never[]) => {
      const hexChainId = args[0] as unknown as string
      setState((prev) => ({ ...prev, ...applyChainId(parseInt(hexChainId, 16)), error: null }))
    }

    const onDisconnect = () => {
      setState((prev) => ({ ...prev, status: 'disconnected', address: null }))
    }

    provider.on('accountsChanged', onAccountsChanged)
    provider.on('chainChanged', onChainChanged)
    provider.on('disconnect', onDisconnect)

    return () => {
      cancelled = true
      provider.removeListener('accountsChanged', onAccountsChanged)
      provider.removeListener('chainChanged', onChainChanged)
      provider.removeListener('disconnect', onDisconnect)
    }
  }, [applyChainId])

  // -------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------

  const connect = useCallback(async () => {
    const provider = providerRef.current
    if (!provider) {
      setState((prev) => ({ ...prev, status: 'unavailable' }))
      return
    }

    setState((prev) => ({ ...prev, status: 'connecting', error: null }))

    try {
      const accounts = await requestAccounts(provider)
      const chainId = await getChainId(provider)

      setState((prev) => ({
        ...prev,
        ...applyChainId(chainId),
        status: accounts.length > 0 ? 'connected' : 'disconnected',
        address: accounts[0] ?? null,
        error: null,
      }))
    } catch (error) {
      setState((prev) => ({
        ...prev,
        status: 'disconnected',
        error: describeWalletError(error),
      }))
    }
  }, [applyChainId])

  /**
   * Forget the connection on our side.
   *
   * Note: there is no EIP-1193 method to make a wallet revoke access. This
   * clears our state; the user removes the site in MetaMask's own settings
   * if they want to fully revoke. We say so in the UI rather than implying
   * more than actually happened.
   */
  const disconnect = useCallback(() => {
    setState((prev) => ({ ...INITIAL_STATE, status: 'disconnected', chainId: prev.chainId, chain: prev.chain }))
  }, [])

  const switchToChain = useCallback(async (chainKey: string) => {
    const provider = providerRef.current
    const target = getChain(chainKey)
    if (!provider || !target || target.chainId === null) return

    setState((prev) => ({ ...prev, error: null }))

    try {
      await switchChain(provider, toHexChainId(target.chainId))
      // We do not set state here on purpose -- the wallet fires
      // `chainChanged`, and letting that single path update state means the
      // UI is correct whether the switch happened here or in MetaMask.
    } catch (error) {
      if (getErrorCode(error) === WalletErrorCode.UNRECOGNIZED_CHAIN) {
        setState((prev) => ({
          ...prev,
          error: `Add ${target.name} to MetaMask first, then try again.`,
        }))
        return
      }
      setState((prev) => ({ ...prev, error: describeWalletError(error) }))
    }
  }, [])

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }))
  }, [])

  const value = useMemo<WalletContextValue>(
    () => ({ ...state, connect, disconnect, switchToChain, clearError }),
    [state, connect, disconnect, switchToChain, clearError],
  )

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
}

export function useWallet(): WalletContextValue {
  const context = useContext(WalletContext)
  if (!context) {
    throw new Error('useWallet must be used inside <WalletProvider>')
  }
  return context
}
