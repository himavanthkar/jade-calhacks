import { describe, expect, test } from 'bun:test'
import type { Escalation } from '../src/api'
import { decisionPath } from '../src/decisionPath'

const card = (over: Partial<Escalation>): Escalation => ({
  id: 'ESC-1', finding_id: 'FN-1', to_role: 'customer_team_analyst', question: 'DD-1 claims 2026-09 at $4.50/case.',
  options: [{ id: 'program', label: 'Program as signed', decision: 'dispute_difference' }, { id: 'hold', label: 'Hold until more evidence arrives', decision: 'hold' }],
  answer: null, answered_by: null, answered_at: null, became_precedent_id: null, created_at: '2026-10-05T12:00:00',
  recommended: 'program', recommendation_basis: 'Last year 2 cases were resolved this way.', period: '2026-10', customer_id: 'WMT',
  control_id: 'CTL-RATE-CONFLICT', escalation_type: 'source_conflict', exposure: '4000.20', evidence: {}, ...over,
})

const taken = (p: ReturnType<typeof decisionPath>) => p.nodes.map(n => n.branches.find(b => b.taken)!)

describe('the path a card took through the judgment gate', () => {
  test('a first-time rate conflict goes to the customer team as a source conflict', () => {
    const p = decisionPath(card({}))
    expect(p.nodes.map(n => n.id)).toEqual(['mechanical', 'mail', 'precedent', 'lane'])
    expect(taken(p).map(b => b.label)).toEqual(['No', 'No', 'No', 'Sources disagree'])
    expect(taken(p).at(-1)!.leaf).toBe('The customer team analyst')
    expect(p.nodes.every(n => n.branches.filter(b => b.taken).length === 1)).toBe(true)
    expect(p.outcome.done).toBe(false)
  })
  test('an unsigned rate in mail sends it to the controller with a hold, skipping precedent', () => {
    const mail = [{ id: 'EM-1', kind: 'unsigned_terms', from: 'Walmart sales lead', signed: false, sender_actor: 'sales.walmart', subject: '', received: '', asserted_rate: '4.50', program_id: 'TP-0214', quotes: [] }]
    const p = decisionPath(card({ to_role: 'controller', recommended: 'hold', evidence: { correspondence: mail } }))
    expect(p.nodes.map(n => n.id)).toEqual(['mechanical', 'mail'])
    expect(taken(p)[1]).toEqual({ label: 'Yes', leaf: 'The controller · hold (EM-1)', taken: true })
    expect(p.leaf.detail).toContain('Hold until more evidence arrives')
  })
  test('a precedent that covered less asks again, and the answer that becomes precedent is named', () => {
    const p = decisionPath(card({ question: 'Precedent PR-0003 (dispute_difference) covers up to $3,000.00; this one is $4,000.20. …',
      answer: 'program', answered_by: 'team.walmart', became_precedent_id: 'PR-0009' }))
    expect(taken(p)[2].label).toBe('Yes, for less')
    expect(p.outcome.text).toContain('PR-0009')
  })
  test("a restatement is the controller's, whatever the lane says", () => {
    const p = decisionPath(card({ control_id: 'CTL-DED-GT-ACCRUAL', escalation_type: 'authority', to_role: 'controller', evidence: { amendment_id: 'AM-02' } }))
    expect(taken(p)[3].label).toBe('Closed period changes')
  })
})
