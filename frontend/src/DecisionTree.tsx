import type { Escalation } from './api'
import { decisionPath, type Branch } from './decisionPath'
import './DecisionTree.css'

/** Why this card reached this person, drawn as a decision tree: square decision nodes climbing left to
 *  right, each exit ending in a round leaf. The path this case took is drawn heavy and ends in a filled
 *  leaf; the branches it didn't take stay thin, with where they lead. */
type Pt = { x: number; y: number }
const STEP_X = 140, STEP_Y = 58, EXIT = { x: 95, y: 56 }, FAN_X = 190, FAN_GAP = 40

export default function DecisionTree({ card }: { card: Escalation }) {
  const p = decisionPath(card)
  const nodes = p.nodes.map((n, i) => ({ ...n, at: { x: 40 + i * STEP_X, y: 60 + (p.nodes.length - 1 - i) * STEP_Y } }))
  const edges: { from: Pt; to: Pt; b: Branch; leafText?: string; up: boolean; fan?: boolean }[] = []
  nodes.forEach((n, i) => {
    const last = i === nodes.length - 1
    const exits = n.branches.filter(b => b.leaf !== undefined || last)
    const cont = n.branches.find(b => b.leaf === undefined)
    if (cont && !last) edges.push({ from: n.at, to: nodes[i + 1].at, b: cont, up: true })
    if (exits.length === 1) {
      const b = exits[0]
      edges.push({ from: n.at, to: { x: n.at.x + EXIT.x, y: n.at.y + EXIT.y }, b, leafText: b.leaf ?? 'Precedent, then who decides', up: false })
    } else {
      exits.forEach((b, j) => edges.push({ from: n.at, to: { x: n.at.x + FAN_X, y: n.at.y + (j - (exits.length - 1) / 2) * FAN_GAP }, b,
        leafText: b.leaf ?? 'Precedent, then who decides', up: j < (exits.length - 1) / 2, fan: true }))
    }
  })
  const pts = [...nodes.map(n => n.at), ...edges.map(e => e.to)]
  const minY = Math.min(...pts.map(q => q.y)) - 40, maxY = Math.max(...pts.map(q => q.y)) + 30
  const maxX = Math.max(...pts.map(q => q.x)) + 230
  return <section className="decision-tree" aria-label="Why this reached you">
    <h3>WHY THIS REACHED YOU</h3>
    <svg viewBox={`0 ${minY} ${maxX} ${maxY - minY}`} role="img" aria-label={`Decision tree: ${p.nodes.map(n => `${n.label} ${n.branches.find(b => b.taken)?.label}`).join(', ')}; ${p.leaf.title}.`}>
      {edges.map((e, i) => {
        const mx = (e.from.x + e.to.x) / 2, my = (e.from.y + e.to.y) / 2
        return <g key={i} className={e.b.taken ? 'dt-edge taken' : 'dt-edge'}>
          <line x1={e.from.x} y1={e.from.y} x2={e.to.x} y2={e.to.y}/>
          {e.fan
            ? <text className="dt-blabel" x={e.to.x - 16} y={e.to.y - 6} textAnchor="end">{e.b.label}</text>
            : <text className="dt-blabel" x={mx - 4} y={e.up ? my - 9 : my + 17} textAnchor="middle">{e.b.label}</text>}
          {e.leafText !== undefined && <>
            <circle cx={e.to.x} cy={e.to.y} r="10" className={e.b.taken ? 'dt-leaf taken' : 'dt-leaf'}/>
            <text className={e.b.taken ? 'dt-ltext taken' : 'dt-ltext'} x={e.to.x + 18} y={e.to.y + 4}>{e.leafText}</text>
          </>}
        </g>
      })}
      {nodes.map(n => <g key={n.id}>
        <rect x={n.at.x - 13} y={n.at.y - 13} width="26" height="26" rx="3" className="dt-square"/>
        <text className="dt-nlabel" x={n.at.x} y={n.at.y - 22} textAnchor="middle">{n.label}</text>
      </g>)}
    </svg>
    <div className={`dt-result ${p.outcome.done ? 'dt-done' : 'dt-open'}`}>
      <p><b>{p.leaf.title}.</b> {p.leaf.detail}</p>
      <p className="dt-outcome"><span>{p.outcome.done ? '● Decided' : '○ Open'}</span> {p.outcome.text}</p>
    </div>
    <p className="dt-note">Squares are the checks, in the order the engine runs them on every finding; circles are where a case ends. Read from the card's record: the engine decided, this explains.</p>
  </section>
}
