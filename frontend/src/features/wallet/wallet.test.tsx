import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getEvmChainByChainId, toHexChainId } from '../../config/chains'
import {
  describeWalletError,
  getErrorCode,
  getMetaMaskProvider,
  shortenAddress,
  WalletErrorCode,
} from './provider'
import { useWallet, WalletProvider } from './WalletContext'

/**
 * Tests for the wallet layer.
 *
 * This is the riskiest code in the frontend. A wallet that reports the
 * wrong account, or misses a network switch, shows the user someone else's
 * balance or mainnet figures while they are on a testnet. Both are worse
 * than showing nothing.
 */

const ADDRESS_A = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'
const ADDRESS_B = '0xAb5801a7D398351b8bE11C439e05C5B3259aec9B'

/** A controllable stand-in for MetaMask. */
function createMockWallet(options: { accounts?: string[]; chainId?: string } = {}) {
  const handlers: Record<string, ((...args: never[]) => void)[]> = {}
  let accounts = options.accounts ?? []
  let chainId = options.chainId ?? '0x1'

  const provider = {
    isMetaMask: true,
    async request({ method, params }: { method: string; params?: unknown }) {
      switch (method) {
        case 'eth_accounts':
          return accounts
        case 'eth_requestAccounts':
          accounts = [ADDRESS_A]
          return accounts
        case 'eth_chainId':
          return chainId
        case 'wallet_switchEthereumChain': {
          const requested = (params as [{ chainId: string }])[0].chainId
          if (requested === '0x38') throw { code: 4902, message: 'Unrecognized chain ID.' }
          chainId = requested
          emit('chainChanged', chainId)
          return null
        }
        default:
          throw { code: -32601, message: 'not implemented' }
      }
    },
    on(event: string, handler: (...args: never[]) => void) {
      ;(handlers[event] ??= []).push(handler)
    },
    removeListener(event: string, handler: (...args: never[]) => void) {
      handlers[event] = (handlers[event] ?? []).filter((h) => h !== handler)
    },
  }

  function emit(event: string, payload: unknown) {
    for (const handler of handlers[event] ?? []) {
      ;(handler as (arg: unknown) => void)(payload)
    }
  }

  return {
    provider,
    emit,
    setAccounts: (next: string[]) => {
      accounts = next
      emit('accountsChanged', next)
    },
    listenerCount: (event: string) => (handlers[event] ?? []).length,
  }
}

/** Renders the wallet state as text so assertions read plainly. */
function Probe() {
  const wallet = useWallet()
  return (
    <div>
      <span data-testid="status">{wallet.status}</span>
      <span data-testid="address">{wallet.address ?? 'none'}</span>
      <span data-testid="chain">{wallet.chain?.id ?? 'none'}</span>
      <span data-testid="chainId">{wallet.chainId ?? 'none'}</span>
      <span data-testid="unsupported">{String(wallet.isUnsupportedNetwork)}</span>
      <span data-testid="error">{wallet.error ?? 'none'}</span>
      <button onClick={() => void wallet.connect()}>connect</button>
      <button onClick={() => wallet.disconnect()}>disconnect</button>
      <button onClick={() => void wallet.switchToChain('sepolia')}>to-sepolia</button>
      <button onClick={() => void wallet.switchToChain('bsc')}>to-bsc</button>
    </div>
  )
}

function renderWallet() {
  return render(
    <WalletProvider>
      <Probe />
    </WalletProvider>,
  )
}

afterEach(() => {
  delete (window as { ethereum?: unknown }).ethereum
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------

describe('shortenAddress', () => {
  it('keeps the start and end so an address stays recognisable', () => {
    expect(shortenAddress(ADDRESS_A)).toBe('0xd8dA…6045')
  })

  it('leaves an already-short string alone', () => {
    expect(shortenAddress('0x1234')).toBe('0x1234')
  })
})

describe('toHexChainId', () => {
  it('converts to the hex form wallets expect', () => {
    // wallet_switchEthereumChain takes '0xaa36a7', not 11155111. Passing
    // the decimal is a common and silent failure.
    expect(toHexChainId(11155111)).toBe('0xaa36a7')
    expect(toHexChainId(1)).toBe('0x1')
    expect(toHexChainId(56)).toBe('0x38')
  })
})

describe('getEvmChainByChainId', () => {
  it('resolves supported chains', () => {
    expect(getEvmChainByChainId(1)?.id).toBe('ethereum')
    expect(getEvmChainByChainId(11155111)?.id).toBe('sepolia')
  })

  it('returns undefined for a chain we do not support', () => {
    expect(getEvmChainByChainId(137)).toBeUndefined()
  })
})

describe('wallet error handling', () => {
  it('reads the standard EIP-1193 codes', () => {
    expect(getErrorCode({ code: 4001 })).toBe(4001)
    expect(getErrorCode({ data: { code: 4902 } })).toBe(4902)
    expect(getErrorCode('not an error object')).toBeNull()
  })

  it('explains rejection in plain language', () => {
    const message = describeWalletError({ code: WalletErrorCode.USER_REJECTED })
    expect(message).toMatch(/rejected/i)
  })

  it('tells the user where to look when a request is already open', () => {
    const message = describeWalletError({ code: WalletErrorCode.REQUEST_ALREADY_PENDING })
    expect(message).toMatch(/MetaMask window/i)
  })
})

describe('getMetaMaskProvider', () => {
  it('returns null when no wallet is installed', () => {
    expect(getMetaMaskProvider()).toBeNull()
  })

  it('picks MetaMask when several wallets compete for window.ethereum', () => {
    const other = { isMetaMask: false, request: vi.fn(), on: vi.fn(), removeListener: vi.fn() }
    const metamask = { isMetaMask: true, request: vi.fn(), on: vi.fn(), removeListener: vi.fn() }
    ;(window as never as { ethereum: unknown }).ethereum = {
      ...other,
      providers: [other, metamask],
    }

    expect(getMetaMaskProvider()).toBe(metamask)
  })
})

// ---------------------------------------------------------------------
// The state machine
// ---------------------------------------------------------------------

describe('WalletProvider', () => {
  it('reports unavailable when no wallet is installed', async () => {
    renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unavailable'))
  })

  it('restores an existing session without opening a popup', async () => {
    const mock = createMockWallet({ accounts: [ADDRESS_A], chainId: '0x1' })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider
    const requestSpy = vi.spyOn(mock.provider, 'request')

    renderWallet()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
    expect(screen.getByTestId('address')).toHaveTextContent(ADDRESS_A)

    // eth_requestAccounts opens a popup; restoring must not use it.
    const methods = requestSpy.mock.calls.map((c) => (c[0] as { method: string }).method)
    expect(methods).toContain('eth_accounts')
    expect(methods).not.toContain('eth_requestAccounts')
  })

  it('stays disconnected when the wallet has authorised nothing', async () => {
    const mock = createMockWallet({ accounts: [] })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('disconnected'))
  })

  it('connects on request', async () => {
    const mock = createMockWallet({ accounts: [] })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('disconnected'))

    await act(async () => {
      screen.getByText('connect').click()
    })

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
  })

  it('follows an account switch made inside the wallet', async () => {
    // Without this, the app happily shows account A's balance while the
    // user is operating account B.
    const mock = createMockWallet({ accounts: [ADDRESS_A] })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(ADDRESS_A))

    await act(async () => mock.setAccounts([ADDRESS_B]))

    await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(ADDRESS_B))
  })

  it('treats an empty accounts event as a disconnection', async () => {
    const mock = createMockWallet({ accounts: [ADDRESS_A] })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))

    await act(async () => mock.setAccounts([]))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('disconnected'))
    expect(screen.getByTestId('address')).toHaveTextContent('none')
  })

  it('follows a network switch made inside the wallet', async () => {
    const mock = createMockWallet({ accounts: [ADDRESS_A], chainId: '0x1' })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('chain')).toHaveTextContent('ethereum'))

    await act(async () => mock.emit('chainChanged', '0xaa36a7'))

    await waitFor(() => expect(screen.getByTestId('chain')).toHaveTextContent('sepolia'))
  })

  it('flags a network it does not support', async () => {
    // Critical: on an unsupported chain every figure on screen would be
    // meaningless, so the app must know and say so.
    const mock = createMockWallet({ accounts: [ADDRESS_A], chainId: '0x1' })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('unsupported')).toHaveTextContent('false'))

    await act(async () => mock.emit('chainChanged', '0x89')) // Polygon

    await waitFor(() => expect(screen.getByTestId('unsupported')).toHaveTextContent('true'))
    expect(screen.getByTestId('chainId')).toHaveTextContent('137')
    expect(screen.getByTestId('chain')).toHaveTextContent('none')
  })

  it('lets state be driven by the wallet event, not the switch call', async () => {
    // switchToChain deliberately does not set state itself; it waits for
    // chainChanged. That way the UI is correct whether the switch came
    // from us or from MetaMask directly.
    const mock = createMockWallet({ accounts: [ADDRESS_A], chainId: '0x1' })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('chain')).toHaveTextContent('ethereum'))

    await act(async () => {
      screen.getByText('to-sepolia').click()
    })

    await waitFor(() => expect(screen.getByTestId('chain')).toHaveTextContent('sepolia'))
  })

  it('explains an unrecognised chain rather than failing silently', async () => {
    const mock = createMockWallet({ accounts: [ADDRESS_A], chainId: '0x1' })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))

    await act(async () => {
      screen.getByText('to-bsc').click()
    })

    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent(/Add BNB Smart Chain to MetaMask/i),
    )
  })

  it('removes its listeners on unmount', async () => {
    const mock = createMockWallet({ accounts: [ADDRESS_A] })
    ;(window as never as { ethereum: unknown }).ethereum = mock.provider

    const { unmount } = renderWallet()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
    expect(mock.listenerCount('accountsChanged')).toBeGreaterThan(0)

    unmount()

    expect(mock.listenerCount('accountsChanged')).toBe(0)
    expect(mock.listenerCount('chainChanged')).toBe(0)
  })
})
