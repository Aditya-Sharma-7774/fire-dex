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

/** Thrown for any non-2xx response, so callers get one error type. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
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
    throw new ApiError(`Request to ${path} failed`, response.status)
  }

  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),
}

export { API_BASE_URL }
