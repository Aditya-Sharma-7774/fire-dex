import { useEffect, useRef, useState } from 'react'

import { explorerAddressUrl } from '../../config/chains'
import { shortenAddress } from './provider'
import { useWallet } from './WalletContext'

/**
 * Connect / connected-account control in the header.
 *
 * Four visible states, because each needs a different action from the user:
 *   unavailable  -> install MetaMask
 *   disconnected -> connect
 *   connecting   -> waiting on the popup
 *   connected    -> show the account, offer copy / explorer / disconnect
 */
export function WalletButton() {
  const { status, address, chain, connect, disconnect } = useWallet()
  const [menuOpen, setMenuOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close the dropdown on an outside click or Escape. Without this the menu
  // stays open behind other clicks, which feels broken.
  useEffect(() => {
    if (!menuOpen) return

    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  const copyAddress = async () => {
    if (!address) return
    try {
      await navigator.clipboard.writeText(address)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked; the address is visible on screen anyway */
    }
  }

  if (status === 'unavailable') {
    return (
      <a
        href="https://metamask.io/download/"
        target="_blank"
        rel="noreferrer noopener"
        className="group relative overflow-hidden rounded-xl border border-fire-500/30 bg-fire-500/10 px-3.5 py-2 text-xs font-semibold text-fire-300 transition-all hover:border-fire-500/60 hover:bg-fire-500/15 sm:text-sm"
      >
        Install MetaMask
      </a>
    )
  }

  if (status === 'connected' && address) {
    return (
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          className="group flex items-center gap-2 rounded-xl border hairline bg-white/[0.03] px-2.5 py-2 transition-all hover:border-fire-500/30 hover:bg-white/[0.06] sm:px-3"
        >
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span className="font-mono text-xs font-medium text-coal-100">
            {shortenAddress(address)}
          </span>
          <span
            className={`text-coal-500 transition-transform duration-200 ${menuOpen ? 'rotate-180' : ''}`}
            aria-hidden="true"
          >
            ▾
          </span>
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full z-50 mt-2 w-64 origin-top-right animate-scale-in rounded-2xl border hairline bg-coal-900/95 p-1.5 shadow-2xl backdrop-blur-xl">
            <div className="border-b hairline px-3 py-2.5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-coal-500">
                Connected account
              </div>
              <div className="mt-1 break-all font-mono text-[11px] text-coal-200">{address}</div>
            </div>

            <button
              type="button"
              onClick={copyAddress}
              className="mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs text-coal-300 transition-colors hover:bg-white/[0.05] hover:text-coal-100"
            >
              {copied ? '✓ Copied' : 'Copy address'}
            </button>

            {chain && (
              <a
                href={explorerAddressUrl(chain, address)}
                target="_blank"
                rel="noreferrer noopener"
                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs text-coal-300 transition-colors hover:bg-white/[0.05] hover:text-coal-100"
              >
                View on explorer ↗
              </a>
            )}

            <button
              type="button"
              onClick={() => {
                disconnect()
                setMenuOpen(false)
              }}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs text-red-400 transition-colors hover:bg-red-500/10"
            >
              Disconnect
            </button>

            {/* Being precise: no EIP-1193 method makes a wallet revoke access. */}
            <p className="px-3 pb-2 pt-1 text-[10px] leading-relaxed text-coal-600">
              Disconnecting clears this site's session. To fully revoke access, remove the site in
              MetaMask.
            </p>
          </div>
        )}
      </div>
    )
  }

  const connecting = status === 'connecting'

  return (
    <button
      type="button"
      onClick={() => void connect()}
      disabled={connecting}
      className="group relative overflow-hidden rounded-xl bg-gradient-to-br from-fire-500 to-fire-700 px-3.5 py-2 text-xs font-semibold text-white shadow-glow transition-all hover:shadow-glow-lg disabled:cursor-wait disabled:opacity-70 sm:px-4 sm:text-sm"
    >
      {/* Sheen that sweeps across on hover. Subtle -- it should read as
          polish, not as a game UI. */}
      <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
      <span className="relative flex items-center gap-2">
        {connecting && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        )}
        {connecting ? 'Check wallet…' : 'Connect Wallet'}
      </span>
    </button>
  )
}
