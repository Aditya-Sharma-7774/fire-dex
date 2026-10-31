/**
 * Recognises what a person might paste by mistake -- BEFORE it leaves the browser.
 *
 * The backend also refuses these shapes, but by then the secret has crossed
 * the network and reached the server's access log. Catching it here means it
 * is never sent at all.
 *
 * None of these shapes overlaps a real address, so a false positive cannot
 * block a genuine one:
 *
 *   address                   length    secret                     length
 *   Bitcoin legacy / P2SH     26-35     WIF private key            51-52
 *   Bitcoin bech32            42-62     Solana keypair (base58)    86-88
 *   Solana                    32-44     extended private key       111
 *   Ethereum                  42        EVM private key (hex)      64
 */

export type SecretKind =
  | 'evm-private-key'
  | 'solana-keypair'
  | 'keypair-file'
  | 'wif-private-key'
  | 'extended-private-key'
  | 'recovery-phrase'

const BASE58 = '1-9A-HJ-NP-Za-km-z'

const SHAPES: Array<[SecretKind, RegExp]> = [
  ['evm-private-key', /^(0x)?[0-9a-fA-F]{64}$/],
  ['keypair-file', /^\[\s*\d{1,3}(\s*,\s*\d{1,3}){31,}\s*\]$/],
  ['extended-private-key', new RegExp(`^[xyztuv]prv[${BASE58}]{100,}$`)],
  ['solana-keypair', new RegExp(`^[${BASE58}]{80,90}$`)],
  ['wif-private-key', new RegExp(`^[5KL9c][${BASE58}]{50,51}$`)],
]

const RECOVERY_PHRASE_LENGTHS = new Set([12, 15, 18, 21, 24])

/** What kind of secret the input looks like, or null if it looks like none. */
export function detectSecret(input: string): SecretKind | null {
  const value = input.trim()
  for (const [kind, shape] of SHAPES) {
    if (shape.test(value)) return kind
  }
  const words = value.toLowerCase().split(/\s+/)
  if (RECOVERY_PHRASE_LENGTHS.has(words.length) && words.every((w) => /^[a-z]{3,8}$/.test(w))) {
    return 'recovery-phrase'
  }
  return null
}

const LABELS: Record<SecretKind, string> = {
  'evm-private-key': 'a private key',
  'solana-keypair': 'a Solana private key',
  'keypair-file': 'a wallet keypair file',
  'wif-private-key': 'a Bitcoin private key',
  'extended-private-key': 'an extended private key',
  'recovery-phrase': 'a recovery phrase',
}

/** What to tell the user. Never repeats any part of the input. */
export function secretWarning(kind: SecretKind): string {
  return (
    `That looks like ${LABELS[kind]}. It was not sent anywhere. ` +
    'Fire DEX never needs one -- paste a public address instead. ' +
    'If you have shared this anywhere, move your funds to a new wallet now.'
  )
}

/**
 * A quick shape check before asking the server.
 *
 * Deliberately loose: it only catches input that is obviously the wrong
 * kind. The backend does the real validation, including every checksum.
 */
export function addressShapeProblem(chain: 'solana' | 'bitcoin', input: string): string | null {
  const value = input.trim()
  if (!value) return 'Paste a public address.'
  if (value.startsWith('0x')) return 'That is an Ethereum address. Connect MetaMask for Ethereum and BNB Chain.'

  if (chain === 'solana') {
    return new RegExp(`^[${BASE58}]{32,44}$`).test(value)
      ? null
      : 'A Solana address is 32 to 44 letters and numbers, without 0, O, I or l.'
  }

  const bech32 = /^(bc1|BC1)[0-9a-zA-Z]{8,87}$/.test(value)
  const legacy = new RegExp(`^[13][${BASE58}]{25,34}$`).test(value)
  return bech32 || legacy ? null : 'A Bitcoin address starts with 1, 3 or bc1.'
}
