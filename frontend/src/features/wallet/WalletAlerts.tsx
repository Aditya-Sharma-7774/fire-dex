import { ACTIVE_CHAINS } from '../../config/chains'
import { useWallet } from './WalletContext'

/**
 * Banners for the two wallet situations that must never be silent.
 *
 * Wrong network is the important one. If the wallet is on a chain we do not
 * support and we say nothing, every figure on screen is meaningless -- the
 * user believes they are looking at their assets when they are not.
 */
export function WalletAlerts() {
  const { isUnsupportedNetwork, chainId, error, clearError, switchToChain, status } = useWallet()

  const showNetworkWarning = status === 'connected' && isUnsupportedNetwork

  if (!showNetworkWarning && !error) return null

  return (
    <div className="mx-auto w-full max-w-7xl space-y-3 px-4 pt-5 sm:px-6">
      {showNetworkWarning && (
        <div className="animate-fade-up rounded-2xl border border-amber-500/30 bg-amber-500/[0.07] p-4">
          <div className="flex flex-wrap items-start gap-3">
            <span className="mt-0.5 text-lg leading-none" aria-hidden="true">
              ⚠
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-amber-300">Unsupported network</div>
              <p className="mt-1 text-xs leading-relaxed text-amber-200/70">
                Your wallet is on chain ID <span className="font-mono">{chainId}</span>, which Fire
                DEX does not support. Balances are not shown, because showing them would be
                misleading. Switch to a supported network to continue.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {ACTIVE_CHAINS.map((chain) => (
                  <button
                    key={chain.id}
                    type="button"
                    onClick={() => void switchToChain(chain.id)}
                    className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-500/20"
                  >
                    Switch to {chain.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="animate-fade-up flex items-start gap-3 rounded-2xl border border-red-500/30 bg-red-500/[0.07] p-4">
          <span className="mt-0.5 text-lg leading-none" aria-hidden="true">
            ✕
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-red-300">Wallet request failed</div>
            <p className="mt-1 text-xs leading-relaxed text-red-200/70">{error}</p>
          </div>
          <button
            type="button"
            onClick={clearError}
            className="shrink-0 rounded-lg px-2 py-1 text-xs text-red-300/70 transition-colors hover:bg-red-500/10 hover:text-red-200"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}
