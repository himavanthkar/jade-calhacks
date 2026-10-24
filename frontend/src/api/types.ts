/** DB-backed fields follow db/schema.sql and tpa modules; HTTP envelopes remain spec proposals. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Evidence = Record<string, Json>
/** Preserve decimal strings from Python; use numbers only for display, never ledger math. */
export type DecimalValue = number | string
export type CustomerId = 'WMT' | 'COST' | 'KR'
export type PeriodState = 'OPEN' | 'ACCRUED' | 'CONTROLLED' | 'ESCALATED' | 'REVIEWED' | 'SIGNED' | 'CLOSED' | 'RESTATED'
export interface Posting {
  id: string; journal_id: string; period: string; customer_id: CustomerId
  entry_type: 'opening' | 'revenue' | 'accrual' | 'reversal' | 'clearing' | 'dispute' | 'restatement' | 'adjustment'
  program_id: string | null; account: string; debit: DecimalValue; credit: DecimalValue
  memo: string | null; valid_time: string; decision_time: string
  reversal_of: string | null; restates: string | null; source_finding_id: string | null
  deduction_id: string | null; approved_by: string | null
}
export interface Finding { id: string; control_id: string; customer_id: CustomerId; amount: DecimalValue | null; state: 'open' | 'auto_resolved' | 'escalated' | 'resolved'; evidence: Evidence }
export interface GateResult { name: string; description: string; passed: boolean; violations: Evidence[] }
export interface Flux { id: string; account: string; current_balance: DecimalValue; prior_balance: DecimalValue; pct_change: DecimalValue | null; narrative: string; driver_entry_ids: string[]; approved_by: string | null }
/** Spec envelope only: backend stores state and gates per (period, customer_id). Do not infer an aggregate state. */
export interface Period { state: PeriodState; postings: Posting[]; findings: Finding[]; gates: Record<string, GateResult>; flux: Flux[] }
export interface CustomerPeriod { period: string; customer_id: CustomerId; state: PeriodState; signed_by: string | null; signed_at: string | null; gate_results: Record<string, GateResult> }
export interface Control { id: string; name: string; threshold: DecimalValue | null; threshold_unit: 'usd' | 'pct' | 'periods' | null; owner: string; precedent_ids: string[]; fired_count: number; learned: boolean }
/** options is JSONB in the database; string-only options are not guaranteed. */
export interface Escalation { id: string; to_role: string; question: string; options: Json[]; evidence: Evidence }
/** Exact top-level shape of tpa.asof.entry_history. No generated narrative exists yet. */
export interface Explanation { line: Posting; journal: Posting[]; reverses_or_restates: Posting | null; reversed_by: Posting[]; restated_by: Posting[]; deduction: Evidence | null; finding: Finding | null; approved_by: Evidence | null }
/** Ratios are 0–1. null means no denominator, not 0% (tpa.evaluate.metrics). */
export interface Metrics { precision: number | null; recall: number | null; escalation_rate: number | null; autonomy: number | null; as_of?: string; live_month?: number; counts?: Record<string, number>; missed?: Evidence[]; false_positives?: Evidence[] }
export interface RequestOptions { signal?: AbortSignal }
export interface TradePromotionApi {
  getPeriod(period: string, options?: RequestOptions): Promise<Period>
  stepPeriod(period: string, options?: RequestOptions): Promise<void>
  getControls(options?: RequestOptions): Promise<Control[]>
  getEscalations(options?: RequestOptions): Promise<Escalation[]>
  answerEscalation(id: string, answer: string, options?: RequestOptions): Promise<void>
  explainEntry(id: string, options?: RequestOptions): Promise<Explanation>
  getMetrics(period: string, options?: RequestOptions): Promise<Metrics>
}
