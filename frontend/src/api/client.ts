import { adaptControls, adaptMetrics } from './adapters'
import type { Control, Metrics } from './types'
import type { TradePromotionApi, RequestOptions } from './types'

export class ApiError extends Error {
  status: number
  details: unknown
  constructor(status: number, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}
export function validatePeriod(period: string) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) throw new Error('Period must use YYYY-MM format.')
  return period
}

/** No automatic POST retries: stepping or answering twice can change the books. */
export function createHttpApi(baseUrl = '/api', fetcher: typeof fetch = fetch): TradePromotionApi {
  const base = baseUrl.replace(/\/$/, '')
  async function request<T>(path: string, options?: RequestOptions, body?: unknown, mutation = false): Promise<T> {
    const response = await fetcher(`${base}${path}`, {
      method: mutation ? 'POST' : 'GET',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options?.signal,
    })
    const raw = await response.text()
    let data: unknown
    try { data = raw ? JSON.parse(raw) : undefined } catch { data = raw }
    if (!response.ok) throw new ApiError(response.status, `API request failed (${response.status})`, data)
    // The spec does not define mutation response bodies. Refetch after success.
    if (mutation) return undefined as T
    if (!raw || typeof data === 'string') throw new ApiError(response.status, 'Expected a JSON response.', data)
    return data as T
  }
  return {
    getPeriod: (period, options) => request(`/period/${validatePeriod(period)}`, options),
    stepPeriod: (period, options) => request(`/period/${validatePeriod(period)}/step`, options, undefined, true),
    getControls: async options => adaptControls(await request<Control[]>('/controls', options)),
    getEscalations: options => request('/escalations?open=true', options),
    answerEscalation: (id, answer, options) => request(`/escalations/${encodeURIComponent(id)}/answer`, options, { answer }, true),
    explainEntry: (id, options) => request(`/explain/${encodeURIComponent(id)}`, options),
    getMetrics: async (period, options) => adaptMetrics(await request<Metrics>(`/metrics?as_of=${validatePeriod(period)}`, options)),
  }
}
