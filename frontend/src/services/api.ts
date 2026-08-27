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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
}

export { API_BASE_URL }
