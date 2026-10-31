/**
 * Access to the browser wallet, via the EIP-1193 standard.
 *
 * MetaMask (and every other browser wallet) injects a provider object at
 * `window.ethereum` that implements EIP-1193. We talk to that standard
 * directly rather than through a wrapper library, so it is completely
 * visible what is being asked of the wallet and when.
 *
 * ==========================================================
 *  SECURITY INVARIANT
 *  Nothing in this file -- or anywhere in Fire DEX -- ever
 *  requests, receives, stores or transmits a private key or
 *  seed phrase. We ask the wallet for a PUBLIC ADDRESS and
 *  ask it to sign; the key never leaves the extension.
 * ==========================================================
 */

/** The subset of EIP-1193 we actually use. */
export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] | object }): Promise<unknown>
  on(event: string, handler: (...args: never[]) => void): void
  removeListener(event: string, handler: (...args: never[]) => void): void
  isMetaMask?: boolean
  /** Present when several wallet extensions are installed side by side. */
  providers?: Eip1193Provider[]
}

declare global {
  interface Window {
    ethereum?: Eip1193Provider
  }
}

/**
 * Standard EIP-1193 / MetaMask error codes.
 *
 * These are part of the specification, not MetaMask trivia -- handling
 * them properly is the difference between a clear message and a scary
 * unexplained failure.
 */
export const WalletErrorCode = {
  /** The user clicked Reject in the wallet popup. Not an error condition. */
  USER_REJECTED: 4001,
  /** The wallet does not know this network and must be asked to add it. */
  UNRECOGNIZED_CHAIN: 4902,
  /** A previous request is still waiting for the user. Popup may be hidden. */
  REQUEST_ALREADY_PENDING: -32002,
} as const

interface ProviderRpcError {
  code: number
  message: string
}

function isProviderRpcError(error: unknown): error is ProviderRpcError {
  return typeof error === 'object' && error !== null && 'code' in error
}

export function getErrorCode(error: unknown): number | null {
  if (isProviderRpcError(error)) return error.code
  // MetaMask sometimes nests the real error one level down.
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data?: unknown }).data
    if (isProviderRpcError(data)) return data.code
  }
  return null
}

/**
 * Find the injected MetaMask provider, or null if it is not installed.
 *
 * When several wallet extensions are installed they compete for
 * `window.ethereum` and expose a `providers` array. We pick MetaMask
 * explicitly instead of taking whichever won the race, so the app behaves
 * predictably on a machine with more than one wallet.
 */
export function getMetaMaskProvider(): Eip1193Provider | null {
  const injected = window.ethereum
  if (!injected) return null

  if (Array.isArray(injected.providers)) {
    return injected.providers.find((p) => p.isMetaMask) ?? injected.providers[0] ?? null
  }

  return injected
}

export function isMetaMaskInstalled(): boolean {
  return getMetaMaskProvider() !== null
}

// ---------------------------------------------------------------------
// Typed wrappers around the raw RPC calls
// ---------------------------------------------------------------------

/**
 * Ask the wallet which accounts are already authorised.
 *
 * This does NOT open a popup. It is how we restore a session on page
 * reload without pestering the user to reconnect every time.
 */
export async function getAuthorisedAccounts(provider: Eip1193Provider): Promise<string[]> {
  const accounts = (await provider.request({ method: 'eth_accounts' })) as string[]
  return accounts ?? []
}

/**
 * Request access to the user's accounts. THIS OPENS THE WALLET POPUP.
 *
 * Only ever call it from a direct user action, such as a click. Calling it
 * on page load is hostile and browsers may block it.
 */
export async function requestAccounts(provider: Eip1193Provider): Promise<string[]> {
  const accounts = (await provider.request({ method: 'eth_requestAccounts' })) as string[]
  return accounts ?? []
}

/** Current network, as an EIP-155 chain ID in decimal. */
export async function getChainId(provider: Eip1193Provider): Promise<number> {
  const hex = (await provider.request({ method: 'eth_chainId' })) as string
  return parseInt(hex, 16)
}

/**
 * Ask the wallet to switch networks.
 *
 * Throws with code 4902 if the wallet does not have this chain configured,
 * which the caller can handle by offering to add it.
 */
export async function switchChain(
  provider: Eip1193Provider,
  hexChainId: string,
): Promise<void> {
  await provider.request({
    method: 'wallet_switchEthereumChain',
    params: [{ chainId: hexChainId }],
  })
}

/** What EIP-3085 needs to add a network the wallet does not know. */
export interface AddChainParams {
  chainId: string
  chainName: string
  nativeCurrency: { name: string; symbol: string; decimals: number }
  rpcUrls: string[]
  blockExplorerUrls: string[]
}

/**
 * Ask the wallet to add a network, which also switches to it.
 *
 * The RPC URL handed over here is the one the user's wallet will send their
 * own transactions through, so it must be the chain's official endpoint.
 * A dishonest RPC can misreport what a transaction does.
 */
export async function addChain(provider: Eip1193Provider, params: AddChainParams): Promise<void> {
  await provider.request({ method: 'wallet_addEthereumChain', params: [params] })
}

/** Turn any wallet error into a message worth showing a human. */
export function describeWalletError(error: unknown): string {
  const code = getErrorCode(error)

  switch (code) {
    case WalletErrorCode.USER_REJECTED:
      return 'You rejected the request in your wallet.'
    case WalletErrorCode.REQUEST_ALREADY_PENDING:
      return 'A wallet request is already open. Check your MetaMask window.'
    case WalletErrorCode.UNRECOGNIZED_CHAIN:
      return 'Your wallet does not have this network configured yet.'
    default:
      if (isProviderRpcError(error) && error.message) return error.message
      return 'Something went wrong talking to your wallet.'
  }
}

/** Shorten an address for display: 0xd8dA…6045 */
export function shortenAddress(address: string, chars = 4): string {
  if (address.length < chars * 2 + 4) return address
  return `${address.slice(0, 2 + chars)}…${address.slice(-chars)}`
}
