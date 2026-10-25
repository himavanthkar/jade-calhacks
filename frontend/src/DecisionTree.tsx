import type { Escalation } from './api'
import { decisionPath } from './decisionPath'
import './DecisionTree.css'

/** Why this card reached this person: the judgment gate, with the path this case took lit and the
 *  branches it didn't take shown with where they lead. */
export default function DecisionTree({ card }: { card: Escalation }) {
  const p = decisionPath(card)
  return <section className="decision-tree" aria-label="Why this reached you">
    <h3>WHY THIS REACHED YOU</h3>
    <ol>
      {p.steps.map((s, i) => <li key={s.id} className="dt-step">
        <span className="dt-node">{i + 1}</span>
        <div className="dt-body">
          <p className="dt-q">{s.question}</p>
          <div className="dt-branches">
            <span className="dt-branch taken"><b>{s.taken.label}</b> → {s.taken.leadsTo}</span>
            {s.other.map(o => <span key={o.label} className="dt-branch"><b>{o.label}</b> → {o.leadsTo}</span>)}
          </div>
        </div>
      </li>)}
      <li className="dt-step leaf">
        <span className="dt-node">✓</span>
        <div className="dt-body"><p className="dt-q">{p.leaf.title}</p><p className="dt-detail">{p.leaf.detail}</p></div>
      </li>
      <li className={`dt-step outcome ${p.outcome.done ? 'done' : 'open'}`}>
        <span className="dt-node">{p.outcome.done ? '●' : '○'}</span>
        <div className="dt-body"><p className="dt-q">{p.outcome.done ? 'Decided' : 'Open'}</p><p className="dt-detail">{p.outcome.text}</p></div>
      </li>
    </ol>
    <p className="dt-note">The same gate runs on every finding, in this order. Read from the card's record; the engine decided, this explains.</p>
  </section>
}
