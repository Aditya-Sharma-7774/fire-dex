import { useState } from 'react'

import { explorerAddressUrl, WATCH_ONLY_CHAINS } from '../../config/chains'
import { api, ApiError, type AddressValidation } from '../../services/api'
import { usePortfolio } from '../market/useMarket'
import { addressShapeProblem, detectSecret, secretWarning } from '../wallet/addressSafety'
import { shortenAddress } from '../wallet/provider'
import { PortfolioCard } from './HoldingsPanel'

/**
 * Solana and Bitcoin holdings, read from a public address.
 *
 * MetaMask cannot hold either, so these chains are watch-only: paste an
 * address, or let Phantom supply one. Fire DEX reads public chain data for
 * it and has no way to move funds.
 *
 * A paste field is exactly where people paste private keys by mistake, so
 * every input is checked for secret shapes the moment it arrives. A secret
 * is wiped from the field at once and never sent, stored or shown.
 */

type WatchChain = 'solana' | 'bitcoin'

const STORAGE_PREFIX = 'firedex.watch.'

function loadSaved(chain: WatchChain): AddressValidation | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + chain)
    return raw ? (JSON.parse(raw) as AddressValidation) : null
  } catch {
    return null
  }
}

function save(chain: WatchChain, value: AddressValidation | null): void {
  try {
    if (value) window.localStorage.setItem(STORAGE_PREFIX + chain, JSON.stringify(value))
    else window.localStorage.removeItem(STORAGE_PREFIX + chain)
  } catch {
    // Remembering the address is a convenience. Without storage it simply
    // is not remembered across reloads.
  }
}

interface PhantomProvider {
  isPhantom?: boolean
  connect(): Promise<{ publicKey: { toString(): string } }>
}

function getPhantom(): PhantomProvider | null {
  const provider = (window as unknown as { phantom?: { solana?: PhantomProvider } }).phantom?.solana
  return provider?.isPhantom ? provider : null
}

export function WatchAddressPanel() {
  const [chainId, setChainId] = useState<WatchChain>('solana')
  const [tracked, setTracked] = useState<AddressValidation | null>(() => loadSaved('solana'))
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const chain = WATCH_ONLY_CHAINS.find((c) => c.id === chainId)
  const portfolio = usePortfolio(tracked ? chainId : null, tracked?.address ?? null)
  const phantom = chainId === 'solana' ? getPhantom() : null

  if (!chain) return null

  function selectChain(id: WatchChain) {
    setChainId(id)
    setTracked(loadSaved(id))
    setInput('')
    setError(null)
    setWarning(null)
  }

  /** True if the value was a secret and has been wiped. */
  function rejectIfSecret(value: string): boolean {
    const secret = detectSecret(value)
    if (!secret) return false
    setInput('')
    setError(null)
    setWarning(secretWarning(secret))
    return true
  }

  async function track(raw: string) {
    setError(null)
    setWarning(null)
    if (rejectIfSecret(raw)) return

    const problem = addressShapeProblem(chainId, raw)
    if (problem) {
      setError(problem)
      return
    }

    setChecking(true)
    try {
      const result = await api.validateAddress(chainId, raw.trim())
      setTracked(result)
      save(chainId, result)
      setInput('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not check that address.')
    } finally {
      setChecking(false)
    }
  }

  async function connectPhantom() {
    if (!phantom) return
    try {
      const { publicKey } = await phantom.connect()
      await track(publicKey.toString())
    } catch (err) {
      const rejected = (err as { code?: number })?.code === 4001
      setError(rejected ? 'You rejected the request in Phantom.' : 'Could not connect to Phantom.')
    }
  }

  function stopTracking() {
    setTracked(null)
    save(chainId, null)
  }

  return (
    <section id="track-address" className="mt-14 scroll-mt-24">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">
          Track an address
        </h2>
        <span className="text-[11px] text-coal-500">
          Watch-only · Fire DEX reads public data and cannot move funds
        </span>
      </div>

      <div className="mb-3 flex gap-2" role="group" aria-label="Chain to track">
        {WATCH_ONLY_CHAINS.map((option) => {
          const selected = option.id === chainId
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={selected}
              onClick={() => selectChain(option.id as WatchChain)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                selected
                  ? 'border-fire-500/40 bg-fire-500/10 text-fire-300'
                  : 'hairline text-coal-300 hover:bg-white/[0.04]'
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: option.color }} />
              {option.name}
            </button>
          )
        })}
      </div>

      {!tracked && (
        <form
          className="glass p-5"
          onSubmit={(event) => {
            event.preventDefault()
            void track(input)
          }}
        >
          <label htmlFor="watch-address" className="block text-xs text-coal-400">
            Public {chain.name} address
          </label>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input
              id="watch-address"
              type="text"
              value={input}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              placeholder={chainId === 'solana' ? 'e.g. 8p4jRpgG…pomaq' : 'e.g. bc1q… or 1… or 3…'}
              onChange={(event) => {
                const value = event.target.value
                if (rejectIfSecret(value)) return
                setInput(value)
                setError(null)
              }}
              className="min-w-0 flex-1 rounded-xl border hairline bg-coal-950/60 px-3 py-2 font-mono text-sm text-coal-100 outline-none placeholder:text-coal-600 focus:border-fire-500/40"
            />
            <button
              type="submit"
              disabled={checking}
              className="rounded-xl bg-fire-500/90 px-4 py-2 text-sm font-semibold text-coal-950 transition-colors hover:bg-fire-400 disabled:opacity-60"
            >
              {checking ? 'Checking…' : 'Track'}
            </button>
            {phantom && (
              <button
                type="button"
                onClick={() => void connectPhantom()}
                className="rounded-xl border hairline px-4 py-2 text-sm text-coal-200 transition-colors hover:bg-white/[0.05]"
              >
                Use Phantom
              </button>
            )}
          </div>

          {warning && (
            <p role="alert" className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs leading-relaxed text-red-200">
              {warning}
            </p>
          )}
          {error && (
            <p role="alert" className="mt-3 text-xs text-amber-300">
              {error}
            </p>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-coal-500">
            Only ever paste a public address. Fire DEX never needs a private key or recovery phrase.
          </p>
        </form>
      )}

      {tracked && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <a
              href={explorerAddressUrl(chain, tracked.address)}
              target="_blank"
              rel="noreferrer noopener"
              className="font-mono text-coal-300 hover:text-fire-300"
            >
              {shortenAddress(tracked.address, 6)}
            </a>
            {tracked.address_type && <span className="text-coal-500">{tracked.address_type}</span>}
            {tracked.is_wallet === false && (
              <span className="text-amber-400">Program-owned address, not a personal wallet</span>
            )}
            <button
              type="button"
              onClick={stopTracking}
              className="ml-auto text-coal-500 hover:text-coal-200"
            >
              Stop tracking
            </button>
          </div>
          <PortfolioCard chain={chain} portfolio={portfolio} />
        </>
      )}
    </section>
  )
}
