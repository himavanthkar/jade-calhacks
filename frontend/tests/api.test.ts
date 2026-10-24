import { describe, expect, test } from 'bun:test'
import { ApiError, createHttpApi } from '../src/api/client'
import { createMockApi } from '../src/api/mock'

describe('HTTP contract', () => {
  test('encodes answer path and body, accepts empty success', async () => {
    let url = ''; let init: RequestInit | undefined
    const fetcher = (async (input: string | URL | Request, options?: RequestInit) => { url = String(input); init = options; return new Response(null, { status: 204 }) }) as typeof fetch
    expect(await createHttpApi('/api/', fetcher).answerEscalation('a/b', 'hold', { reasoning: 'Waiting on backup.' })).toBeUndefined()
    expect(url).toBe('/api/escalations/a%2Fb/answer')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ answer: 'hold', reasoning: 'Waiting on backup.' })
  })
  test('surfaces the SoD throw with its reason, without retry', async () => {
    let calls = 0
    const body = '{"detail":"Walmart sales lead negotiated TP-0214 for Walmart; approval routed to controller.","kind":"segregation_of_duties"}'
    const fetcher = (async () => { calls++; return new Response(body, { status: 403 }) }) as typeof fetch
    try { await createHttpApi('/api', fetcher).stepPeriod('2026-01'); throw new Error('Expected failure') }
    catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(403)
      expect((error as ApiError).message).toContain('approval routed to controller')
    }
    expect(calls).toBe(1)
  })
  test('rejects invalid month before requesting', () => {
    expect(() => createHttpApi().getPeriod('2026-13')).toThrow('YYYY-MM')
  })
  test('as-of reads and exports carry the moment in the query', async () => {
    const urls: string[] = []
    const fetcher = (async (input: string | URL | Request) => { urls.push(String(input)); return Response.json({}) }) as typeof fetch
    const api = createHttpApi('/api', fetcher)
    await api.getPeriod('2026-02', { asOf: 'month-2' })
    await api.getPackage('2026-02', { asOf: 'month-8' })
    expect(urls).toEqual(['/api/period/2026-02?as_of=month-2', '/api/period/2026-02/package?as_of=month-8'])
    expect(api.exportUrl('2026-02', 'ledger.csv', 'month-2')).toBe('/api/period/2026-02/export/ledger.csv?as_of=month-2')
  })
})

describe('mock replays the real API', () => {
  test('controls appear once onboarding has run, on the first step', async () => {
    const api = createMockApi()
    expect(await api.getControls()).toEqual([])
    await api.stepPeriod('2026-01')
    const controls = await api.getControls()
    expect(controls.length).toBeGreaterThan(10)
    expect(controls.every(c => Number.isInteger(c.fired_count) && typeof c.owner === 'string')).toBe(true)
  })
  test('steps in order, amounts are decimal strings and journals balance', async () => {
    const api = createMockApi()
    expect((await api.getPeriod('2026-01')).state).toBe('OPEN')
    await expect(api.stepPeriod('2026-02')).rejects.toThrow('the clock is at 2026-01')
    await api.stepPeriod('2026-01')
    expect((await api.getClock()).current_period).toBe('2026-02')
    const period = await api.getPeriod('2026-01')
    expect(period.postings.every(p => typeof p.debit === 'string')).toBe(true)
    const cents = period.postings.reduce((sum, p) => sum + Math.round(Number(p.debit) * 100) - Math.round(Number(p.credit) * 100), 0)
    expect(cents).toBe(0)
    expect(period.findings.some(f => f.escalation_type === 'sod')).toBe(true)        // the Kroger sales lead's attempt
  })
  test('answering writes a precedent, settles its siblings and frees the period for sign-off', async () => {
    const api = createMockApi()
    await api.stepPeriod('2026-01')
    const [card] = await api.getEscalations()
    expect(card.options.every(o => o.id && o.label && o.decision)).toBe(true)
    await expect(api.answerEscalation(card.id, 'nope')).rejects.toThrow('not an option')
    await expect(api.answerEscalation(card.id, card.options[0].id, { answeredBy: 'sales.walmart' })).rejects.toThrow('cannot answer')
    const result = (await api.answerEscalation(card.id, card.options[0].label))!
    expect(result.precedent_id).toMatch(/^PR-/)
    const open = await api.getEscalations()
    expect(open.map(e => e.id)).not.toContain(card.id)
    for (const id of result.settled) expect(open.map(e => e.id)).not.toContain(id)
    for (const e of open) await api.answerEscalation(e.id, e.options[0].id)
    const period = await api.getPeriod('2026-01')
    const reviewed = period.customers.filter(c => c.state === 'REVIEWED')
    expect(reviewed.length).toBeGreaterThan(0)
    await api.signPeriod('2026-01', reviewed[0].customer_id)
    expect((await api.getPeriod('2026-01')).customers.find(c => c.customer_id === reviewed[0].customer_id)!.state).toBe('SIGNED')
  })
  test('explain and ask return the evidence chain', async () => {
    const api = createMockApi()
    await api.stepPeriod('2026-01')
    const line = (await api.getPeriod('2026-01')).postings.find(p => p.account.startsWith('2300'))!
    const ex = await api.explainEntry(line.id)
    expect(ex.chain.steps.length).toBeGreaterThan(0)
    expect((await api.ask(`Why did you post ${line.id}?`)).chains[0].entry_id).toBe(line.id)
    expect((await api.ask('hello?')).chains).toEqual([])
  })
  test('the moment: February has two correct answers', async () => {
    const api = createMockApi('moment')
    expect((await api.getClock()).current_period).toBe('2026-09')
    const aug = await api.getPeriod('2026-08')
    expect(aug.findings.some(f => f.conflict_type === 'amendment_not_applied')).toBe(true)
    const then = await api.getPackage('2026-02', { asOf: 'month-2' })
    const now = await api.getPackage('2026-02', { asOf: 'month-8' })
    const liability = (p: typeof then) => p.customers.find(c => c.customer_id === 'WMT')!.balances['2300 Accrued trade promotion liability']
    expect(liability(then)).not.toBe(liability(now))
    const asks = await api.ask('What did it know in March?')
    expect(asks.answer).toContain('AM-02')
    const m1 = await api.getMetrics('month-1'), m8 = await api.getMetrics('month-8')
    expect(m1.recall).not.toBeNull(); expect(m8.recall).not.toBeNull()
  })
  test('sessions are independent and reads are copies', async () => {
    const api = createMockApi(); await api.stepPeriod('2026-01')
    const controls = await api.getControls(); controls[0].name = 'changed'
    expect((await api.getControls())[0].name).not.toBe('changed')
    expect(await createMockApi().getEscalations()).toEqual([])
  })
  test('aborted mutations leave the session untouched', async () => {
    const api = createMockApi(); const controller = new AbortController(); controller.abort()
    await expect(api.stepPeriod('2026-01', { signal: controller.signal })).rejects.toThrow()
    expect((await api.getPeriod('2026-01')).state).toBe('OPEN')
  })
})
