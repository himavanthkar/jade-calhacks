import type { Correspondence, Escalation } from './api'

/** The judgment gate (tpa/judgment.py `judge`), as the path one card took through it. Read from what the
 *  card recorded (lane, escalation type, the precedent prefix, quoted mail, the answer); nothing here
 *  decides or recomputes. Order matches the code: mechanical, mail, precedent, lane. */
export interface Branch { label: string; leadsTo: string }
export interface Step { id: string; question: string; taken: Branch; other: Branch[] }
export interface Path { steps: Step[]; leaf: { title: string; detail: string }; outcome: { done: boolean; text: string } }

const ROLE: Record<string, string> = {
  controller: 'the controller', customer_team_analyst: 'the customer team analyst', deduction_analyst: 'the deduction analyst',
  trade_promotion_accountant: 'the trade promotion accountant', close_reviewer: 'the close reviewer', sales_lead: 'the sales lead',
}
export const role = (r: string | null | undefined) => (r && ROLE[r]) || (r ?? '').replaceAll('_', ' ')

export function decisionPath(card: Escalation): Path {
  const mail = (Array.isArray(card.evidence.correspondence) ? card.evidence.correspondence : []) as unknown as Correspondence[]
  const unsigned = mail.find(m => m.kind === 'unsigned_terms' && !m.signed)
  const mailRouted = Boolean(unsigned) && card.to_role === 'controller' && card.recommended === 'hold'
  const exceeded = /^Precedent \S+ \(/.test(card.question)
  const restatement = Boolean(card.evidence.amendment_id)
  const control = (card.evidence.control ?? {}) as { name?: string; threshold?: string; threshold_unit?: string }

  const steps: Step[] = [{
    id: 'mechanical', question: 'Is it mechanical? (a duplicate, missing proof, a late return)',
    taken: { label: 'No', leadsTo: 'needs judgment' },
    other: [{ label: 'Yes', leadsTo: 'the agent disputes or re-estimates; no card' }],
  }, {
    id: 'mail', question: 'Does mail on file claim terms nobody signed?',
    taken: mailRouted ? { label: 'Yes', leadsTo: `${unsigned!.id} from ${unsigned!.from}` } : { label: 'No', leadsTo: 'the agreement is the only source' },
    other: [mailRouted ? { label: 'No', leadsTo: 'precedent, then the usual lane' } : { label: 'Yes', leadsTo: 'controller, hold recommended' }],
  }]
  if (!mailRouted) {
    steps.push({
      id: 'precedent', question: 'Has a person answered this situation before?',
      taken: exceeded ? { label: 'Yes, for less', leadsTo: 'this one is larger than anything approved' } : { label: 'No', leadsTo: 'first time: ask' },
      other: [{ label: exceeded ? 'Yes, covering this amount' : 'Yes', leadsTo: 'settled silently by that precedent; no card' }],
    })
    const lane = restatement ? { label: 'A closed period must change', leadsTo: 'the controller (restatement)' }
      : card.escalation_type === 'source_conflict' ? { label: 'Two sources disagree', leadsTo: role(card.to_role) }
      : card.escalation_type === 'low_confidence' ? { label: "The agreement can't settle it", leadsTo: role(card.to_role) }
      : { label: `Over the mined threshold${control.threshold && Number(control.threshold) ? ` (${control.threshold_unit === 'usd' ? '$' + Number(control.threshold).toLocaleString('en-US') : control.threshold})` : ''}`, leadsTo: role(card.to_role) }
    const lanes = [
      { label: 'A closed period must change', leadsTo: 'the controller' },
      { label: 'Two sources disagree', leadsTo: 'the customer team analyst' },
      { label: "The agreement can't settle it", leadsTo: 'the controller' },
      { label: 'Over the mined threshold', leadsTo: "the control's owner" },
    ].filter(l => !lane.label.startsWith(l.label))
    steps.push({ id: 'lane', question: 'Who must decide?', taken: lane, other: lanes })
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
  return { steps, leaf, outcome }
}
