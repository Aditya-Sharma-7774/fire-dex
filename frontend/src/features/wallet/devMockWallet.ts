/**
 * ============================================================
 *  DEVELOPMENT MOCK WALLET -- NOT PART OF THE REAL APPLICATION
 * ============================================================
 *
 * A fake EIP-1193 provider, so wallet UI can be developed and tested on a
 * machine with no MetaMask installed, and so wallet flows that are awkward
 * to reproduce by hand (rejection, network switching, account switching)
 * can be exercised deliberately.
 *
 * WHAT IT DOES AND DOES NOT FAKE
 *
 *   Fakes:     the wallet -- addresses, chain IDs, approval, events.
 *   Does NOT:  blockchain data. Balances still come from the real backend,
 *              which reads a real node. A mocked address shows its real
 *              on-chain balance.
 *
 * There are no private keys here, real or fake. The mock only ever returns
 * public addresses, exactly as a real wallet does.
 *
 * THREE SAFETY GATES, all of which must pass before it activates:
 *
 *   1. import.meta.env.DEV -- Vite replaces this with `false` in a
 *      production build, so the bundler removes this whole module.
 *   2. An explicit `?mockWallet=1` in the URL. Never on by default.
 *   3. A visible banner in the UI while it is active, so nobody can mistake
 *      mock data for a real connection.
 */

import type { Eip1193Provider } from './provider'

/** A real, well-known public address (vitalik.eth) with a real balance. */
const MOCK_ADDRESS = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'
const MOCK_SECOND_ADDRESS = '0xAb5801a7D398351b8bE11C439e05C5B3259aec9B'

const SEPOLIA_HEX = '0xaa36a7'

type Handler = (...args: never[]) => void

export function isMockWalletRequested(): boolean {
  if (!import.meta.env.DEV) return false
  return new URLSearchParams(window.location.search).get('mockWallet') === '1'
}

/**
 * Install the mock at window.ethereum.
 *
 * Must run before React mounts, because the wallet context reads
 * window.ethereum once on startup.
 */
export function installMockWallet(): void {
  if (!isMockWalletRequested()) return

  const handlers: Record<string, Handler[]> = {}
  let authorised = false
  let chainIdHex = SEPOLIA_HEX
  const addedChains = new Set<string>()
  let address = MOCK_ADDRESS

  const emit = (event: string, payload: unknown) => {
    for (const handler of handlers[event] ?? []) {
      ;(handler as (arg: unknown) => void)(payload)
    }
  }

  const provider: Eip1193Provider = {
    isMetaMask: true,

    async request({ method, params }) {
      // A real wallet is never instant. The delay makes loading and
      // "connecting" states actually observable during development.
      await new Promise((resolve) => setTimeout(resolve, 220))

      switch (method) {
        case 'eth_accounts':
          return authorised ? [address] : []

        case 'eth_requestAccounts': {
          // ?mockReject=1 exercises the user-rejection path (EIP-1193 4001).
          if (new URLSearchParams(window.location.search).get('mockReject') === '1') {
            throw { code: 4001, message: 'User rejected the request.' }
          }
          authorised = true
          return [address]
        }

        case 'eth_chainId':
          return chainIdHex

        case 'wallet_switchEthereumChain': {
          const requested = (params as [{ chainId: string }])[0]?.chainId
          if (!requested) throw { code: -32602, message: 'Missing chainId' }

          // Behave like a fresh MetaMask that has not had BNB Smart Chain
          // added, so the 4902 "unrecognised chain" -> add-chain path runs.
          if (requested === '0x38' && !addedChains.has('0x38')) {
            throw { code: 4902, message: 'Unrecognized chain ID.' }
          }

          chainIdHex = requested
          emit('chainChanged', chainIdHex)
          return null
        }

        case 'wallet_addEthereumChain': {
          const added = (params as [{ chainId: string }])[0]?.chainId
          if (!added) throw { code: -32602, message: 'Missing chainId' }
          // MetaMask adds the network and then switches to it.
          addedChains.add(added)
          chainIdHex = added
          emit('chainChanged', chainIdHex)
          return null
        }

        default:
          throw { code: -32601, message: `Mock wallet does not implement ${method}` }
      }
    },

    on(event, handler) {
      ;(handlers[event] ??= []).push(handler)
    },

    removeListener(event, handler) {
      handlers[event] = (handlers[event] ?? []).filter((h) => h !== handler)
    },
  }

  Object.defineProperty(window, 'ethereum', {
    value: provider,
    writable: true,
    configurable: true,
  })

  // Console helpers, so the event-driven paths can be triggered by hand.
  Object.defineProperty(window, '__mockWallet', {
    value: {
      switchAccount() {
        address = address === MOCK_ADDRESS ? MOCK_SECOND_ADDRESS : MOCK_ADDRESS
        emit('accountsChanged', [address])
        return address
      },
      revokeAccess() {
        authorised = false
        emit('accountsChanged', [])
      },
      /** Chain 137 is not in our registry -- triggers the unsupported banner. */
      switchToUnsupportedChain() {
        chainIdHex = '0x89'
        emit('chainChanged', chainIdHex)
      },
      setChain(hex: string) {
        chainIdHex = hex
        emit('chainChanged', hex)
      },
    },
    writable: false,
    configurable: true,
  })

  console.warn(
    '%c⚠ MOCK WALLET ACTIVE',
    'background:#f97316;color:#000;padding:2px 6px;border-radius:3px;font-weight:bold',
    '\nwindow.ethereum is a development fake. Balances are still real backend data.',
    '\nHelpers: __mockWallet.switchAccount() / .revokeAccess() / .switchToUnsupportedChain()',
  )
}
