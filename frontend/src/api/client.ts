import { adaptControls, adaptMetrics } from './adapters'
import type { AsOfOptions, Control, Metrics, RequestOptions, SyncResult, TradePromotionApi } from './types'

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
/** The API's `kind` on a refusal: 'segregation_of_duties' (403) or 'gate_failure' (409). */
export function errorKind(error: unknown): string | undefined {
  const d = error instanceof ApiError ? error.details : undefined
  return typeof d === 'object' && d && 'kind' in d ? String((d as { kind: unknown }).kind) : undefined
}
export function validatePeriod(period: string) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) throw new Error('Period must use YYYY-MM format.')
  return period
}
function query(params: Record<string, string | undefined>) {
  const entries = Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined)
  return entries.length ? `?${new URLSearchParams(entries)}` : ''
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
    // FastAPI puts the reason in `detail`; a 403 with kind 'segregation_of_duties' is the SoD throw.
    if (!response.ok) {
      const detail = typeof data === 'object' && data && 'detail' in data ? String((data as { detail: unknown }).detail) : undefined
      throw new ApiError(response.status, detail ?? `API request failed (${response.status})`, data)
    }
    // A mutation may answer with nothing; refetch what it changed either way.
    if (mutation) return (raw ? data : undefined) as T
    if (!raw || typeof data === 'string') throw new ApiError(response.status, 'Expected a JSON response.', data)
    return data as T
  }
  return {
    getClock: options => request('/clock', options),
    getPeriod: (period, options?: AsOfOptions) => request(`/period/${validatePeriod(period)}${query({ as_of: options?.asOf })}`, options),
    stepPeriod: (period, options) => request(`/period/${validatePeriod(period)}/step`, options, undefined, true),
    signPeriod: async (period, customerId, signedBy, options) => {
      await request(`/period/${validatePeriod(period)}/sign`, options, { customer_id: customerId, ...(signedBy ? { signed_by: signedBy } : {}) }, true)
    },
    getPackage: (period, options) => request(`/period/${validatePeriod(period)}/package${query({ as_of: options?.asOf })}`, options),
    exportUrl: (period, file, asOf) => `${base}/period/${validatePeriod(period)}/export/${file}${query({ as_of: asOf })}`,
    getControls: async options => adaptControls(await request<Control[]>('/controls', options)),
    getPrecedent: (kind, id, options) => request(`/precedents/${kind}/${encodeURIComponent(id)}`, options),
    getEscalations: options => request(`/escalations${query({ open: String(options?.open ?? true) })}`, options),
    answerEscalation: (id, answer, options) => request(`/escalations/${encodeURIComponent(id)}/answer`, options,
      { answer, answered_by: options?.answeredBy, reasoning: options?.reasoning }, true),
    explainEntry: (id, options) => request(`/explain/${encodeURIComponent(id)}`, options),
    ask: (question, options) => request('/ask', options, { question }, true),
    getMetrics: async (period, options) => adaptMetrics(await request<Metrics>(`/metrics?as_of=${encodeURIComponent(period)}`, options)),
    getIntegrations: options => request('/integrations', options),
    getInbox: options => request('/inbox', options),
    syncInbox: async (step = false, options) => (await request<SyncResult>('/inbox/sync', options, { step }, true)) ?? { landed: [] },
    getScenarioExamples: options => request('/scenario/examples', options),
    getInjections: options => request('/scenario', options),
    injectScenario: (kind, payload, options) => request('/scenario', options,
      { kind, payload, step: options?.step ?? false, injected_by: options?.injectedBy }, true),
  }
}
