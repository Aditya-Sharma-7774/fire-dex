import { useEffect, useRef, useState } from 'react'

import { METAMASK_CHAINS } from '../../config/chains'
import { useWallet } from './WalletContext'

/**
 * Network picker.
 *
 * Switching here asks the WALLET to switch, rather than changing some local
 * variable. That matters: the wallet is the authority on which network the
 * user is actually on, and pretending otherwise is how apps end up showing
 * mainnet data while the wallet is on a testnet.
 *
 * Chains we have not implemented are shown but disabled, so the roadmap is
 * visible without implying they work.
 */
export function NetworkSelector() {
  const { chain, chainId, isUnsupportedNetwork, status, switchToChain } = useWallet()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const disconnected = status !== 'connected'

  const label = disconnected
    ? 'No Network'
    : isUnsupportedNetwork
      ? `Unsupported (${chainId})`
      : (chain?.shortName ?? 'Unknown')

  const dotColour = disconnected
    ? '#61616b'
    : isUnsupportedNetwork
      ? '#f59e0b'
      : (chain?.color ?? '#61616b')

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disconnected}
        onClick={() => setOpen((value) => !value)}
        className={`flex items-center gap-2 rounded-xl border px-2.5 py-2 text-xs font-medium transition-all sm:px-3 ${
          isUnsupportedNetwork
            ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
            : 'hairline bg-white/[0.03] text-coal-300 hover:border-fire-500/30 hover:bg-white/[0.06]'
        } disabled:cursor-not-allowed disabled:opacity-50`}
      >
        <span
          className="h-2 w-2 shrink-0 rounded-full transition-colors duration-300"
          style={{ background: dotColour, boxShadow: `0 0 8px ${dotColour}` }}
        />
        <span className="hidden sm:inline">{label}</span>
        <span
          className={`text-coal-600 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-60 origin-top-right animate-scale-in rounded-2xl border hairline bg-coal-900/95 p-1.5 shadow-2xl backdrop-blur-xl">
          <div className="px-3 py-2 text-[10px] uppercase tracking-[0.12em] text-coal-500">
            Switch network
          </div>

          {METAMASK_CHAINS.map((option) => {
            const selected = chain?.id === option.id
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  void switchToChain(option.id)
                  setOpen(false)
                }}
                className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left transition-colors ${
                  selected ? 'bg-fire-500/10' : 'hover:bg-white/[0.05]'
                } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent`}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: option.color }}
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={`block truncate text-xs font-medium ${selected ? 'text-fire-300' : 'text-coal-200'}`}
                  >
                    {option.name}
                  </span>
                  <span className="block font-mono text-[10px] text-coal-500">
                    {option.family}
                    {option.chainId !== null && ` · ${option.chainId}`}
                  </span>
                </span>
                {option.isTestnet && (
                  <span className="shrink-0 rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400">
                    Test
                  </span>
                )}
                {selected && <span className="shrink-0 text-xs text-fire-400">✓</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
