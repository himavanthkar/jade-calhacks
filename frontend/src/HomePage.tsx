import type { Escalation, Period } from './api'
import { headline, role } from './decisionPath'
import './HomePage.css'

/** Home: what needs a person, and nothing else. One line on the problem, three numbers for the month,
 *  the decisions waiting with JADE's recommendation on each. Everything behind them is one click away. */
const NAMES: Record<string, string> = { WMT: 'Walmart', COST: 'Costco', KR: 'Kroger' }
const usd = (v: string | null) => v == null ? '' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(Number(v))

export default function HomePage({ period, cards, onOpen, onStep, stepLabel, stepDisabled }: {
  period?: Period; cards: Escalation[]; onOpen: (card: Escalation) => void; onStep: () => void; stepLabel: string; stepDisabled: boolean
}) {
  const findings = period?.findings ?? []
  const settled = findings.filter(f => f.state === 'auto_resolved').length
  const signed = period?.customers.filter(c => c.signed_at).length ?? 0
  const month = period ? new Date(`${period.period}-01T12:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : '…'
  return <main className="home">
    <section className="home-hero">
      <p className="home-eyebrow">General Mills · trade promotion close</p>
      <h1>Every deduction checked against its agreement.<br/><span>You only see the calls the agreement can't make.</span></h1>
      <details className="home-why"><summary>Why this matters</summary>
        <ul>
          <li><b>$493M</b> in trade promotions owed to retailers sits on General Mills' balance sheet, a critical accounting estimate <a href="https://www.sec.gov/Archives/edgar/data/40704/000162828026046466/gis-20260531.htm" target="_blank" rel="noreferrer">(10-K)</a>.</li>
          <li>Retailers take it back as deductions months later. When the estimate trues up, the quarter moves: <b>−13 / +7 points</b> of Q4 profit growth in FY2025 / FY2026 (earnings releases).</li>
          <li>The costly failure isn't a bad claim. It's a signed amendment nobody entered: six months close short.</li>
        </ul>
      </details>
    </section>

    <section className="home-month" aria-label={`${month} at a glance`}>
      <div><strong>{settled}</strong><span>settled by JADE in {month.split(' ')[0]}</span></div>
      <div className={cards.length ? 'attention' : ''}><strong>{cards.length}</strong><span>waiting on you</span></div>
      <div><strong>{signed} of {period?.customers.length ?? 3}</strong><span>customers signed</span></div>
    </section>

    <section className="home-queue">
      <header><h2>Waiting on you</h2><button className="home-step" disabled={stepDisabled} onClick={onStep}>{stepLabel}</button></header>
      {cards.length ? <ul>{cards.map(c => {
        const rec = c.options.find(o => o.id === c.recommended)
        return <li key={c.id}><button onClick={() => onOpen(c)}>
          <span className="home-who">{NAMES[c.customer_id] ?? c.customer_id}<small>for {role(c.to_role)}</small></span>
          <span className="home-what" title={String(c.evidence.summary ?? c.question)}>{headline(c)}</span>
          <span className="home-amt">{usd(c.exposure)}</span>
          <span className="home-rec">{rec ? `JADE: ${rec.label}` : 'Needs a decision'}</span>
          <span className="home-go">Review →</span>
        </button></li>
      })}</ul> : <p className="home-empty">Nothing needs you. Every finding this month was settled by an agreement or an earlier answer.</p>}
    </section>
  </main>
}
