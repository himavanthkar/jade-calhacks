import { describe, expect, test } from 'bun:test'
import { createHttpApi, ApiError } from '../src/api/client'
import { createMockApi } from '../src/api/mock'

describe('HTTP contract', () => {
  test('encodes answer path and body, accepts empty success', async () => {
    let url = ''; let init: RequestInit | undefined
    const fetcher = (async (input: string | URL | Request, options?: RequestInit) => { url = String(input); init = options; return new Response(null, { status: 204 }) }) as typeof fetch
    await createHttpApi('/api/', fetcher).answerEscalation('a/b', 'Hold')
    expect(url).toBe('/api/escalations/a%2Fb/answer')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ answer: 'Hold' })
  })
  test('preserves authorization failures without retry', async () => {
    let calls = 0
    const fetcher = (async () => { calls++; return new Response('{"detail":"SoD block"}', { status: 403 }) }) as typeof fetch
    try { await createHttpApi('/api', fetcher).stepPeriod('2026-01'); throw new Error('Expected failure') }
    catch (error) { expect(error).toBeInstanceOf(ApiError); expect((error as ApiError).status).toBe(403) }
    expect(calls).toBe(1)
  })
  test('rejects invalid month before requesting', () => {
    expect(() => createHttpApi().getPeriod('2026-13')).toThrow('YYYY-MM')
  })
})
describe('mock flow', () => {
  test('step, answer and refresh; independent sessions and immutable reads', async () => {
    const api = createMockApi()
    expect((await api.getPeriod('2026-01')).state).toBe('OPEN')
    await api.stepPeriod('2026-01')
    const period = await api.getPeriod('2026-01')
    expect(period.state).toBe('ESCALATED')
    expect(period.postings.reduce((sum, p) => sum + Number(p.debit) - Number(p.credit), 0)).toBe(0)
    expect((await api.explainEntry(period.postings[0].id)).line.id).toBe(period.postings[0].id)
    const [card] = await api.getEscalations()
    await api.answerEscalation(card.id, String(card.options[0]))
    expect(await api.getEscalations()).toHaveLength(0)
    expect((await api.getPeriod('2026-01')).state).toBe('CONTROLLED')
    expect(await createMockApi().getEscalations()).toHaveLength(1)
    const controls = await api.getControls(); controls[0].name = 'changed'
    expect((await api.getControls())[0].name).not.toBe('changed')
  })
  test('aborted mutations leave session untouched', async () => {
    const api = createMockApi(); const controller = new AbortController(); controller.abort()
    await expect(api.stepPeriod('2026-01', { signal: controller.signal })).rejects.toThrow()
    expect((await api.getPeriod('2026-01')).state).toBe('OPEN')
  })
})

describe('jade backend response compatibility', () => {
  test('maps owner_role, preserves decimal strings and nullable thresholds', async () => {
    const rows = [{ id: 'CTL-SCAN-NO-BACKUP', name: 'Missing backup', owner_role: 'deduction_analyst', threshold: null, threshold_unit: null, fired_count: 2, learned: true, precedent_ids: [] }]
    const fetcher = (async () => Response.json(rows)) as typeof fetch
    const [control] = await createHttpApi('/api', fetcher).getControls()
    expect(control.owner).toBe('deduction_analyst')
    expect(control.threshold).toBeNull()
  })
  test('retains null metrics and evaluator diagnostics', async () => {
    const data = { precision: null, recall: 0, escalation_rate: null, autonomy: 0.5, counts: { findings: 0 }, missed: [] }
    const fetcher = (async () => Response.json(data)) as typeof fetch
    expect(await createHttpApi('/api', fetcher).getMetrics('2026-01')).toEqual(data)
  })
  test('preserves backend ledger history and decimal amounts', async () => {
    const api = createMockApi(); await api.stepPeriod('2026-02')
    const [line] = (await api.getPeriod('2026-02')).postings
    expect(line.customer_id).toBe('WMT')
    expect(line.valid_time).toBe('2026-02-28')
    const history = await api.explainEntry(line.id)
    const response = { ...history, line: { ...line, debit: '10000.00' } }
    const fetcher = (async () => Response.json(response)) as typeof fetch
    expect(await createHttpApi('/api', fetcher).explainEntry(line.id)).toEqual(response)
  })
})
