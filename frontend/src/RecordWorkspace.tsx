import { useEffect, useMemo, useState } from 'react'
import { api, apiMode } from './api'
import { createMockApi } from './api/mock'
import type { AskResponse, Clock, Control, Escalation, Evidence, Metrics, Period, TradePromotionApi } from './api'


type Scenario = 'inbox' | 'moment'
const money = (value: string | null) => value === null ? 'N/A' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
const percent = (value: number | null | undefined) => value == null ? 'N/A' : `${(value * 100).toFixed(2).replace(/\.00$/, '')}%`
const role = (value: string) => value.replaceAll('_', ' ')
const customer = { WMT: 'Walmart', COST: 'Costco', KR: 'Kroger' }

export default function RecordWorkspace({ initialView = '' }: { initialView?: string }) {
  const [scenario, setScenario] = useState<Scenario>('moment')
  const client = useMemo(() => apiMode === 'mock' ? createMockApi(scenario) : api, [scenario])
  return <div className="workspace">
    <header className="page-header"><div><p>GENERAL MILLS / TRADEWISE</p><h1>Trade Promotion Autonomy</h1></div>
      <div><span className="status">{apiMode === 'mock' ? 'Captured API fixtures · Seeded simulation' : 'Live API'}</span>
        {apiMode === 'mock' && <label className="scenario">Scenario <select value={scenario} onChange={e => setScenario(e.target.value as Scenario)}><option value="moment">August · Restatement resolved</option><option value="inbox">January–February · Review inbox</option></select></label>}
      </div>
    </header>
    <Dashboard initialView={initialView} key={`${apiMode}-${scenario}`} client={client} scenario={scenario} />
  </div>
}

function Dashboard({ client, scenario, initialView }: { initialView: string; client: TradePromotionApi; scenario: Scenario }) {
  const [clock, setClock] = useState<Clock>()
  const [selected, setSelected] = useState('')
  const [period, setPeriod] = useState<Period>()
  const [controls, setControls] = useState<Control[]>([])
  const [cards, setCards] = useState<Escalation[]>([])
  const [metrics, setMetrics] = useState<Metrics>()
  const [baseline, setBaseline] = useState<Metrics>()
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [question, setQuestion] = useState('Why did you post JE-1058?')
  const [answer, setAnswer] = useState<AskResponse>()
  const [detail, setDetail] = useState<Evidence>()
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const options = { signal: controller.signal }

    async function load() {
      const c = await client.getClock(options)
      const p = selected || (apiMode === 'mock' && scenario === 'moment' ? '2026-08' : c.current_period)
      const [data, rules, inbox] = await Promise.all([client.getPeriod(p, options), client.getControls(options), client.getEscalations(options)])
      const [m, b] = await Promise.allSettled([client.getMetrics(p, options), client.getMetrics('month-1', options)])
      if (controller.signal.aborted) return
      setClock(c); setPeriod(data); setControls(rules); setCards(inbox)
      setMetrics(m.status === 'fulfilled' ? m.value : undefined)
      setBaseline(b.status === 'fulfilled' ? b.value : undefined)
      if (m.status === 'rejected' && data.state !== 'OPEN') setNotice('Metrics unavailable for this period. Other records loaded successfully.')
    }
    load().catch(e => { if (!controller.signal.aborted) setError(String(e.message ?? e)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, selected, refresh, scenario])

  async function act(action: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const finding = period?.findings.find(f => f.conflict_type === 'amendment_not_applied')
  const disabled = busy || loading
  useEffect(() => {
    const headings = Array.from(document.querySelectorAll('.detail-dialog .panel h2, .records-view .panel h2'))
    const heading = headings.find(h => h.textContent?.startsWith(initialView))
    heading?.scrollIntoView({ block: 'start' })
  }, [initialView])
  return <>
    {error && <div role="alert" className="error">{error} <button onClick={() => setRefresh(x => x + 1)} disabled={disabled}>Refresh records</button></div>}
    {notice && <p role="status" className="notice">{notice}</p>}
    <section className="panel">
      <div className="panel-heading"><h2>Month & Period</h2><span>{loading ? 'Loading…' : period?.state}</span></div>
      <div className="toolbar"><label>View month <input aria-label="View month" type="month" min="2026-01" max="2026-12" value={selected || period?.period || ''} disabled={disabled} onChange={e => { if (e.target.value) setSelected(e.target.value) }} /></label>
        <button disabled={disabled || !clock || (apiMode === 'mock' && (scenario === 'moment' || clock.current_period > '2026-02'))} onClick={() => act(async () => { const next = clock!.current_period; await client.stepPeriod(next); setSelected(next); setRefresh(x => x + 1) })}>Step {clock?.current_period ?? 'month'}</button>
        <span className="hint">Selected: {period?.period ?? '—'} · Next cycle: {clock?.current_period ?? '—'}</span>
      </div>
      {apiMode === 'mock' && <p className="hint">{scenario === 'moment' ? 'August capture after controller approval. For open review cards, select January–February.' : 'Replay covers January and February. Step January to load controls and review requests. Answers change this local replay only.'}</p>}
      <div className="summary-grid">{(['precision', 'recall', 'escalation_rate', 'autonomy'] as const).map(key => <div className="metric" key={key}><span>{role(key)}</span><strong>{percent(metrics?.[key])}</strong><small>Month 1: {percent(baseline?.[key])}</small></div>)}</div>
      {finding && <article className="notice"><strong>Resolved · Walmart restatement · {money(finding.amount)}</strong><p>{String(finding.evidence.summary)}</p><p>Resolution: {finding.state} · Historical issue, not a pending approval</p></article>}
      <div className="toolbar">{period?.customers.map(c => <span className="status" key={c.customer_id}>{customer[c.customer_id]} · {c.state}</span>)}</div>
      <details><summary>Verification gates ({Object.keys(period?.gates ?? {}).length})</summary>{Object.values(period?.gates ?? {}).map(g => <p key={g.name}>{g.passed ? 'PASS' : 'BLOCKED'} · {g.description} ({g.violations.length} violations)</p>)}{!Object.keys(period?.gates ?? {}).length && <p>No gate results for this period.</p>}</details>
      <details><summary>Journal entries ({period?.postings.length ?? 0})</summary><div className="table-scroll"><table><thead><tr><th>Entry</th><th>Customer</th><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>{period?.postings.map(p => <tr key={p.id}><td><button disabled={disabled} onClick={() => act(async () => { const e = await client.explainEntry(p.id); setAnswer({ question: p.id, answer: e.text, chains: [e.chain], knowledge: null, drafted_by: 'agent' }) })}>{p.id}</button></td><td>{customer[p.customer_id]}</td><td>{p.account}</td><td>{money(p.debit)}</td><td>{money(p.credit)}</td></tr>)}</tbody></table></div></details>
      <details><summary>Flux commentary ({period?.flux.length ?? 0})</summary>{period?.flux.map(f => <article key={f.id}><h3>{f.account}</h3><p>{f.narrative}</p><small>{f.driver_entry_ids.join(' · ')}</small></article>)}</details>
    </section>
    <section className="panel"><h2>Controls Library</h2><div className="table-scroll"><table><thead><tr><th>Rule</th><th>Threshold</th><th>Owner</th><th>Precedent</th><th>Fired</th></tr></thead><tbody>{controls.map(c => <tr key={c.id}><td>{c.name}{c.learned && <span className="status">Learned</span>}<details><summary>Condition</summary>{c.condition}</details></td><td>{c.threshold === null ? 'N/A' : c.threshold_unit === 'usd' ? money(c.threshold) : `${Number(c.threshold)}${c.threshold_unit === 'pct' ? '%' : ' periods'}`}</td><td>{role(c.owner)}</td><td><details><summary>{c.precedent_ids.length} historical · {c.live_precedent_ids.length} live</summary>{(['history', 'live'] as const).flatMap(kind => (kind === 'history' ? c.precedent_ids : c.live_precedent_ids).map(id => <button key={id} disabled={disabled} onClick={() => act(async () => setDetail(await client.getPrecedent(kind, id)))}>{id}</button>))}</details></td><td>{c.fired_count}</td></tr>)}</tbody></table></div>{!controls.length && <p className="hint">No controls loaded. In inbox replay, step January to run onboarding.</p>}
    {detail && <div className="notice"><button onClick={() => setDetail(undefined)}>Close precedent</button><pre>{JSON.stringify(detail, null, 2)}</pre></div>}</section>
    <section className="panel"><h2>Escalation Inbox · {cards.length} open</h2>{!cards.length && <p className="hint">No open review requests in this capture.</p>}
      <div className="inbox-grid">{cards.map(c => <article className="review-card" key={c.id}><small>{c.id} · {c.period} · {customer[c.customer_id]} · {role(c.to_role)}</small><h3>{String(c.evidence.summary ?? c.question)}</h3><p>{c.question}</p><details><summary>Evidence</summary><pre>{JSON.stringify(c.evidence, null, 2)}</pre></details><div className="toolbar">{c.options.map(o => <button disabled={disabled} key={o.id} onClick={() => act(async () => { const result = await client.answerEscalation(c.id, o.id); setNotice(result?.escalated_to ? 'Routed to controller.' : `Response saved${result?.precedent_id ? ` · ${result.precedent_id}` : ''}.`); setRefresh(x => x + 1) })}>{o.label}</button>)}</div></article>)}</div>
    </section>
    <section className="panel"><h2>Interrogation</h2><form onSubmit={e => { e.preventDefault(); act(async () => setAnswer(await client.ask(question))) }}><label htmlFor="question">Ask why a decision was made</label><div className="question-row"><input id="question" value={question} onChange={e => setQuestion(e.target.value)} /><button disabled={disabled || !question.trim()}>Ask</button></div></form><div className="toolbar">{['Why did you post JE-1058?', 'What did it know in March?'].map(q => <button disabled={disabled} key={q} onClick={() => { setQuestion(q); act(async () => setAnswer(await client.ask(q))) }}>{q}</button>)}</div>
      {answer && <div aria-live="polite"><pre>{answer.answer}</pre>{answer.chains.map(c => <details key={c.entry_id}><summary>{c.head}</summary>{c.steps.map((s, i) => <p key={i}><strong>{s.label}</strong> · {s.text}</p>)}</details>)}</div>}
    </section>
    <footer>{apiMode === 'mock' ? 'Seed 1337 · Captured backend responses, not real General Mills transactions. Replay decisions do not recalculate captured metrics or ledger entries. Reload or switch scenarios to reset.' : 'Connected to configured API. Mutations are not retried automatically.'}</footer>
  </>
}
