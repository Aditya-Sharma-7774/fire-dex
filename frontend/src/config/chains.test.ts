import { describe, expect, it } from 'vitest'

import { ACTIVE_CHAINS, explorerAddressUrl, getChain, METAMASK_CHAINS, WATCH_ONLY_CHAINS } from './chains'

describe('chain lists', () => {
  it('never offers MetaMask a chain it cannot switch to', () => {
    // MetaMask is an EVM wallet. Offering it Solana or Bitcoin would ask it
    // to switch to a chain with no chain ID, which silently does nothing.
    expect(METAMASK_CHAINS.every((c) => c.family === 'evm' && c.chainId !== null)).toBe(true)
    expect(METAMASK_CHAINS.map((c) => c.id)).toEqual(['ethereum', 'sepolia', 'bsc'])
  })

  it('reads Solana and Bitcoin by address instead', () => {
    expect(WATCH_ONLY_CHAINS.map((c) => c.id)).toEqual(['solana', 'bitcoin'])
  })

  it('covers every supported chain exactly once between the two', () => {
    const covered = [...METAMASK_CHAINS, ...WATCH_ONLY_CHAINS].map((c) => c.id).sort()
    expect(covered).toEqual(ACTIVE_CHAINS.map((c) => c.id).sort())
  })

  it('gives MetaMask an official endpoint only for chains it does not ship with', () => {
    expect(getChain('bsc')?.walletRpcUrl).toBe('https://bsc-dataseed.bnbchain.org')
    expect(getChain('ethereum')?.walletRpcUrl).toBeUndefined()
  })

  it('links addresses to explorers that serve an address page at /address/', () => {
    const solana = getChain('solana')!
    expect(explorerAddressUrl(solana, 'ABC')).toBe('https://explorer.solana.com/address/ABC')
    const bitcoin = getChain('bitcoin')!
    expect(explorerAddressUrl(bitcoin, 'bc1q')).toBe('https://mempool.space/address/bc1q')
  })
})
