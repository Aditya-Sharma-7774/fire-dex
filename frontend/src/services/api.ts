/**
 * Typed client for the Fire DEX backend.
 *
 * Every backend call in the app goes through this file. Components never
 * call `fetch` directly -- that keeps error handling, base URLs and (later)
 * auth headers in exactly one place.
 *
 * From a later milestone these types will be generated from the backend's
 * OpenAPI schema instead of hand-written, so the two halves cannot drift.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export type AppMode = 'development' | 'testnet' | 'production'

export interface HealthResponse {
  status: string
  app: string
  version: string
  mode: AppMode
  timestamp: string
}

export interface ChainStatusResponse {
  chain: string
  configured: boolean
  reachable: boolean
  chain_id: number | null
  block_number: number | null
  error: string | null
}

export interface NativeBalanceResponse {
  chain: string
  address: string
  symbol: string
  decimals: number
  /**
   * Exact balance in the smallest unit (wei), as a STRING.
   *
   * Wei routinely exceeds Number.MAX_SAFE_INTEGER, so parsing this as a
   * JavaScript number would silently corrupt it. Use BigInt(raw) when you
   * need to do arithmetic.
   */
  raw: string
  formatted: string
  fetched_at: string
}

export interface PriceResponse {
  coingecko_id: string
  symbol: string
  usd: number
  change_24h: number | null
  market_cap: number | null
  volume_24h: number | null
  data_timestamp: string | null
  fetched_at: string
  source: string
  /** True when this price came from cache past its TTL. The UI must say so. */
  is_stale: boolean
}

export interface TokenBalanceResponse {
  symbol: string
  name: string
  chain: string
  address: string | null
  decimals: number
  is_native: boolean
  /** Exact amount in the smallest unit, as a string. "unknown" if unreadable. */
  raw: string
  formatted: string
  /** null means "we could not price this", never "it is worthless". */
  price_usd: number | null
  value_usd: number | null
  change_24h: number | null
  price_is_stale: boolean
}

export interface PortfolioResponse {
  chain: string
  address: string
  balances: TokenBalanceResponse[]
  /** null when nothing could be priced -- distinct from a genuine zero. */
  total_value_usd: number | null
  priced_count: number
  unpriced_count: number
  fetched_at: string
  contains_stale_prices: boolean
}

export interface TokenConfigResponse {
  symbol: string
  name: string
  chain: string
  address: string | null
  decimals: number
  coingecko_id: string | null
  is_native: boolean
  is_stablecoin: boolean
}

export interface AiProviderStatus {
  provider: string
  model: string
  available: boolean
  base_url?: string
}

export interface AiStatusResponse {
  preference: string
  local: AiProviderStatus
  online: AiProviderStatus
  any_available: boolean
}

export interface AnalysisHistoryItem {
  result_id: string
  query: string
  subject: string
  chain: string | null
  model: string | null
  provider: string | null
  mode: string | null
  reviewer_score: number | null
  reviewer_verdict: string | null
  confidence: number | null
  evidence_count: number
  evidence_coverage: number | null
  agents_completed: number
  agents_failed: number
  duration_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  data_stale: boolean
  result_hash: string
  created_at: string
}

export interface AnalysisDetailResponse extends AnalysisHistoryItem {
  address: string | null
  summary: string | null
  evidence: Array<Record<string, unknown>>
  agent_results: Array<Record<string, unknown>>
  reviewer_result: Record<string, unknown> | null
  executions: Array<Record<string, unknown>>
  prev_hash: string
  canonical_json: string
}

export interface VerificationResponse {
  result_id: string
  valid: boolean
  stored_hash: string
  computed_hash: string
  chain_intact: boolean
  message: string
}

/** Shape of the backend's error responses. */
interface ApiErrorBody {
  error: string
  message: string
  detail: string | null
}

/** Thrown for any non-2xx response, so callers get one error type. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
    readonly detail?: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * In-flight request deduplication.
 *
 * Several components legitimately want the same data -- the balance card and
 * the holdings panel both need the portfolio, and their poll timers drift
 * into alignment. Without this, each component issues its own identical
 * request, doubling load on our backend and on the public node behind it.
 *
 * When a GET for a path is already in flight, later callers receive the same
 * promise instead of starting a second request. Entries are removed as soon
 * as the request settles, so this is deduplication, not caching -- no
 * response is ever served from here after the fact.
 */
const inFlight = new Map<string, Promise<unknown>>()

function dedupe<T>(key: string, run: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key)
  if (existing) return existing as Promise<T>

  const promise = run().finally(() => inFlight.delete(key))
  inFlight.set(key, promise)
  return promise
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Only GETs are safe to deduplicate; a repeated write must actually repeat.
  if (!init?.method || init.method === 'GET') {
    return dedupe(path, () => performRequest<T>(path, init))
  }
  return performRequest<T>(path, init)
}

async function performRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    // Network-level failure: backend not running, DNS, CORS preflight, offline.
    throw new ApiError(
      `Cannot reach the Fire DEX backend at ${API_BASE_URL}. Is it running?`,
    )
  }

  if (!response.ok) {
    // The backend sends structured errors; surface its message rather than
    // a generic "request failed", so the user learns something useful.
    let body: Partial<ApiErrorBody> = {}
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      /* non-JSON error body; fall through to the generic message */
    }
    throw new ApiError(
      body.message ?? `Request to ${path} failed`,
      response.status,
      body.error,
      body.detail ?? null,
    )
  }

  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  chainStatus: (chain: string) =>
    request<ChainStatusResponse>(`/api/v1/chains/${chain}/status`),

  nativeBalance: (chain: string, address: string) =>
    request<NativeBalanceResponse>(
      `/api/v1/chains/${chain}/balance/${address}`,
    ),

  tokens: (chain: string) => request<TokenConfigResponse[]>(`/api/v1/tokens/${chain}`),

  prices: (ids?: string[]) =>
    request<Record<string, PriceResponse>>(
      `/api/v1/market/prices${ids?.length ? `?ids=${ids.join(',')}` : ''}`,
    ),

  portfolio: (chain: string, address: string) =>
    request<PortfolioResponse>(`/api/v1/portfolio/${chain}/${address}`),

  aiStatus: () => request<AiStatusResponse>('/api/v1/ai/status'),

  history: (limit = 25) =>
    request<AnalysisHistoryItem[]>(`/api/v1/analysis/history?limit=${limit}`),

  analysis: (resultId: string) =>
    request<AnalysisDetailResponse>(`/api/v1/analysis/${resultId}`),

  verify: (resultId: string) =>
    request<VerificationResponse>(`/api/v1/analysis/${resultId}/verify`),
}

export { API_BASE_URL }
