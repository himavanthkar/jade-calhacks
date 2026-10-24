import { ApiError, validatePeriod } from './client'
import type { Control, Escalation, Evidence, Period, RequestOptions, TradePromotionApi } from './types'

const evidence: Evidence = { entry_ids: ['JE-DEMO-001'], program_ids: ['TP-DEMO-001'], shipment_ids: ['SH-DEMO-001'], deduction_ids: ['DD-DEMO-001'], source_clause_ids: ['clause-4.2'] }
const initialControls: Control[] = [
  { id: 'CTL-DED-GT-ACCRUAL', name: 'Deduction exceeds accrued liability', threshold: 2500, threshold_unit: 'usd', owner: 'trade_promotion_accountant', precedent_ids: ['PRE-DEMO-001'], fired_count: 1, learned: false },
  { id: 'CTL-SCAN-NO-BACKUP', name: 'Scan-back claim without backup', threshold: 0, threshold_unit: 'usd', owner: 'deduction_analyst', precedent_ids: [], fired_count: 1, learned: true },
]
const initialEscalations: Escalation[] = [{ id: 'ESC-DEMO-001', to_role: 'customer_team_analyst', question: 'The program and the claimed rate disagree. Which is the source of truth?', options: ['Program as signed', "Customer’s claimed rate", 'Hold until backup arrives', 'Escalate to controller'], evidence }]

/** Synthetic UI fixtures only. No accounting engine, authority enforcement, or evaluation. */
export function createMockApi(): TradePromotionApi {
  const controls = structuredClone(initialControls)
  const escalations = structuredClone(initialEscalations)
  const stepped = new Set<string>()
  function finish<T>(value: T, options?: RequestOptions): Promise<T> {
    options?.signal?.throwIfAborted()
    return Promise.resolve(structuredClone(value))
  }
  function periodData(period: string): Period {
    validatePeriod(period)
    const processed = stepped.has(period)
    const end = new Date(Date.UTC(Number(period.slice(0, 4)), Number(period.slice(5)), 0)).toISOString().slice(0, 10)
    const metadata = { customer_id: 'WMT' as const, entry_type: 'accrual' as const, program_id: 'TP-DEMO-001', reversal_of: null, source_finding_id: null, deduction_id: null, approved_by: null }
    return {
      state: processed ? (escalations.length ? 'ESCALATED' : 'CONTROLLED') : 'OPEN',
      postings: processed ? [
        { ...metadata, id: `JE-${period}-D`, journal_id: `J-${period}`, period, account: '4100 Trade promotion expense', debit: 10000, credit: 0, memo: 'Synthetic accrual fixture', valid_time: end, decision_time: `${end}T12:00:00`, restates: null },
        { ...metadata, id: `JE-${period}-C`, journal_id: `J-${period}`, period, account: '2300 Accrued trade promotion liability', debit: 0, credit: 10000, memo: 'Synthetic accrual fixture', valid_time: end, decision_time: `${end}T12:00:00`, restates: null },
      ] : [],
      findings: processed ? [{ id: 'F-DEMO-001', control_id: 'CTL-DED-GT-ACCRUAL', customer_id: 'WMT', amount: 3000, state: escalations.length ? 'escalated' : 'resolved', evidence }] : [],
      gates: processed ? { journals_balance: { name: 'journals_balance', description: 'Fixture debits equal credits.', passed: true, violations: [] } } : {},
      flux: [],
    }
  }
  return {
    getPeriod: (period, options) => finish(periodData(period), options),
    stepPeriod: async (period, options) => { options?.signal?.throwIfAborted(); validatePeriod(period); stepped.add(period) },
    getControls: options => finish(controls, options),
    getEscalations: options => finish(escalations, options),
    answerEscalation: async (id, answer, options) => {
      options?.signal?.throwIfAborted()
      const index = escalations.findIndex(item => item.id === id)
      if (index < 0) throw new ApiError(404, 'Escalation not found or already answered.')
      if (!escalations[index].options.includes(answer)) throw new ApiError(422, 'Select an available answer.')
      escalations.splice(index, 1)
      controls[0].precedent_ids.push('PRE-DEMO-002')
    },
    explainEntry: (id, options) => {
      const match = /^JE-(\d{4}-\d{2})-[DC]$/.exec(id)
      if (!match || !stepped.has(match[1])) throw new ApiError(404, 'Entry not found.')
      const period = periodData(match[1])
      const line = period.postings.find(entry => entry.id === id)!
      return finish({ line, journal: period.postings, reverses_or_restates: null, reversed_by: [], restated_by: [], deduction: null, finding: null, approved_by: null }, options)
    },
    getMetrics: (period, options) => { validatePeriod(period); return finish({ precision: 0.9, recall: 0.85, escalation_rate: 0.4, autonomy: 0.5 }, options) },
  }
}
