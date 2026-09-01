import { NetworkSelector } from '../features/wallet/NetworkSelector'
import { WalletButton } from '../features/wallet/WalletButton'
import type { HealthResponse } from '../services/api'

type Tab = 'dashboard' | 'fire-ai' | 'history'

interface HeaderProps {
  health: HealthResponse | null
  healthError: string | null
  loading: boolean
  tab: Tab
  onTabChange: (tab: Tab) => void
}

const NAV_ITEMS: { label: string; tab: Tab }[] = [
  { label: 'Dashboard', tab: 'dashboard' },
  { label: 'Fire AI', tab: 'fire-ai' },
  { label: 'History', tab: 'history' },
]

/**
 * Top navigation bar.
 *
 * Layout note: the three groups are logo / nav / controls. The controls
 * group holds a network selector and a wallet address, which grow once a
 * wallet is connected. The nav therefore hides below `xl` rather than `lg`,
 * and every group is allowed to shrink -- otherwise the two sides collide
 * at around 1024px as soon as real data arrives.
 */
export function Header({ health, healthError, loading, tab, onTabChange }: HeaderProps) {
  return (
    <header className="sticky top-0 z-40 border-b hairline bg-coal-950/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
        {/* Logo */}
        <button
          type="button"
          onClick={() => onTabChange('dashboard')}
          className="group flex shrink-0 items-center gap-2.5"
        >
          <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-fire-400 to-fire-700 shadow-glow transition-transform duration-300 group-hover:scale-105">
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
        </button>

        {/* Navigation. Hidden below xl so it cannot collide with the wallet
            controls once an address is displayed. */}
        <nav className="ml-4 hidden min-w-0 items-center gap-1 lg:flex">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.tab}
              type="button"
              onClick={() => onTabChange(item.tab)}
              className={
                tab === item.tab
                  ? 'rounded-lg bg-fire-500/10 px-3 py-1.5 text-sm font-medium text-fire-300'
                  : 'rounded-lg px-3 py-1.5 text-sm font-medium text-coal-500 transition-colors hover:bg-white/[0.04] hover:text-coal-200'
              }
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex min-w-0 items-center gap-2">
          <BackendPill health={health} error={healthError} loading={loading} />
          <NetworkSelector />
          <WalletButton />
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
      className="hidden shrink-0 items-center gap-2 rounded-xl border hairline px-2.5 py-2 md:flex"
    >
      <span className="relative flex h-1.5 w-1.5">
        {!loading && !error && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${state.dot}`} />
      </span>
      <span className={`text-xs font-medium ${state.tone}`}>
        <span className="hidden lg:inline">API </span>
        {state.text}
      </span>
    </div>
  )
}
