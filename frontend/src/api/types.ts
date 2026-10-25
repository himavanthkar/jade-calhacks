/** Shapes of the real API (tpa/api.py). Fixtures in ./fixtures are captured from it, not written by hand. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Evidence = Record<string, Json>
/** Amounts arrive as decimal strings; use numbers only for display, never ledger math. */
export type DecimalValue = string
export type CustomerId = 'WMT' | 'COST' | 'KR'
export type PeriodState = 'OPEN' | 'ACCRUED' | 'CONTROLLED' | 'ESCALATED' | 'REVIEWED' | 'SIGNED' | 'CLOSED' | 'RESTATED'
export type Role = 'controller' | 'close_reviewer' | 'customer_team_analyst' | 'deduction_analyst' | 'trade_promotion_accountant' | 'sales_lead' | 'agent'
export type EscalationType = 'authority' | 'source_conflict' | 'low_confidence' | 'sod'

export interface Clock { current_period: string; sim_date: string; live_month: number; last_period: string; humans: 'inbox' | 'players' | 'autopilot' }

export interface Posting {
  id: string; journal_id: string; period: string; customer_id: CustomerId
  entry_type: 'opening' | 'revenue' | 'accrual' | 'reversal' | 'clearing' | 'dispute' | 'restatement' | 'adjustment'
  program_id: string | null; account: string; debit: DecimalValue; credit: DecimalValue
  memo: string | null; valid_time: string; decision_time: string
  reversal_of: string | null; restates: string | null; source_finding_id: string | null
  deduction_id: string | null; approved_by: string | null
}
export interface Finding {
  id: string; period: string; customer_id: CustomerId; control_id: string
  severity: 'low' | 'medium' | 'high' | 'critical'; amount: DecimalValue | null; exposure: DecimalValue | null
  confidence: DecimalValue | null; state: 'open' | 'auto_resolved' | 'escalated' | 'resolved'
  /** 'sod' marks a blocked self-approval: the segregation-of-duties throw. */
  escalation_type: EscalationType | null; conflict_type: string | null
  /** Always has `summary` (the card's lede) and `control`; ids of every row involved; `resolution` once decided. */
  evidence: Evidence; created_at: string
}
export interface GateResult { name: string; description: string; passed: boolean; violations: Evidence[] }
export interface Flux {
  id: string; period: string; account: string; current_balance: DecimalValue; prior_balance: DecimalValue
  pct_change: DecimalValue | null; narrative: string; driver_entry_ids: string[]; decision_time: string
  approved_by: string | null; approved_at: string | null
}
/** State and gates live per (period, customer). */
export interface CustomerPeriod { period: string; customer_id: CustomerId; state: PeriodState; signed_by: string | null; signed_at: string | null; gate_results: Record<string, GateResult> | null }
/** The close's check of the total trade liability against General Mills' reported ratio (latest 10-K at the time). */
export interface AnalyticalReview {
  id: string; period: string; measure: string; liability: DecimalValue; net_sales_annualized: DecimalValue; ratio: DecimalValue
  expectation: DecimalValue | null; low: DecimalValue | null; high: DecimalValue | null; within_range: boolean | null
  source: Evidence; drivers: Evidence[]; narrative: string; decision_time: string
}
/** `state` is the least-advanced customer's; `gates` merges customers, each violation tagged with customer_id. */
export interface Period { period: string; state: PeriodState; customers: CustomerPeriod[]; postings: Posting[]; findings: Finding[]; gates: Record<string, GateResult>; flux: Flux[]; analytical_review?: AnalyticalReview | null }
export interface StepSummary { period: string; states: Record<CustomerId, PeriodState | 'BLOCKED'>; findings: [string, Finding['state'], number][]; log: string[] }

export interface Control {
  id: string; name: string; condition: string; threshold: DecimalValue | null; threshold_unit: 'usd' | 'pct' | 'periods' | null
  owner: Role; precedent_ids: string[]; live_precedent_ids: string[]; fired_count: number
  /** Added after onboarding: show these as learned. */
  learned: boolean; status: 'active' | 'retired' | 'tuned'; mined_at: string
}
/** `recommended` marks the agent's recommendation; choosing another option needs a reason. */
export interface EscalationOption { id: string; label: string; decision: string; recommended?: boolean }
export interface Escalation {
  id: string; finding_id: string; to_role: Role; question: string; options: EscalationOption[]
  answer: string | null; answered_by: string | null; answered_at: string | null; became_precedent_id: string | null; created_at: string
  /** The option id the agent recommends, and why (this year's precedent, last year's handling, or policy). */
  recommended?: string | null; recommendation_basis?: string | null
  period: string; customer_id: CustomerId; control_id: string; escalation_type: EscalationType | null; exposure: DecimalValue | null
  evidence: Evidence
}
export interface AnswerOptions extends RequestOptions {
  /** Default: the person the card is addressed to. */
  answeredBy?: string
  /** Default: the option's label. Becomes the precedent's reasoning. */
  reasoning?: string
}
/** `settled`: other open cards the new precedent answered at once. */
/** `overrode`: the recommendation the person turned down, if they did. */
export interface AnswerResult { escalation_id: string; finding_id: string; decision: string; journals: string[]; precedent_id: string | null; settled: string[]; escalated_to: string | null; overrode?: string | null }

export interface ChainStep { label: 'rule' | 'terms' | 'inputs' | 'knew-at' | 'approved' | 'signed' | 'restated' | 'reversed' | 'precedent' | string; text: string; ids: string[] }
export interface Chain { entry_id: string; head: string; steps: ChainStep[]; memo: string | null }
/** tpa.asof.entry_history plus the interrogation chain and its plain-text form. */
export interface Explanation {
  line: Posting; journal: Posting[]; reverses_or_restates: Posting | null; reversed_by: Posting[]; restated_by: Posting[]
  deduction: Evidence | null; finding: Finding | null; approved_by: Evidence | null; chain: Chain; text: string
}
/** `drafted_by: 'model'` only when every number in the answer is in the evidence. */
export interface AskResponse { question: string; answer: string; chains: Chain[]; knowledge: Evidence | null; drafted_by: 'agent' | 'model' }

export interface Reconciliation { program_id: string; origin: string; opening: DecimalValue; accruals: DecimalValue; estimate_adjustments: DecimalValue; settled: DecimalValue; ending: DecimalValue; outstanding: DecimalValue }
export interface CustomerPackage {
  customer_id: CustomerId; state: PeriodState | null; signed_by: string | null; signed_at: string | null
  postings: Posting[]; balances: Record<string, DecimalValue>; totals: { debit: DecimalValue; credit: DecimalValue }
  findings: (Finding & Partial<Pick<Escalation, 'to_role' | 'question' | 'answer' | 'answered_by' | 'answered_at' | 'became_precedent_id'>> & { escalation_id: string | null })[]
  gates: Record<string, GateResult>; reconciliation: Reconciliation[]
}
/** `needs_explanation`: the analytical review is outside its range; the reviewer explains before signing. */
export interface SignoffPackage { period: string; as_of: string; flux: Flux[]; customers: CustomerPackage[]; analytical_review?: AnalyticalReview | null; needs_explanation?: boolean }
export type ExportFile = 'ledger.csv' | 'trial_balance.csv' | 'reconciliation.csv' | 'gates.csv'

/** Ratios are 0–1. null means no denominator, not 0% (tpa.evaluate.metrics). */
/** Whether answers stuck: repeats of situations a person already answered, and how they were handled. */
export interface JudgmentRecord { repeat_findings: number; settled_by_precedent: number; asked_again: number; asked_again_detail: Evidence[]; precedent_hit_rate: number | null; first_time_questions: number }
export interface Metrics { precision: number | null; recall: number | null; escalation_rate: number | null; autonomy: number | null; as_of?: string; live_month?: number; counts?: Record<string, number>; missed?: Evidence[]; false_positives?: Evidence[]; judgment?: JudgmentRecord }

/** The judge's own scenario (tpa/scenario.py): rows land in the month the clock is on; the engine meets them on the next step. */
export type ScenarioKind = 'deduction' | 'duplicate' | 'backup' | 'return' | 'amendment' | 'approval_attempt' | 'handoff'
export interface ScenarioExample { title: string; kind: ScenarioKind; payload: Evidence }
export interface Injection { id: string; kind: ScenarioKind; payload: Evidence; created_ids: string[]; period: string; sim_date: string; injected_by: string | null }
/** `step` and `findings` only when the month was run with the injection: findings are the ones whose evidence names a created id. */
export interface InjectResult { id: string; kind: ScenarioKind; period: string; lands_on: string; created_ids: string[]; step?: StepSummary; findings?: Finding[] }
export interface InjectOptions extends RequestOptions { step?: boolean; injectedBy?: string }
/** The people (tpa/seed/fiction.py ACTORS); the API checks who may answer what. */
export interface Actor { id: string; name: string; role: Role; customer_id: CustomerId | null }

export interface RequestOptions { signal?: AbortSignal }
/** `asOf`: 'month-N', 'YYYY-MM' or an ISO date-time — the books as they stood then. */
export interface AsOfOptions extends RequestOptions { asOf?: string }

export interface TradePromotionApi {
  getClock(options?: RequestOptions): Promise<Clock>
  getPeriod(period: string, options?: AsOfOptions): Promise<Period>
  /** Only the period the clock points at can be stepped. */
  stepPeriod(period: string, options?: RequestOptions): Promise<StepSummary | undefined>
  /** A named close reviewer or controller signs a clean (REVIEWED) customer-period. */
  signPeriod(period: string, customerId: CustomerId, signedBy?: string, options?: RequestOptions): Promise<void>
  getPackage(period: string, options?: AsOfOptions): Promise<SignoffPackage>
  exportUrl(period: string, file: ExportFile, asOf?: string): string
  getControls(options?: RequestOptions): Promise<Control[]>
  /** A precedent cell's click: kind 'history' for prior-year decisions, 'live' for answered cards. */
  getPrecedent(kind: 'history' | 'live', id: string, options?: RequestOptions): Promise<Evidence>
  getEscalations(options?: RequestOptions & { open?: boolean }): Promise<Escalation[]>
  /** `answer` is an option id or its label. */
  answerEscalation(id: string, answer: string, options?: AnswerOptions): Promise<AnswerResult | undefined>
  explainEntry(id: string, options?: RequestOptions): Promise<Explanation>
  ask(question: string, options?: RequestOptions): Promise<AskResponse>
  getMetrics(period: string, options?: RequestOptions): Promise<Metrics>
  getScenarioExamples(options?: RequestOptions): Promise<ScenarioExample[]>
  getInjections(options?: RequestOptions): Promise<Injection[]>
  /** With `step`, also runs the month so the scenario plays out at once. */
  injectScenario(kind: ScenarioKind, payload: Evidence, options?: InjectOptions): Promise<InjectResult>
}
