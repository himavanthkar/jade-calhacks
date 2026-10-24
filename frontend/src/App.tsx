import { useEffect, useMemo, useState } from 'react'
import { api, apiMode } from './api'
import { createMockApi } from './api/mock'
import type { Period, Metrics, Control, Escalation } from './api'
import RecordWorkspace from './RecordWorkspace'
import PeriodPage from './PeriodPage'
import './Records.css'
import './App.css'

const icon = (name: string) => <img className="ui-icon" src={`/figma/jade/${name}.svg`} alt="" />
const pct = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const usd = (n: string | null | undefined) => n == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(Number(n))
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug']
const keys = ['precision', 'recall', 'escalation_rate', 'autonomy'] as const
const labels = ['Precision', 'Recall', 'Escalation rate', 'Autonomy']

export default function App() {
  const client = useMemo(() => apiMode === 'mock' ? createMockApi('moment') : api, [])
  const [data, setData] = useState<{period: Period; metrics: Metrics; baseline: Metrics; controls: Control[]; cards: Escalation[]}>()
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [view, setView] = useState('Overview')
  const [periodTab, setPeriodTab] = useState('Period Status')
  const [drawer, setDrawer] = useState('')
  const [query, setQuery] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const options = { signal: controller.signal }
    async function load() {
      const clock = await client.getClock(options)
      const periodKey = apiMode === 'mock' ? '2026-08' : clock.last_period || clock.current_period
      const [period, metrics, baseline, controls, cards] = await Promise.all([client.getPeriod(periodKey, options), client.getMetrics(periodKey, options), client.getMetrics('month-1', options), client.getControls(options), client.getEscalations(options)])
      if (!controller.signal.aborted) { setData({ period, metrics, baseline, controls, cards }); setError('') }
    }
    load().catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [client, retry])
  useEffect(() => {
    if (!drawer) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawer('') }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [drawer])
  const finding = data?.period.findings.find(f => f.conflict_type === 'amendment_not_applied')
  const open = data?.period.findings.filter(f => f.state === 'open' || f.state === 'escalated') ?? []
  const gates = Object.values(data?.period.gates ?? {})
  const monthIndex = data ? Number(data.period.period.slice(5)) : 8
  const dateLabel = data ? new Date(`${data.period.period}-01T12:00:00`).toLocaleDateString('en-US', {month:'long',year:'numeric'}) : 'August 2026'
  const nav = (name: string, asset: string) => <button className={`nav-item ${view === name ? 'active' : ''}`} onClick={() => setView(name)}>{icon(asset)}<span>{name}</span>{name !== 'Overview' && <span className="chevron">›</span>}</button>
  return <div className={`app-shell ${view === 'Month & Period' ? 'period-active' : ''}`}>
    <aside className="sidebar"><a href="#" className="brand" onClick={e => {e.preventDefault();setView('Overview')}}><b className="brand-mark">J</b><span><strong>JADE</strong></span></a>
      <div className="organization"><b>GM</b><div><strong>General Mills</strong><small>US Retail Finance</small></div>{icon('imgIcon4')}</div>
      <p className="nav-label">WORKSPACE</p><nav>{nav('Overview', 'imgIcon5')}{nav('Month & Period','imgIcon6')}<div className="subnav">{['Period Status','Journal Entries','Verification Gates','Restatement Comparison','Flux & Close Review'].map(x=><button key={x} onClick={()=>{setView('Month & Period');setPeriodTab(x)}}>{x}</button>)}</div>{nav('Controls Library','imgIcon8')}{nav('Escalation Inbox','imgIcon9')}{nav('Interrogation','imgIcon10')}</nav>
      <div className="sidebar-bottom"><small>AUTONOMY STATUS</small><strong><i/> Month {monthIndex} · {data?.period.state.toLowerCase() ?? 'loading'}</strong><p>Evidence from captured API responses</p><span>{apiMode === 'mock' ? 'Seeded demo · Spec v1.0' : 'Connected API'}</span></div>
    </aside>
    <div className="main-shell"><header className="topbar"><form className="search" onSubmit={e=>{e.preventDefault();setDrawer(query ? `Search: ${query}` : 'Search records')}}>{icon('imgIcon')}<input aria-label="Search records" placeholder="Search programs, controls, evidence…" value={query} onChange={e=>setQuery(e.target.value)}/></form><div className="top-actions"><div className="current-month"><small>MONTH {monthIndex}</small><span>{dateLabel}</span></div><button className="step-button" onClick={()=>setDrawer('Month & Period')}>Step month</button><button className="icon-button" aria-label="Open escalation inbox" onClick={()=>setView('Escalation Inbox')}>{icon('imgIcon3')}</button><span className="avatar" title="Demo reviewer">AM</span></div></header>
    {view === 'Month & Period' ? <PeriodPage period={data?.period} metrics={data?.metrics} client={client} tab={periodTab} onTab={setPeriodTab} error={error} onRetry={()=>setRetry(n=>n+1)}/> : view !== 'Overview' ? <div className="records-view"><button onClick={()=>setView('Overview')}>← Overview</button><h1>{view}</h1><RecordWorkspace initialView={view}/></div> : <main className="overview">
      <div className="hero-bars" aria-hidden="true">{[119,130,142,152,161,169,177,187,198,209,219,227,229,226,217,203,188,172,158,146,137,129,121,114,106,99,94,92,95,101,110,121,133,144,155,166,180,196,215,237,260,281,299,313,321,324,324].map((height,i)=><i key={i} style={{height, left:`${(10+i*20.5)/975*100}%`}}/>)}</div>
      <div className="overview-heading"><div><p className="eyebrow">MONTH {monthIndex} · {dateLabel.toUpperCase()}</p><h1>JADE</h1><p>General Mills · US retail trade accounting</p></div><div className="heading-actions"><button onClick={()=>setView('Interrogation')}>{icon('imgIcon11')} Ask AI</button></div></div>
      {error && <div className="error" role="alert">{error} <button onClick={()=>setRetry(n=>n+1)}>Retry</button></div>}
      {!data && !error && <p role="status">Loading captured records…</p>}
      <section className="finding-banner"><div className="finding-icon">{icon('imgIcon12')}</div><div className="finding-copy"><p className="eyebrow">{finding?.state === 'resolved' ? 'RESOLVED' : finding?.state.toUpperCase() ?? 'LOADING'} · WALMART · TP-0214</p><h2>Walmart promotion restatement{finding?.state === 'resolved' ? ' approved' : ''}</h2><p>August evidence revises prior-period accruals. Open the evidence to review the recorded decision.</p></div><div className="impact"><small>Restatement amount</small><strong>{usd(finding?.amount)}</strong><button onClick={()=>setDrawer('Restatement evidence')}>Open evidence {icon('imgIcon13')}</button></div></section>
      <section className="kpi-grid" aria-label="Performance metrics">{keys.map((key,i)=>{const value=data?.metrics[key];const prior=data?.baseline[key];const delta=value!=null&&prior!=null?(value-prior)*100:null;return <article className="kpi" key={key}><div><span>{labels[i]}</span></div><strong>{pct(value)}</strong><small>{delta==null?'Awaiting metrics':`${delta>0?'+':''}${delta.toFixed(1)} pts since Month 1`}</small><div className="meter"><span style={{width:`${(value??0)*100}%`}}/></div></article>})}</section>
      <div className="operations-grid"><section className="month-panel"><div className="section-title"><h2>Month Stepper</h2><span className="green">● Month {monthIndex} {data?.period.state.toLowerCase()}</span></div><div className="month-track">{months.map((m,i)=><div key={m} className={i===monthIndex-1?'selected':''}><span>{i===monthIndex-1?monthIndex:icon('imgIcon14')}</span><small>{m}</small></div>)}</div><div className="counts">{[['Journal lines',data?.period.postings.length],['Verification gates',data?`${gates.filter(g=>g.passed).length}/${gates.length}`:undefined],['Open findings',data?open.length:undefined],['Learned controls',data?.controls.filter(c=>c.learned).length]].map(([label,n])=><div key={label}><small>{label}</small><strong>{n??'—'}</strong></div>)}</div><div className="activity"><button onClick={()=>setDrawer('Verification Gates')}><span>{icon('imgIcon15')}</span><div><strong>Verification gates</strong><small>{data?`${gates.filter(g=>g.passed).length} of ${gates.length} gates passed`:'Loading gate results'}</small></div><span>Review →</span></button><button onClick={()=>setDrawer('Restatement evidence')}><span>{icon('imgIcon16')}</span><div><strong>Historical restatement {finding?.state??''}</strong><small>Walmart TP-0214 · Evidence-backed decision</small></div><span>View →</span></button><button onClick={()=>setView('Controls Library')}><span>{icon('imgIcon17')}</span><div><strong>{data?.controls.length??'—'} controls in library</strong><small>Review thresholds, owners and precedents</small></div><span>Explore →</span></button></div></section>
      <section className="attention-panel"><div className="section-title"><h2>Requires attention</h2><span className="green">● {data?.cards.length??'—'}</span></div><article><small className="green">● {data?.cards.length ? 'Review requested' : 'Up to date'}</small><h3>{data?.cards.length ? `${data.cards.length} open review requests` : 'No open escalations'}</h3><p>For the selected API snapshot.</p><button onClick={()=>setView('Escalation Inbox')}>Open inbox ›</button></article><article><small>PERIOD CLOSE</small><h3>{data?.period.customers.filter(c=>c.state==='CLOSED').length??'—'} customer periods closed</h3><p>Walmart · Costco · Kroger</p><button onClick={()=>setDrawer('Month & Period')}>Review close ›</button></article><article><small>RECORDED DECISION</small><h3>Walmart restatement</h3><p>{finding?.id??'—'} · {finding?.state??'Loading'}</p><button onClick={()=>setDrawer('Restatement evidence')}>Review evidence ›</button></article></section></div>
      <div className="charts-grid"><section className="chart-card"><div className="section-title"><h2>AI Performance Over Time</h2><span className="badge">CAPTURED</span></div><p>Month 1 and Month {monthIndex} · available snapshots</p><div className="comparison-chart">{[0,1,3].map(i=><div key={i}><span>{labels[i]}</span><div><div className="comparison-bar baseline" style={{width:`${(data?.baseline[keys[i]]??0)*100}%`}}/><div className={`comparison-bar series-${i}`} style={{width:`${(data?.metrics[keys[i]]??0)*100}%`}}/></div><strong>{pct(data?.metrics[keys[i]])}</strong></div>)}</div><div className="chart-legend"><span><i className="baseline"/>Month 1</span><span><i/>Month {monthIndex}</span></div><small>Intermediate monthly snapshots are not supplied.</small></section><section className="chart-card exposure"><h2>Restatement by Customer</h2><p>Captured finding · recorded amount</p><div className="exposure-row"><strong>Walmart</strong><b>{usd(finding?.amount)}</b></div><div className="exposure-bar"/><div className="exposure-note"><span className="green">● {finding?.state??'Loading'}</span><p>TP-0214 · Historical accrual correction</p></div><button onClick={()=>setDrawer('Restatement evidence')}>Inspect supporting evidence →</button><small>Seeded simulation · Not actual General Mills financial data</small></section></div>
      <footer className="overview-footer">{apiMode==='mock'?'Captured backend fixtures · Seed 1337':'Connected API'} · Values follow API responses; this is a demonstration workspace.</footer>
    </main>}</div>
    {drawer && <div className="modal-backdrop" onClick={()=>setDrawer('')}><section className="detail-dialog" role="dialog" aria-modal="true" aria-label={drawer} onClick={e=>e.stopPropagation()}><header><h2>{drawer}</h2><button autoFocus aria-label="Close details" onClick={()=>setDrawer('')}>✕</button></header>{drawer==='Restatement evidence'?<div className="evidence-detail"><h3>{usd(finding?.amount)} · {finding?.state}</h3><p>{String(finding?.evidence.summary??'No restatement available.')}</p><pre>{JSON.stringify(finding?.evidence,null,2)}</pre></div>:<RecordWorkspace initialView={drawer}/>}</section></div>}
  </div>
}
