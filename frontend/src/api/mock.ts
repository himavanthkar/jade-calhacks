import { ApiError, validatePeriod } from './client'
import inboxData from './fixtures/inbox.json'
import momentData from './fixtures/moment.json'
import mailData from './fixtures/mail.json'
import backtestData from './fixtures/backtest.json'
import type {
  AnswerResult, AskResponse, Backtest, Clock, Control, CustomerId, Escalation, Evidence, Explanation, InboundMessage, Integration,
  Metrics, Period, PeriodState, RequestOptions, ScenarioExample, SignoffPackage, StepSummary, TradePromotionApi,
} from './types'

/**
 * Replays responses captured from the real API (seed 1337; see fixtures/README.md). No accounting
 * happens here: stepping reveals the captured month, answering removes the card and settles cards
 * with the same control and customer, as a precedent would.
 *
 *   inbox   January and February stepped with every card left for a person (default)
 *   moment  month 8 after AM-02: the restatement approved, the February accrual's two answers
 */
export type MockScenario = 'inbox' | 'moment'

interface MonthFixture { step: StepSummary; period: Period; escalations: Escalation[]; controls: Control[]; metrics: Metrics; explain: Record<string, Explanation> }
const inbox = inboxData as unknown as { clock: Clock; controls: Control[]; months: Record<string, MonthFixture> }
const moment = momentData as unknown as {
  clock: Clock; period: Period; controls: Control[]; escalations_answered: Escalation[]; feb_accrual: Explanation
  feb_package_then: SignoffPackage; feb_package_now: SignoffPackage; metrics: Record<string, Metrics>; asks: AskResponse[]
}
/** October after the side letter, the claim it is about, and the signed amendment (scripts/mail_fixture.py). */
const mail = mailData as unknown as { integrations: Integration[]; inbox: InboundMessage[]; escalations: Escalation[] }
/** GET /api/backtest and the played year's monthly metrics (scripts/backtest_fixture.py). */
const backtest = backtestData as unknown as { backtest: Backtest; series: Metrics[] }
const CUSTOMERS: CustomerId[] = ['COST', 'KR', 'WMT']
const ORDER: PeriodState[] = ['OPEN', 'ACCRUED', 'CONTROLLED', 'ESCALATED', 'REVIEWED', 'SIGNED', 'CLOSED', 'RESTATED']
const MONTHS = Object.keys(inbox.months)

function open(period: string): Period {
  return { period, state: 'OPEN', postings: [], findings: [], gates: {}, flux: [],
    customers: CUSTOMERS.map(customer_id => ({ period, customer_id, state: 'OPEN', signed_by: null, signed_at: null, gate_results: null })) }
}
function nextPeriod(period: string) {
  const [y, m] = period.split('-').map(Number)
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`
}

/** The same shapes tpa.scenario.examples returns, for browsing in the mock; injecting needs the API. */
const EXAMPLES = (period: string): ScenarioExample[] => [
  { title: 'Walmart short-pays a scan-back claim with no backup', kind: 'deduction',
    payload: { customer_id: 'WMT', program_id: 'TP-0214', amount: '48000.00', claimed_period: period, day: 5 } },
  { title: 'Walmart claims last month at $4.50/case', kind: 'deduction',
    payload: { customer_id: 'WMT', program_id: 'TP-0214', amount: '60000.00', claimed_period: period, claimed_rate: '4.50', day: 6,
      backup: { scan_units: 13333, scan_rate: '4.50' } } },
  { title: 'TP-0214 renegotiated down to $3.60/case, effective three months ago', kind: 'amendment',
    payload: { program_id: 'TP-0214', new_rate: '3.60', effective_date: `${period}-01`, day: 12 } },
]

export function createMockApi(scenario: MockScenario = 'inbox'): TradePromotionApi {
  const periods = new Map<string, Period>()
  const explain = new Map<string, Explanation>()
  let clock: Clock = structuredClone(inbox.clock)
  let controls: Control[] = []
  let cards: Escalation[] = []
  const answered: Escalation[] = []
  const metrics = new Map<string, Metrics>()
  let precedents = 0

  if (scenario === 'moment') {
    clock = structuredClone(moment.clock)
    controls = structuredClone(moment.controls)
    periods.set(moment.period.period, structuredClone(moment.period))
    explain.set(moment.feb_accrual.line.id, structuredClone(moment.feb_accrual))
    answered.push(...structuredClone(moment.escalations_answered))
    for (const [k, v] of Object.entries(moment.metrics)) metrics.set(k, v)
  }

  function finish<T>(value: T, options?: RequestOptions): Promise<T> {
    options?.signal?.throwIfAborted()
    return Promise.resolve(structuredClone(value))
  }
  function settle(period: Period, findingId: string) {
    const f = period.findings.find(x => x.id === findingId)
    if (!f) return
    f.state = 'resolved'
    const customer = period.customers.find(c => c.customer_id === f.customer_id)!
    const unresolved = period.findings.some(x => x.customer_id === f.customer_id && (x.state === 'open' || x.state === 'escalated'))
    if (!unresolved && customer.state === 'ESCALATED') customer.state = 'REVIEWED'
    period.state = period.customers.map(c => c.state).reduce((a, b) => (ORDER.indexOf(a) <= ORDER.indexOf(b) ? a : b))
  }

  return {
    getClock: options => finish(clock, options),
    getPeriod: (period, options) => finish(periods.get(validatePeriod(period)) ?? open(period), options),
    stepPeriod: async (period, options) => {
      options?.signal?.throwIfAborted()
      validatePeriod(period)
      if (period !== clock.current_period) throw new ApiError(409, `the clock is at ${clock.current_period}; step that period first`)
      const month = inbox.months[period]
      if (scenario !== 'inbox' || !month) throw new ApiError(409, `The mock covers ${MONTHS.join(' and ')}; run the API for the full year.`)
      const answeredIds = new Set(answered.map(e => e.id))
      periods.set(period, structuredClone(month.period))
      cards = structuredClone(month.escalations).filter(e => !answeredIds.has(e.id))
      for (const e of answered) { const p = periods.get(e.period); if (p) settle(p, e.finding_id) }
      const live = new Map(controls.map(c => [c.id, c.live_precedent_ids]))
      controls = structuredClone(month.controls).map(c => ({ ...c, live_precedent_ids: live.get(c.id) ?? c.live_precedent_ids }))
      for (const [id, x] of Object.entries(month.explain)) explain.set(id, structuredClone(x))
      metrics.set(period, month.metrics)
      clock = { ...clock, current_period: nextPeriod(period), sim_date: month.period.postings.at(-1)?.valid_time ?? clock.sim_date, live_month: clock.live_month + 1 }
      return structuredClone(month.step)
    },
    signPeriod: async (period, customerId, signedBy = 'close_reviewer', options) => {
      options?.signal?.throwIfAborted()
      const p = periods.get(validatePeriod(period))
      const c = p?.customers.find(x => x.customer_id === customerId)
      if (!p || !c) throw new ApiError(404, `no period ${period} for ${customerId}`)
      if (!['controller', 'close_reviewer'].includes(signedBy)) throw new ApiError(403, `${signedBy} cannot sign the close`)
      if (c.state !== 'REVIEWED') throw new ApiError(409, `${period} ${customerId} is ${c.state}, not ready to sign`)
      Object.assign(c, { state: 'SIGNED', signed_by: signedBy, signed_at: `${clock.current_period}-01T07:00:00` })
      if (p.customers.every(x => x.state === 'SIGNED')) p.customers.forEach(x => { x.state = 'CLOSED' })
      p.state = p.customers.map(x => x.state).reduce((a, b) => (ORDER.indexOf(a) <= ORDER.indexOf(b) ? a : b))
    },
    getPackage: (period, options) => {
      if (scenario === 'moment' && validatePeriod(period) === '2026-02')
        return finish(['month-2', '2026-02'].includes(options?.asOf ?? '') ? moment.feb_package_then : moment.feb_package_now, options)
      return Promise.reject(new ApiError(404, 'The mock has the sign-off package for 2026-02 in the moment scenario only.'))
    },
    exportUrl: (period, file) => `#mock-export/${period}/${file}`,
    getControls: options => finish(controls, options),
    getPrecedent: (kind, id, options) => finish({ id, kind, note: 'The mock has no precedent rows; the API returns the full record.' } as Evidence, options),
    getEscalations: options => finish(options?.open === false ? [...answered, ...cards] : cards, options),
    answerEscalation: async (id, answer, options) => {
      options?.signal?.throwIfAborted()
      const card = cards.find(e => e.id === id)
      if (!card) throw new ApiError(422, `${id} was already answered or does not exist`)
      const option = card.options.find(o => o.id === answer || o.label === answer)
      if (!option) throw new ApiError(422, `'${answer}' is not an option on ${id}`)
      if (options?.answeredBy?.startsWith('sales.')) throw new ApiError(403, `${options.answeredBy} cannot answer a card addressed to the ${card.to_role}`)
      const result: AnswerResult = { escalation_id: id, finding_id: card.finding_id, decision: option.decision, journals: [], precedent_id: null, settled: [], escalated_to: null }
      if (option.decision === 'escalate') {
        card.to_role = 'controller'
        card.options = card.options.filter(o => o.decision !== 'escalate')
        result.escalated_to = id
        return result
      }
      const done = (e: Escalation, by: string | null) => {
        cards = cards.filter(x => x.id !== e.id)
        answered.push({ ...e, answer: by ? option.id : `precedent:${result.precedent_id}`, answered_by: by, answered_at: `${clock.current_period}-01T07:00:00` })
        const p = periods.get(e.period); if (p) settle(p, e.finding_id)
      }
      if (option.decision !== 'hold') {
        result.precedent_id = `PR-MOCK-${String(++precedents).padStart(4, '0')}`
        controls.find(c => c.id === card.control_id)?.live_precedent_ids.push(result.precedent_id)
        result.settled = cards.filter(e => e.id !== id && e.control_id === card.control_id && e.customer_id === card.customer_id).map(e => e.id)
      }
      done(card, options?.answeredBy ?? card.to_role)
      for (const sid of result.settled) done(cards.find(e => e.id === sid)!, null)
      return result
    },
    explainEntry: (id, options) => {
      const found = explain.get(id)
      if (found) return finish(found, options)
      const line = [...periods.values()].flatMap(p => p.postings).find(x => x.id === id)
      if (!line) return Promise.reject(new ApiError(404, `no entry ${id}`))
      const journal = [...periods.values()].flatMap(p => p.postings).filter(x => x.journal_id === line.journal_id)
      const head = `${line.journal_id} · ${line.valid_time.slice(0, 7)} ${line.entry_type} · ${line.customer_id}`
      return finish({ line, journal, reverses_or_restates: null, reversed_by: [], restated_by: [], deduction: null, finding: null, approved_by: null,
        chain: { entry_id: id, head, steps: [], memo: line.memo }, text: `${head}\n  (the mock captured no chain for this line)` }, options)
    },
    ask: (question, options) => {
      const captured = scenario === 'moment' ? moment.asks.find(a => a.question === question) : undefined
      if (captured) return finish(captured, options)
      const id = /\bJE-\d+(-\d+)?\b/.exec(question)?.[0]
      const hit = id && [...explain.values()].find(x => x.line.id === id || x.line.journal_id === id)
      if (hit) return finish({ question, answer: hit.text, chains: [hit.chain], knowledge: null, drafted_by: 'agent' } satisfies AskResponse, options)
      return finish({ question, chains: [], knowledge: null, drafted_by: 'agent',
        answer: "I couldn't tie that to a record. Name an entry (JE-…), a deduction (DD-…), a finding (FN-…) or a month, and I'll trace it." } satisfies AskResponse, options)
    },
    getBacktest: options => finish(backtest.backtest, options),
    getMetricsSeries: options => finish(backtest.series, options),
    getIntegrations: options => finish(mail.integrations.map(i => i.id === 'gmail' ? { ...i, account: 'captured inbox', detail: 'Captured from the API: replaying a synced inbox.' } : i), options),
    getInbox: options => finish(mail.inbox, options),
    syncInbox: () => Promise.reject(new ApiError(409, 'The mock replays a captured inbox. Run the API with JADE_MAIL_BACKEND to read live mail.')),
    getMetrics: (period, options) => {
      const m = metrics.get(period) ?? metrics.get(period.replace(/^2026-0?/, 'month-'))
      return m ? finish(m, options) : Promise.reject(new ApiError(404, `The mock has metrics for ${[...metrics.keys()].join(', ') || 'no month yet'}.`))
    },
    // Scenarios write source rows the engine then processes; there is no engine here to meet them.
    getScenarioExamples: options => finish(EXAMPLES(clock.current_period), options),
    getInjections: options => finish([], options),
    injectScenario: async (_kind, _payload, options) => {
      options?.signal?.throwIfAborted()
      throw new ApiError(409, 'Live scenarios need the engine: run `make api` and set VITE_API_MODE=http.')
    },
  }
}
