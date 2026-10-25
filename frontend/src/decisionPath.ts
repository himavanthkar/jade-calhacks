import type { Correspondence, Escalation } from './api'

/** The judgment gate (tpa/judgment.py `judge`) as a decision tree, with the path one card took through it.
 *  Read from what the card recorded (lane, escalation type, the precedent prefix, quoted mail, the answer);
 *  nothing here decides or recomputes. Order matches the code: mechanical, mail, precedent, lane.
 *
 *  Each node's first branch without a `leaf` continues to the next node; every other branch ends in a leaf. */
export interface Branch { label: string; leaf?: string; taken: boolean }
export interface Node { id: string; label: string; branches: Branch[] }
export interface Path { nodes: Node[]; leaf: { title: string; detail: string }; outcome: { done: boolean; text: string } }

const ROLE: Record<string, string> = {
  controller: 'the controller', customer_team_analyst: 'the customer team analyst', deduction_analyst: 'the deduction analyst',
  trade_promotion_accountant: 'the trade promotion accountant', close_reviewer: 'the close reviewer', sales_lead: 'the sales lead',
}
export const role = (r: string | null | undefined) => (r && ROLE[r]) || (r ?? '').replaceAll('_', ' ')
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export function decisionPath(card: Escalation): Path {
  const mail = (Array.isArray(card.evidence.correspondence) ? card.evidence.correspondence : []) as unknown as Correspondence[]
  const unsigned = mail.find(m => m.kind === 'unsigned_terms' && !m.signed)
  const mailRouted = Boolean(unsigned) && card.to_role === 'controller' && card.recommended === 'hold'
  const exceeded = /^Precedent \S+ \(/.test(card.question)
  const restatement = Boolean(card.evidence.amendment_id)
  const who = cap(role(card.to_role))

  const nodes: Node[] = [
    { id: 'mechanical', label: 'Mechanical?', branches: [
      { label: 'No', taken: true },
      { label: 'Yes', leaf: 'Agent decides · no card', taken: false }] },
    { id: 'mail', label: 'Unsigned terms in mail?', branches: [
      { label: 'No', taken: !mailRouted },
      { label: 'Yes', leaf: mailRouted ? `${who} · hold (${unsigned!.id})` : 'Controller · hold', taken: mailRouted }] },
  ]
  if (!mailRouted) {
    nodes.push({ id: 'precedent', label: 'Answered before?', branches: [
      { label: exceeded ? 'Yes, for less' : 'No', taken: true },
      { label: 'Yes, covers it', leaf: 'Settled by precedent · no card', taken: false }] })
    const lane = restatement ? 'restatement' : card.escalation_type === 'source_conflict' ? 'conflict'
      : card.escalation_type === 'low_confidence' ? 'unverifiable' : 'threshold'
    const leaves: [string, string, string][] = [
      ['restatement', 'Closed period changes', 'Controller · restatement'],
      ['conflict', 'Sources disagree', 'Customer team · which is right'],
      ['unverifiable', "Can't verify", 'Controller · low confidence'],
      ['threshold', 'Over threshold', "Control's owner · authority"],
    ]
    nodes.push({ id: 'lane', label: 'Who decides?', branches: leaves.map(([id, label, leaf]) =>
      ({ label, leaf: id === lane ? `${who}` : leaf, taken: id === lane })) })
  }
  const pick = card.options.find(o => o.id === card.recommended)
  const leaf = {
    title: `Card to ${role(card.to_role)}`,
    detail: `Recommends: ${pick?.label ?? card.recommended ?? '—'}.${card.recommendation_basis ? ` ${card.recommendation_basis}` : ''}`,
  }
  const answered = card.answer !== null
  const chosen = card.options.find(o => o.id === card.answer || o.label === card.answer)
  const outcome = !answered ? { done: false, text: `Waiting for ${role(card.to_role)}.` }
    : card.answer!.startsWith('superseded:') ? { done: true, text: `Settled by new evidence (${card.answer!.slice(11)}); no answer needed.` }
    : { done: true, text: `${card.answered_by ?? 'A person'} chose “${chosen?.label ?? card.answer}”${card.became_precedent_id ? `, which became ${card.became_precedent_id}: the next case like it settles silently` : ''}.` }
  return { nodes, leaf, outcome }
}

/** One plain line for a person: what is being asked, from the card's own evidence fields. Falls back to the
 *  first sentence of the engine's summary. */
const monthName = (p: unknown) => typeof p === 'string' && /^\d{4}-\d{2}$/.test(p)
  ? new Date(`${p}-01T12:00:00`).toLocaleDateString('en-US', { month: 'long' }) : String(p ?? '')
const perCase = (v: unknown) => `$${Number(v).toFixed(2)}`
export function headline(card: Escalation): string {
  const ev = card.evidence as Record<string, unknown>
  const program = ev.program_id ? ` (${ev.program_id})` : ''
  if (ev.amendment_id) {
    const n = Array.isArray(ev.periods) ? ev.periods.length : 0
    return `Restate ${n || ''} closed month${n === 1 ? '' : 's'}: amendment ${ev.amendment_id} reached us late${program}`.replace('  ', ' ')
  }
  if (card.control_id === 'CTL-RATE-CONFLICT' && ev.claimed_rate && ev.program_rate)
    return `Claims ${monthName(ev.claimed_period ?? ev.origin)} at ${perCase(ev.claimed_rate)} a case; the agreement says ${perCase(ev.program_rate)}${program}`
  if (card.control_id === 'CTL-STALE-ACCRUAL') return `${monthName(ev.origin)} accrual still open with no claim against it${program}`
  if (card.control_id === 'CTL-OUTSIDE-WINDOW') return `Claim falls outside the program's dates${program}`
  if (card.control_id === 'CTL-SCAN-NO-BACKUP') return `Scan-back claim with no scan data${program}`
  if (card.control_id === 'CTL-PERIOD-STRADDLE') return `Claim spans a quarter end${program}`
  if (card.control_id === 'CTL-DED-GT-ACCRUAL') return `Claim is more than was accrued${program}`
  const s = String(ev.summary ?? card.question)
  return (s.match(/^.*?[.?!](\s|$)/)?.[0] ?? s).trim()
}
