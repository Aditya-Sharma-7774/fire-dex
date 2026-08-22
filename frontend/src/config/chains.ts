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
 * Note that `chainId` is meaningful for EVM chains only. Solana and Bitcoin
 * do not have EIP-155 chain IDs, which is exactly why `family` exists -- the
 * app must never assume every chain behaves like Ethereum.
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
  /** Whether this chain is wired up yet. Drives "coming soon" states. */
  status: 'active' | 'planned'
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
    status: 'planned',
  },
  sepolia: {
    id: 'sepolia',
    name: 'Sepolia Testnet',
    shortName: 'SEP',
    family: 'evm',
    chainId: 11155111,
    nativeSymbol: 'ETH',
    nativeDecimals: 18,
    isTestnet: true,
    explorerUrl: 'https://sepolia.etherscan.io',
    color: '#8B9DC3',
    status: 'planned',
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
    status: 'planned',
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
    explorerUrl: 'https://solscan.io',
    color: '#14F195',
    status: 'planned',
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
    status: 'planned',
  },
}

export const CHAIN_LIST: ChainConfig[] = Object.values(CHAINS)

export function getChain(id: string): ChainConfig | undefined {
  return CHAINS[id]
}

/** Find an EVM chain by its EIP-155 ID -- used to detect what MetaMask is on. */
export function getEvmChainByChainId(chainId: number): ChainConfig | undefined {
  return CHAIN_LIST.find((c) => c.family === 'evm' && c.chainId === chainId)
}
