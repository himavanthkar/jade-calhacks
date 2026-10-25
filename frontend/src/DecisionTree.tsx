import { useState, type KeyboardEvent } from 'react'
import type { Correspondence, Escalation } from './api'
import { decisionPath, role, type Branch, type Path } from './decisionPath'
import './DecisionTree.css'

/** Why this card reached this person, drawn as a decision tree: square decision nodes climbing left to
 *  right, each exit ending in a round leaf. The path this case took is drawn heavy and ends in a filled
 *  leaf; the branches it didn't take stay thin, with where they lead. */
type Pt = { x: number; y: number }
const STEP_X = 140, STEP_Y = 58, EXIT = { x: 95, y: 56 }, FAN_X = 190, FAN_GAP = 40
const money = (n: unknown) => n == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(n))

/** What each square asked and what this card answered, read only from fields already on the card. */
function explain(card: Escalation, id: string, p: Path): { asked: string; answer: string } {
  const ev = card.evidence as Record<string, unknown>
  const mail = (Array.isArray(ev.correspondence) ? ev.correspondence : []) as unknown as Correspondence[]
  const unsigned = mail.find(m => m.kind === 'unsigned_terms' && !m.signed)
  const took = p.nodes.find(n => n.id === id)?.branches.find(b => b.taken)
  const who = role(card.to_role)
  if (id === 'mechanical') return { asked: `Does ${card.control_id} settle on the agreement alone, with nothing to judge?`,
    answer: `${took?.label}. ${card.control_id} is a judgment control, so the finding went on through the gate instead of being decided by the agent.` }
  if (id === 'mail') return { asked: 'Did mail quote terms that are not signed, on a question about terms?',
    answer: took?.label === 'Yes' && unsigned ? `Yes. ${unsigned.id} from ${unsigned.from} (${unsigned.received})${unsigned.asserted_rate ? ` asserts $${Number(unsigned.asserted_rate).toFixed(2)}/case` : ''}, and nothing is signed. An email is not an amendment, so the card goes to the controller with a hold.`
      : mail.length ? `No. ${mail.length} email${mail.length > 1 ? 's are' : ' is'} quoted on this card; none is unsigned terms that decide it.` : 'No. No mail bears on this finding.' }
  if (id === 'precedent') return { asked: 'Has a person answered a case like this before, with a standing limit that covers it?',
    answer: took?.label === 'No' ? 'No. No precedent governs this case, so it needs a person.' : `Yes, for less. ${card.question.match(/^Precedent \S+ \([^)]*\) covers up to \$[\d,.]+; this one is \$[\d,]+(\.\d+)?/)?.[0].concat('.') ?? 'A precedent exists, but its standing limit is below this exposure.'}` }
  if (id === 'lane') {
    const periods = Array.isArray(ev.periods) ? ev.periods.length : 0
    const answer = ev.amendment_id ? `Closed period changes. Amendment ${ev.amendment_id} reaches ${periods} closed month${periods === 1 ? '' : 's'}; restating is ${who}'s call.`
      : card.escalation_type === 'source_conflict' ? `Sources disagree. ${String(ev.summary ?? card.question).match(/^.*?[.?!](\s|$)/)?.[0]?.trim() ?? ''} Which is right is for ${who}.`
      : card.escalation_type === 'low_confidence' ? `Can't verify from the agreement (low confidence), so it goes to ${who}.`
      : `Needs authority. ${card.control_id} at ${money(card.exposure)} is not a call the agent makes alone; it goes to the control's owner, ${who}.`
    return { asked: 'Which lane does it fall in, and who owns that call?', answer }
  }
  return { asked: `Where this case ended: ${p.leaf.title}.`, answer: `${p.leaf.detail} ${p.outcome.text}` }
}

export default function DecisionTree({ card }: { card: Escalation }) {
  const [sel, setSel] = useState('')
  const p = decisionPath(card)
  const nodes = p.nodes.map((n, i) => ({ ...n, at: { x: 40 + i * STEP_X, y: 60 + (p.nodes.length - 1 - i) * STEP_Y } }))
  const edges: { from: Pt; to: Pt; b: Branch; leafText?: string; up: boolean; fan?: boolean; key?: string; via?: string }[] = []
  nodes.forEach((n, i) => {
    const last = i === nodes.length - 1
    const exits = n.branches.filter(b => b.leaf !== undefined || last)
    const cont = n.branches.find(b => b.leaf === undefined)
    if (cont && !last) edges.push({ from: n.at, to: nodes[i + 1].at, b: cont, up: true })
    if (exits.length === 1) {
      const b = exits[0]
      edges.push({ from: n.at, to: { x: n.at.x + EXIT.x, y: n.at.y + EXIT.y }, b, leafText: b.leaf ?? 'Precedent, then who decides', up: false, key: b.taken ? 'result' : `${n.id}-${n.branches.indexOf(b)}`, via: n.label })
    } else {
      exits.forEach((b, j) => edges.push({ from: n.at, to: { x: n.at.x + FAN_X, y: n.at.y + (j - (exits.length - 1) / 2) * FAN_GAP }, b,
        leafText: b.leaf ?? 'Precedent, then who decides', up: j < (exits.length - 1) / 2, fan: true, key: b.taken ? 'result' : `${n.id}-${n.branches.indexOf(b)}`, via: n.label }))
    }
  })
  const pts = [...nodes.map(n => n.at), ...edges.map(e => e.to)]
  const minY = Math.min(...pts.map(q => q.y)) - 40, maxY = Math.max(...pts.map(q => q.y)) + 30
  const maxX = Math.max(...pts.map(q => q.x)) + 230
  const pick = (k: string) => setSel(s => s === k ? '' : k)
  const keys = (k: string) => (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(k) } }
  const btn = (k: string, label: string, step?: number) => ({ role: 'button', tabIndex: 0, 'aria-pressed': sel === k, 'aria-label': label, 'data-node': k, 'data-step': step,
    className: `tree-node ${sel === k ? 'selected' : ''}`, onClick: () => pick(k), onKeyDown: keys(k) })
  const leafEdge = edges.find(e => e.key === sel)
  const info = !sel ? undefined : leafEdge && sel !== 'result' ? { asked: `${leafEdge.via} ${leafEdge.b.label}`, answer: `Not this case. That branch leads to: ${leafEdge.leafText}.` } : explain(card, sel, p)
  const title = sel === 'result' ? 'Outcome' : nodes.find(n => n.id === sel)?.label ?? (leafEdge ? 'A branch not taken' : '')
  return <section className="decision-tree" aria-label="Why this reached you">
    <h3>WHY THIS REACHED YOU</h3>
    <svg viewBox={`0 ${minY} ${maxX} ${maxY - minY}`} role="group" aria-label={`Decision tree: ${p.nodes.map(n => `${n.label} ${n.branches.find(b => b.taken)?.label}`).join(', ')}; ${p.leaf.title}.`}>
      {edges.map((e, i) => {
        const mx = (e.from.x + e.to.x) / 2, my = (e.from.y + e.to.y) / 2
        return <g key={i} className={e.b.taken ? 'dt-edge taken' : 'dt-edge'}>
          <line x1={e.from.x} y1={e.from.y} x2={e.to.x} y2={e.to.y}/>
          {e.fan
            ? <text className="dt-blabel" x={e.to.x - 16} y={e.to.y - 6} textAnchor="end">{e.b.label}</text>
            : <text className="dt-blabel" x={mx - 4} y={e.up ? my - 9 : my + 17} textAnchor="middle">{e.b.label}</text>}
        </g>
      })}
      {nodes.map((n, i) => <g key={n.id} {...btn(n.id, `${n.label}: explain`, i)}>
        <rect className="dt-hit" x={n.at.x - Math.max(20, n.label.length * 3.6 + 6)} y={n.at.y - 36} width={Math.max(40, n.label.length * 7.2 + 12)} height="54" rx="6"/>
        <rect x={n.at.x - 13} y={n.at.y - 13} width="26" height="26" rx="3" className="dt-square"/>
        <text className="dt-nlabel" x={n.at.x} y={n.at.y - 22} textAnchor="middle">{n.label}</text>
      </g>)}
      {/* Leaves after the squares, the filled one first, so `.tree-node` in document order walks the path: squares, outcome, then the branches not taken. */}
      {[...edges].filter(e => e.leafText !== undefined && e.key).sort((x, y) => Number(y.key === 'result') - Number(x.key === 'result')).map(e => <g key={e.key} {...btn(e.key!, `${e.leafText}: explain`, e.key === 'result' ? nodes.length : undefined)}>
        <rect className="dt-hit" x={e.to.x - 14} y={e.to.y - 14} width={Math.max(150, e.leafText!.length * 6.2 + 34)} height="28" rx="6"/>
        <circle cx={e.to.x} cy={e.to.y} r="10" className={e.b.taken ? 'dt-leaf taken' : 'dt-leaf'}/>
        <text className={e.b.taken ? 'dt-ltext taken' : 'dt-ltext'} x={e.to.x + 18} y={e.to.y + 4}>{e.leafText}</text>
      </g>)}
    </svg>
    {info ? <div className="dt-result dt-explain" role="status" aria-live="polite"><p><b>{title}</b> · <span className="dt-asked">{info.asked}</span></p><p>{info.answer}</p></div>
      : <p className="dt-note">Click a step to see what it checked for this card.</p>}
  </section>
}
