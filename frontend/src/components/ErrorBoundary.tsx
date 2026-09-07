import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Catches render errors so one broken component cannot blank the page.
 *
 * Without this, any exception thrown during render unmounts the entire
 * React tree and leaves a white screen — no header, no navigation, no way
 * back. That is a bad thirty seconds in front of an examiner, and it is
 * exactly the kind of failure that happens when live market data returns
 * something unexpected.
 *
 * Error boundaries must be class components. Hooks cannot catch render
 * errors; there is no functional equivalent.
 *
 * NOTE ON SCOPE: this catches errors during RENDER. It does not catch
 * errors inside event handlers or async code — those already have their
 * own try/catch in the API client and the wallet layer.
 */

interface Props {
  children: ReactNode
  /** Shown in the message so the user knows which part failed. */
  section?: string
  /** Lets the parent reset the boundary, e.g. on tab change. */
  resetKey?: string | number
}

interface State {
  error: Error | null
  info: ErrorInfo | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept in the console so the stack is still available to a developer
    // while the user sees something readable.
    console.error('Render error caught by boundary:', error, info.componentStack)
    this.setState({ info })
  }

  componentDidUpdate(previous: Props): void {
    // Recover automatically when the parent signals a change — switching
    // tabs should not leave the user stuck on an old error.
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null, info: null })
    }
  }

  private reset = () => this.setState({ error: null, info: null })

  render(): ReactNode {
    const { error, info } = this.state
    if (!error) return this.props.children

    const where = this.props.section ? ` in ${this.props.section}` : ''

    return (
      <section className="glass animate-fade-up p-6 sm:p-8" role="alert">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-xl leading-none" aria-hidden="true">
            ⚠
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-bold tracking-tight text-red-300">
              Something broke{where}
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-coal-400">
              The rest of Fire DEX is still running — only this section failed. Your wallet
              connection and any saved analyses are unaffected.
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={this.reset}
                className="rounded-xl bg-gradient-to-br from-fire-500 to-fire-700 px-4 py-2 text-sm font-semibold text-white shadow-glow transition-all hover:shadow-glow-lg"
              >
                Try again
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-xl border hairline px-4 py-2 text-sm font-medium text-coal-300 transition-colors hover:border-fire-500/30 hover:text-coal-100"
              >
                Reload the page
              </button>
            </div>

            {/* The technical detail is available but not shouted. */}
            <details className="mt-4">
              <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-coal-600 hover:text-coal-400">
                Technical detail
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-xl border hairline bg-coal-900/60 p-3 text-[10px] leading-relaxed text-coal-400">
                {error.message}
                {info?.componentStack}
              </pre>
            </details>
          </div>
        </div>
      </section>
    )
  }
}
