import type { HealthResponse } from '../services/api'
import { CHAIN_LIST } from '../config/chains'

interface HeaderProps {
  health: HealthResponse | null
  healthError: string | null
  loading: boolean
}

/**
 * Top navigation bar.
 *
 * Milestone 1 renders the real structure with inert controls, so the layout
 * is settled before behaviour lands. The network selector and Connect Wallet
 * button become functional in Milestone 2.
 */
export function Header({ health, healthError, loading }: HeaderProps) {
  const activeChains = CHAIN_LIST.filter((c) => c.status === 'active').length

  return (
    <header className="sticky top-0 z-50 border-b hairline bg-coal-950/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-fire-400 to-fire-700 shadow-glow">
            <span className="text-lg leading-none">🔥</span>
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight">
              FIRE <span className="fire-text">DEX</span>
            </div>
            <div className="hidden text-[10px] uppercase tracking-[0.14em] text-coal-400 sm:block">
              Multi-Chain Intelligence
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="ml-6 hidden items-center gap-1 lg:flex">
          {[
            { label: 'Dashboard', active: true },
            { label: 'Fire AI', active: false },
            { label: 'History', active: false },
            { label: 'Audit', active: false },
          ].map((item) => (
            <button
              key={item.label}
              type="button"
              disabled={!item.active}
              className={
                item.active
                  ? 'rounded-lg bg-fire-500/10 px-3 py-1.5 text-sm font-medium text-fire-300'
                  : 'rounded-lg px-3 py-1.5 text-sm font-medium text-coal-500 transition-colors hover:text-coal-300 disabled:cursor-not-allowed disabled:hover:text-coal-500'
              }
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          {/* Backend status -- real, live data */}
          <BackendPill health={health} error={healthError} loading={loading} />

          {/* Network selector -- Milestone 2 */}
          <button
            type="button"
            disabled
            className="hidden items-center gap-2 rounded-xl border hairline px-3 py-2 text-xs font-medium text-coal-400 sm:flex"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-coal-500" />
            {activeChains > 0 ? 'Select Network' : 'No Network'}
            <span className="text-coal-600">▾</span>
          </button>

          {/* Wallet -- Milestone 2 */}
          <button
            type="button"
            disabled
            className="rounded-xl bg-gradient-to-br from-fire-500 to-fire-700 px-3.5 py-2 text-xs font-semibold text-white opacity-55 shadow-glow sm:px-4 sm:text-sm"
          >
            Connect Wallet
          </button>
        </div>
      </div>
    </header>
  )
}

function BackendPill({
  health,
  error,
  loading,
}: {
  health: HealthResponse | null
  error: string | null
  loading: boolean
}) {
  const state = loading
    ? { dot: 'bg-coal-500', text: 'Checking', tone: 'text-coal-400' }
    : error
      ? { dot: 'bg-red-500', text: 'Offline', tone: 'text-red-400' }
      : { dot: 'bg-emerald-400', text: 'Online', tone: 'text-emerald-400' }

  return (
    <div
      title={error ?? (health ? `${health.app} v${health.version} · ${health.mode}` : '')}
      className="flex items-center gap-2 rounded-xl border hairline px-2.5 py-2 sm:px-3"
    >
      <span className="relative flex h-1.5 w-1.5">
        {!loading && !error && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${state.dot}`} />
      </span>
      <span className={`text-xs font-medium ${state.tone}`}>
        <span className="hidden sm:inline">API </span>
        {state.text}
      </span>
    </div>
  )
}
