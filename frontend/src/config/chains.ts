/**
 * Chain configuration.
 *
 * ARCHITECTURAL RULE: a chain is a *config entry*, not a code path.
 *
 * Nothing anywhere else in the app is allowed to hard-code a chain ID, an
 * RPC URL, a native symbol or an explorer link. Everything reads from here.
 * That is what makes "add BNB Smart Chain" a one-object change instead of a
 * hunt through twenty components.
 *
 * `chainId` is meaningful for EVM chains only. Solana and Bitcoin have no
 * EIP-155 chain ID, which is exactly why `family` exists -- the app must
 * never assume every chain behaves like Ethereum.
 *
 * KEPT IN SYNC with the backend registry in
 * `backend/app/blockchain/registry.py`. A backend test parses this file and
 * fails if the two disagree, because a mismatched chain ID or decimal count
 * is a financial safety bug, not a cosmetic one.
 */

export type ChainFamily = 'evm' | 'solana' | 'bitcoin'

export interface ChainConfig {
  /** Stable internal key. Used in API calls and database rows. */
  id: string
  /** Human-readable name shown in the UI. */
  name: string
  /** Short label for compact spaces. */
  shortName: string
  /** Which technical family this chain belongs to. Drives adapter selection. */
  family: ChainFamily
  /** EIP-155 chain ID. EVM chains only; null elsewhere. */
  chainId: number | null
  /** Ticker of the gas/native asset. */
  nativeSymbol: string
  /** Decimal places of the native asset. */
  nativeDecimals: number
  /** True for test networks. The UI must make this obvious to the user. */
  isTestnet: boolean
  /** Block explorer base URL, for linking transactions and addresses. */
  explorerUrl: string
  /** Accent colour used in charts, chips and the chain selector. */
  color: string
  /** Whether Fire DEX supports this chain. */
  isActive: boolean
  /**
   * Official RPC endpoint to give MetaMask when it does not know the chain.
   * The user's own transactions will go through it, so only the chain's
   * official endpoint belongs here. Unset for chains MetaMask ships with.
   */
  walletRpcUrl?: string
}

export const CHAINS: Record<string, ChainConfig> = {
  ethereum: {
    id: 'ethereum',
    name: 'Ethereum',
    shortName: 'ETH',
    family: 'evm',
    chainId: 1,
    nativeSymbol: 'ETH',
    nativeDecimals: 18,
    isTestnet: false,
    explorerUrl: 'https://etherscan.io',
    color: '#627EEA',
    isActive: true,
  },
  sepolia: {
    id: 'sepolia',
    name: 'Sepolia Testnet',
    shortName: 'Sepolia',
    family: 'evm',
    chainId: 11155111,
    nativeSymbol: 'ETH',
    nativeDecimals: 18,
    isTestnet: true,
    explorerUrl: 'https://sepolia.etherscan.io',
    color: '#8B9DC3',
    isActive: true,
  },
  bsc: {
    id: 'bsc',
    name: 'BNB Smart Chain',
    shortName: 'BNB',
    family: 'evm',
    chainId: 56,
    nativeSymbol: 'BNB',
    nativeDecimals: 18,
    isTestnet: false,
    explorerUrl: 'https://bscscan.com',
    color: '#F0B90B',
    isActive: true,
    walletRpcUrl: 'https://bsc-dataseed.bnbchain.org',
  },
  solana: {
    id: 'solana',
    name: 'Solana',
    shortName: 'SOL',
    family: 'solana',
    chainId: null,
    nativeSymbol: 'SOL',
    nativeDecimals: 9,
    isTestnet: false,
    explorerUrl: 'https://explorer.solana.com',
    color: '#14F195',
    isActive: true,
  },
  bitcoin: {
    id: 'bitcoin',
    name: 'Bitcoin',
    shortName: 'BTC',
    family: 'bitcoin',
    chainId: null,
    nativeSymbol: 'BTC',
    nativeDecimals: 8,
    isTestnet: false,
    explorerUrl: 'https://mempool.space',
    color: '#F7931A',
    isActive: true,
  },
}

export const CHAIN_LIST: ChainConfig[] = Object.values(CHAINS)

/** Chains Fire DEX supports. */
export const ACTIVE_CHAINS: ChainConfig[] = CHAIN_LIST.filter((c) => c.isActive)

/**
 * Chains MetaMask can switch to. MetaMask is an EVM wallet: offering it
 * Solana or Bitcoin would ask it to do something it cannot. Those chains
 * are read by address instead.
 */
export const METAMASK_CHAINS: ChainConfig[] = ACTIVE_CHAINS.filter((c) => c.family === 'evm')

/** Chains read by pasting a public address, because MetaMask cannot hold them. */
export const WATCH_ONLY_CHAINS: ChainConfig[] = ACTIVE_CHAINS.filter((c) => c.family !== 'evm')

export function getChain(id: string): ChainConfig | undefined {
  return CHAINS[id]
}

/** Find an EVM chain by its EIP-155 ID -- used to detect what MetaMask is on. */
export function getEvmChainByChainId(chainId: number): ChainConfig | undefined {
  return CHAIN_LIST.find((c) => c.family === 'evm' && c.chainId === chainId)
}

/**
 * EIP-155 chain ID as the hex string wallets expect.
 *
 * `wallet_switchEthereumChain` takes `{ chainId: '0xaa36a7' }`, not the
 * decimal 11155111. Getting this wrong is a very common bug, so the
 * conversion lives here once rather than at every call site.
 */
export function toHexChainId(chainId: number): string {
  return `0x${chainId.toString(16)}`
}

/** Explorer link for an address on a given chain. */
export function explorerAddressUrl(chain: ChainConfig, address: string): string {
  return `${chain.explorerUrl}/address/${address}`
}
