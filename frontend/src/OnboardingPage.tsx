import { useEffect, useState } from 'react'
import type { Clock, Control, Evidence, Integration, Onboarding, TradePromotionApi } from './api'
import { apiMode } from './api'
import { role } from './decisionPath'
import './OnboardingPage.css'

/** Before the first live month: what JADE was given, what it read, what it learned from last year's
 *  people, and what the controller signed. The Controls Library is step 3: every control was mined
 *  from decisions people made, and each one says which. */
const STEPS = ['Connect sources', 'Read the agreements', 'Learn from last year', 'Set policy', 'Go live'] as const
const NAMES: Record<string, string> = { WMT: 'Walmart', COST: 'Costco', KR: 'Kroger' }
const money = (v: string | number) => `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const ACTION: Record<string, string> = { accept_variance: 'Accepted a variance', adjust: 'Adjusted', reverse_claim: 'Reversed a claim', recover: 'Recovered', write_off: 'Wrote off', escalate: 'Escalated', release_stale_accrual: 'Released a stale accrual' }

function rate(t: Onboarding['programs'][number]) {
  if (t.rate_unit === 'per_case') return `$${Number(t.rate).toFixed(2)} / case${t.projected_redemption ? ` · ${Math.round(Number(t.projected_redemption) * 100)}% sell-through` : ''}`
  if (t.rate_unit === 'pct_of_gross') return `${(Number(t.rate) * 100).toFixed(2)}% of gross`
  return money(t.rate)
}
function threshold(c: Control) {
  if (c.threshold === null || Number(c.threshold) === 0) return 'any'
  return c.threshold_unit === 'usd' ? money(c.threshold) : `${Number(c.threshold)}${c.threshold_unit === 'pct' ? '%' : ' periods'}`
}

export default function OnboardingPage({ client, onDone }: { client: TradePromotionApi; onDone: () => void }) {
  const [step, setStep] = useState(0)
  const [ob, setOb] = useState<Onboarding>()
  const [controls, setControls] = useState<Control[]>([])
  const [sources, setSources] = useState<Integration[]>([])
  const [clock, setClock] = useState<Clock>()
  const [detail, setDetail] = useState<Evidence>()
  const [error, setError] = useState('')
  useEffect(() => {
    const c = new AbortController(), o = { signal: c.signal }
    Promise.all([client.getOnboarding(o), client.getControls(o), client.getIntegrations(o), client.getClock(o)])
      .then(([a, b, s, k]) => { if (!c.signal.aborted) { setOb(a); setControls(b); setSources(s); setClock(k) } })
      .catch(e => { if (!c.signal.aborted) setError(e.message) })
    return () => c.abort()
  }, [client])
  const decisions = ob?.history.reduce((n, h) => n + h.n, 0) ?? 0
  const mined = controls.filter(c => !c.learned), learned = controls.filter(c => c.learned)
  const done = [sources.length > 0, (ob?.programs.length ?? 0) > 0, mined.length > 0, (ob?.policy.length ?? 0) > 0, (clock?.live_month ?? 0) > 1]

  return <main className="onboarding-page">
    <header className="ob-heading"><p className="eyebrow">BEFORE THE FIRST LIVE MONTH</p><h1>Onboarding</h1>
      <p>JADE isn't configured; it is taught. It reads the agreements, replays last year's books and the decisions people made in them, and mines its controls from those decisions. The controller signs the policy, and the first live month runs.</p></header>
    <ol className="ob-stepper">{STEPS.map((s, i) => <li key={s}><button className={`${i === step ? 'current' : ''} ${done[i] ? 'done' : ''}`} aria-current={i === step ? 'step' : undefined} onClick={() => setStep(i)}>
      <span>{done[i] ? '✓' : i + 1}</span><strong>{s}</strong></button></li>)}</ol>
    {error && <p className="ob-error" role="alert">{error}</p>}

    {step === 0 && <section className="ob-panel"><h2>Connect the sources</h2><p className="ob-lede">Where the evidence comes from. Each is read by code; nothing in a source is followed as an instruction.</p>
      <div className="ob-sources">{sources.map(s => <article key={s.id}><img src={s.id === 'gmail' ? '/brand/gmail.svg' : '/brand/sec.svg'} alt=""/><div><strong>{s.name}</strong><small>{s.id === 'gmail' ? 'Deductions inbox: notices, backup, amendments' : '10-K figures for the close’s analytical review'}</small></div><span className={s.status === 'connected' ? 'ok' : 'off'}>● {s.status === 'connected' ? 'Connected' : 'Not connected'}</span></article>)}
        <article><img src="/brand/postgresql.svg" alt=""/><div><strong>Ledger</strong><small>Insert-only, bitemporal: every row knows when it was true and when we learned it</small></div><span className="ok">● Connected</span></article></div>
      <button className="ob-next" onClick={() => setStep(1)}>Next: read the agreements →</button></section>}

    {step === 1 && <section className="ob-panel"><h2>Read the agreements</h2><p className="ob-lede">{ob?.programs.length ?? '…'} trade programs read from their documents into terms. Each term cites the clause it came from; a document that doesn't state a required term is refused, not guessed.</p>
      <div className="ob-table"><table><thead><tr><th>Program</th><th>Customer</th><th>Type</th><th>Terms</th><th>Window</th><th>Read from</th></tr></thead><tbody>
        {ob?.programs.map(t => <tr key={t.program_id}><td><code>{t.program_id}</code></td><td>{NAMES[t.customer_id] ?? t.customer_id}</td><td>{t.program_type.replace('_', ' ')}{t.requires_proof ? ' · proof required' : ''}</td><td>{rate(t)}</td><td>{t.window_start} – {t.window_end}</td><td><code>{t.source_clause_id ?? '—'}</code>{t.amendment_id && <span className="ob-tag">amended {t.amendment_id}</span>}</td></tr>)}
      </tbody></table></div>
      <button className="ob-next" onClick={() => setStep(2)}>Next: learn from last year →</button></section>}

    {step === 2 && <section className="ob-panel"><h2>Learn from last year</h2><p className="ob-lede">JADE replayed the history year and compared its answers with the {decisions} decisions people actually made. Where they did something the rules didn't, it mined a control: the threshold they acted at, and the role that acted.</p>
      <div className="ob-history">{ob?.history.map(h => <span key={h.action}><b>{h.n}</b>{ACTION[h.action] ?? h.action}</span>)}</div>
      <h3>Controls library <small>{mined.length} mined{learned.length ? ` · ${learned.length} learned live` : ''}</small></h3>
      <div className="ob-table"><table><thead><tr><th>Control</th><th>Threshold</th><th>Owner</th><th>Taught by</th><th>Fired</th></tr></thead><tbody>
        {controls.map(c => <tr key={c.id}><td><strong>{c.name}</strong>{c.learned && <span className="ob-tag learned">learned live</span>}<details><summary>Condition</summary><code>{c.condition}</code></details></td><td>{threshold(c)}</td><td>{role(c.owner)}</td>
          <td><details><summary>{c.precedent_ids.length} decision{c.precedent_ids.length === 1 ? '' : 's'} last year · {c.live_precedent_ids.length} this year</summary>{(['history', 'live'] as const).flatMap(kind => (kind === 'history' ? c.precedent_ids : c.live_precedent_ids).map(id => <button key={id} className="ob-chip" onClick={() => client.getPrecedent(kind, id).then(setDetail).catch(e => setError(e.message))}>{id}</button>))}</details></td><td>{c.fired_count}</td></tr>)}
      </tbody></table></div>
      {detail && <div className="ob-detail"><header><strong>Precedent</strong><button onClick={() => setDetail(undefined)}>Close</button></header><pre>{JSON.stringify(detail, null, 2)}</pre></div>}
      <button className="ob-next" onClick={() => setStep(3)}>Next: set policy →</button></section>}

    {step === 3 && <section className="ob-panel"><h2>Set policy</h2><p className="ob-lede">What history can't teach, the controller states. Company policy, not GAAP: GAAP sets no automation thresholds, and each of these can be changed.</p>
      <div className="ob-table"><table><thead><tr><th>Setting</th><th>Value</th><th>Why</th></tr></thead><tbody>
        {ob?.policy.map(p => <tr key={p.name}><td><strong>{p.name}</strong></td><td>{p.unit === 'days' ? `${p.value} days` : p.unit === 'pct' ? `${Number(p.value)}%` : `${Math.round(Number(p.value) * 1000) / 10}%`}</td><td>{p.why}</td></tr>)}
      </tbody></table></div>
      <button className="ob-next" onClick={() => setStep(4)}>Next: go live →</button></section>}

    {step === 4 && <section className="ob-panel"><h2>Go live</h2>
      <div className="ob-golive"><div><strong>{ob?.programs.length ?? '—'}</strong><span>agreements read</span></div><div><strong>{decisions}</strong><span>decisions replayed</span></div><div><strong>{mined.length}</strong><span>controls mined</span></div><div><strong>{clock ? (clock.live_month > 1 ? `Month ${clock.live_month - 1}` : 'Ready') : '—'}</strong><span>{clock && clock.live_month > 1 ? 'live months run' : 'first live month: January'}</span></div></div>
      <p className="ob-lede">From here, every month runs the same way: accrue on shipment, match each claim, clear what the agreement supports, ask a person only when it can't, and reuse the answer.</p>
      <button className="ob-next" onClick={onDone}>Open the overview →</button></section>}
    <footer className="ob-note">{apiMode === 'mock' ? 'Captured from the API (scripts/backtest_fixture.py).' : 'Connected API.'} Thresholds come from last year's decisions or from stated policy, never from GAAP.</footer>
  </main>
}
