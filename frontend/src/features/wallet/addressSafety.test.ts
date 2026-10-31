import { describe, expect, it } from 'vitest'

import { addressShapeProblem, detectSecret, secretWarning } from './addressSafety'

/**
 * Two-sided on purpose. Every secret shape must be caught, AND every real
 * address must pass: a guard that blocks genuine addresses is just broken.
 * The addresses below were taken from live mainnet data.
 */

const REAL_ADDRESSES = {
  solanaWallet: '8p4jRpgGUt1PFcgrbCbd11DAVXiRpwxiK47gPLbpomaq',
  solanaMint: 'So11111111111111111111111111111111111111112',
  solanaSystemProgram: '11111111111111111111111111111111',
  bitcoinLegacy: '1JbMa6P5q9DjPJ7zYDP554WiMLTmTohu9Y',
  bitcoinP2sh: '35GYekpvL9YH5xxj3bneNuCXxzRMkt3Ye9',
  bitcoinSegwit: 'bc1qdllzjxkykyk7mmm698lnsh4378xj62fthqex3q',
  bitcoinSegwitScript: 'bc1qwqdg6squsna38e46795at95yu9atm8azzmyvckulcc7kytlcckxswvvzej',
  bitcoinTaproot: 'bc1p64gwv9c32f9ghl7p4dy5x4xurrrll3rs8ykg840pzt5tu83jgyestd2w8z',
  ethereum: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
}

// Shapes only. None of these is anybody's key.
const SECRETS = {
  'evm-private-key': '0x' + 'ab'.repeat(32),
  'evm-private-key-bare': 'cd'.repeat(32),
  'solana-keypair': '4' + 'Zq'.repeat(43),
  'keypair-file': JSON.stringify(Array.from({ length: 64 }, (_, i) => (i * 7) % 256)),
  'wif-uncompressed': '5' + 'H'.repeat(50),
  'wif-compressed': 'K' + 'x'.repeat(51),
  'extended-private-key': 'xprv' + '9A'.repeat(54),
  // The published BIP-39 test vector.
  'recovery-phrase': 'abandon '.repeat(11) + 'about',
}

describe('detectSecret', () => {
  it.each(Object.entries(SECRETS))('catches %s', (_, secret) => {
    expect(detectSecret(secret)).not.toBeNull()
  })

  it.each(Object.entries(REAL_ADDRESSES))('lets the real %s address through', (_, address) => {
    expect(detectSecret(address)).toBeNull()
  })

  it('names the kind of secret it found', () => {
    expect(detectSecret(SECRETS['wif-compressed'])).toBe('wif-private-key')
    expect(detectSecret(SECRETS['recovery-phrase'])).toBe('recovery-phrase')
    expect(detectSecret(SECRETS['keypair-file'])).toBe('keypair-file')
  })

  it('catches a recovery phrase however it is spaced or capitalised', () => {
    expect(detectSecret('  Abandon   ABANDON ' + 'abandon '.repeat(9) + 'about  ')).toBe('recovery-phrase')
  })

  it('does not mistake an ordinary sentence for a recovery phrase', () => {
    expect(detectSecret('please show me my solana balance')).toBeNull()
  })
})

describe('secretWarning', () => {
  it('never repeats any part of the secret', () => {
    for (const secret of Object.values(SECRETS)) {
      const kind = detectSecret(secret)!
      const message = secretWarning(kind)
      expect(message).not.toContain(secret.trim().slice(0, 8))
      expect(message).toMatch(/not sent anywhere/)
    }
  })
})

describe('addressShapeProblem', () => {
  it('accepts every real Solana and Bitcoin address', () => {
    expect(addressShapeProblem('solana', REAL_ADDRESSES.solanaWallet)).toBeNull()
    for (const key of ['bitcoinLegacy', 'bitcoinP2sh', 'bitcoinSegwit', 'bitcoinSegwitScript', 'bitcoinTaproot'] as const) {
      expect(addressShapeProblem('bitcoin', REAL_ADDRESSES[key])).toBeNull()
    }
  })

  it('points an Ethereum address at MetaMask', () => {
    expect(addressShapeProblem('solana', REAL_ADDRESSES.ethereum)).toMatch(/MetaMask/)
  })

  it('rejects a Bitcoin address pasted as Solana and the reverse', () => {
    expect(addressShapeProblem('bitcoin', REAL_ADDRESSES.solanaWallet)).not.toBeNull()
    expect(addressShapeProblem('solana', REAL_ADDRESSES.bitcoinTaproot)).not.toBeNull()
  })

  it('asks for input when empty', () => {
    expect(addressShapeProblem('solana', '   ')).toMatch(/Paste/)
  })
})
