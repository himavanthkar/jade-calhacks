import { useEffect, useState } from 'react'
import type { Problem, TradePromotionApi } from './api'
import './ProblemStrip.css'

/** The problem in cited numbers (GET /api/problem, tpa/problem.py): the same facts the Ask box and the pitch use. */
export default function ProblemStrip({ client, onAsk }: { client: TradePromotionApi; onAsk: () => void }) {
  const [p, setP] = useState<Problem>()
  useEffect(() => {
    const c = new AbortController()
    client.getProblem({ signal: c.signal }).then(setP).catch(() => undefined)
    return () => c.abort()
  }, [client])
  if (!p) return null
  const [lead, ...rest] = p.story.split('. ')
  return <section className="problem-strip" aria-label="The problem">
    <header><p className="eyebrow">THE PROBLEM, IN GENERAL MILLS' OWN NUMBERS</p><button onClick={onAsk}>Ask JADE why it matters →</button></header>
    <div className="ps-facts">{p.facts.map(f => <a key={f.value + f.label} href={f.url} target="_blank" rel="noreferrer"><strong>{f.value}</strong><span>{f.label}</span><small>{f.source}</small></a>)}</div>
    <p className="ps-story"><b>{lead}.</b> {rest.join('. ')}</p>
  </section>
}
