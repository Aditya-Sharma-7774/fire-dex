import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, clearImmutableCache } from './api'

/**
 * Tests for the API client's caching and deduplication.
 *
 * The distinction here is the important part: a stored analysis is
 * immutable by construction and may be cached, while prices and balances
 * change constantly and must never be. Caching the wrong thing would be
 * exactly the stale-data dishonesty the project exists to avoid.
 */

const ANALYSIS = {
  result_id: 'FIRE-2026-000001',
  query: 'Analyse ETH',
  evidence: [],
  agent_results: [],
  executions: [],
}

function mockFetch(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  } as Response)
}

beforeEach(() => {
  clearImmutableCache()
  vi.restoreAllMocks()
})

describe('immutable caching', () => {
  it('fetches a stored analysis once, then serves it from cache', async () => {
    // Measured before this: expanding the same history row twice cost 3
    // network calls.
    const fetchSpy = mockFetch(ANALYSIS)
    vi.stubGlobal('fetch', fetchSpy)

    await api.analysis('FIRE-2026-000001')
    await api.analysis('FIRE-2026-000001')
    await api.analysis('FIRE-2026-000001')

    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('does not confuse two different analyses', async () => {
    const fetchSpy = mockFetch(ANALYSIS)
    vi.stubGlobal('fetch', fetchSpy)

    await api.analysis('FIRE-2026-000001')
    await api.analysis('FIRE-2026-000002')

    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('never caches prices', async () => {
    // Prices change constantly. Serving a cached one would present stale
    // data as current, which is the failure mode this project is built to
    // prevent.
    const fetchSpy = mockFetch({ ethereum: { usd: 2500 } })
    vi.stubGlobal('fetch', fetchSpy)

    await api.prices()
    await api.prices()

    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('never caches balances', async () => {
    const fetchSpy = mockFetch({ raw: '1000', formatted: '1' })
    vi.stubGlobal('fetch', fetchSpy)

    await api.nativeBalance('ethereum', '0xabc')
    await api.nativeBalance('ethereum', '0xabc')

    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('never caches verification, so tampering is always re-checked', async () => {
    // If this were cached, altering the database and clicking Verify again
    // would show the old "intact" answer — defeating the entire point.
    const fetchSpy = mockFetch({ valid: true, message: 'intact' })
    vi.stubGlobal('fetch', fetchSpy)

    await api.verify('FIRE-2026-000001')
    await api.verify('FIRE-2026-000001')

    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })
})

describe('in-flight deduplication', () => {
  it('shares one request between concurrent identical callers', async () => {
    let resolve!: (v: unknown) => void
    const pending = new Promise((r) => (resolve = r))
    const fetchSpy = vi.fn().mockReturnValue(
      pending.then(() => ({ ok: true, json: async () => ({ usd: 1 }) }) as unknown as Response),
    )
    vi.stubGlobal('fetch', fetchSpy)

    const both = Promise.all([api.prices(), api.prices()])
    resolve(null)
    await both

    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })
})
