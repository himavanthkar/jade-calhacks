import { useEffect, useMemo, useState } from 'react'
import { api, apiMode } from './api'
import { createMockApi } from './api/mock'
import type { Clock, Period, Metrics, Control, Escalation, StepSummary } from './api'
import RecordWorkspace from './RecordWorkspace'
import ControlsLibrary from './ControlsLibrary'
import PeriodPage from './PeriodPage'
import InterrogationPage from './InterrogationPage'
import EscalationInbox from './EscalationInbox'
import ScenarioPanel from './ScenarioPanel'
import IntegrationsPage from './IntegrationsPage'
import BacktestPage from './BacktestPage'
import OnboardingPage from './OnboardingPage'
import HomePage from './HomePage'
import LandingPage from './LandingPage'
import ErrorNotice from './ErrorNotice'
import './Records.css'
import './App.css'

const icon = (name: string) => name === 'integration-plug' ? <svg className="integration-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 3v5m6-5v5M6 8h12v3a6 6 0 0 1-6 6v4M6 8v3a6 6 0 0 0 6 6" /></svg> : <img className="ui-icon" src={`/figma/jade/${name}.svg`} alt="" />
const usd = (n: string | null | undefined) => n == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(Number(n))

// clock.last_period is where the simulation ends, not the last month run: show the month before the clock.
function lastRun(clock: Clock) {
  if (clock.current_period > clock.last_period) return clock.last_period
  const [y, m] = clock.current_period.split('-').map(Number)
  if (clock.live_month <= 1) return clock.current_period
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`
}

export default function App() {
  // ?escalation=ESC-0018 opens that card in Decisions, past the landing; its lane is found once the cards load.
  const [deepLink] = useState(() => new URLSearchParams(window.location.search).get('escalation') ?? '')
  const [showLanding, setShowLanding] = useState(!deepLink)
  const client = useMemo(() => apiMode === 'mock' ? createMockApi('moment') : api, [])
  const [data, setData] = useState<{clock: Clock; period: Period; metrics?: Metrics; baseline?: Metrics; controls: Control[]; cards: Escalation[]}>()
  const [stepping, setStepping] = useState(false)
  const [stepError, setStepError] = useState<unknown>()
  const [stepped, setStepped] = useState<StepSummary>()
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [view, setView] = useState(deepLink ? 'Escalation Inbox' : 'Overview')
  const [periodTab, setPeriodTab] = useState('Period Status')
  const [periodNavOpen, setPeriodNavOpen] = useState(false)
  const [drawer, setDrawer] = useState('')
  const [query, setQuery] = useState('')
  const [focus, setFocus] = useState<{ id: string; role?: string } | undefined>(deepLink ? { id: deepLink } : undefined)
  useEffect(() => { if (deepLink) { const u = new URL(window.location.href); u.searchParams.delete('escalation'); window.history.replaceState(null, '', u) } }, [deepLink])
  useEffect(() => {
    const controller = new AbortController()
    const options = { signal: controller.signal }
    async function load() {
      const clock = await client.getClock(options)
      const periodKey = apiMode === 'mock' ? '2026-08' : lastRun(clock)
      // Metrics need the answer key and a run month; their absence shouldn't blank the overview.
      const [period, controls, cards, metrics, baseline] = await Promise.all([client.getPeriod(periodKey, options), client.getControls(options), client.getEscalations(options),
        client.getMetrics(periodKey, options).catch(() => undefined), client.getMetrics('month-1', options).catch(() => undefined)])
      if (!controller.signal.aborted) { setData({ clock, period, metrics, baseline, controls, cards }); setError('') }
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
  // Only the month the clock is on can be stepped; no automatic retry, since stepping twice changes the books.
  async function stepMonth() {
    if (!data || stepping) return
    setStepping(true); setStepError(undefined); setStepped(undefined)
    try { setStepped(await client.stepPeriod(data.clock.current_period)) } catch (e) { setStepError(e) } finally { setStepping(false); setRetry(n => n + 1) }
  }
  const stepBlocked = apiMode === 'mock' ? 'The overview replays the month-8 capture; run the API to step months.' : !data ? 'Loading the clock…' : ''
  const finding = data?.period.findings.find(f => f.conflict_type === 'amendment_not_applied')
  const monthIndex = data ? Number(data.period.period.slice(5)) : 8
  const dateLabel = data ? new Date(`${data.period.period}-01T12:00:00`).toLocaleDateString('en-US', {month:'long',year:'numeric'}) : 'August 2026'
  const nav = (name: string, asset: string, label = name) => <button className={`nav-item ${view === name ? 'active' : ''}`} aria-expanded={name === 'Month & Period' ? periodNavOpen : undefined} aria-controls={name === 'Month & Period' ? 'period-navigation' : undefined} onClick={() => {setView(name);if(name === 'Month & Period')setPeriodNavOpen(open=>!open)}}>{icon(asset)}<span>{label}</span>{name === 'Month & Period' && <span aria-hidden="true" className={`chevron ${periodNavOpen ? 'expanded' : ''}`}>›</span>}</button>
  return <>
    {showLanding && <div className="landing-overlay"><LandingPage onEnter={v => {if (v) setView(v);if (v === 'Month & Period') setPeriodNavOpen(true);setShowLanding(false);window.scrollTo(0, 0)}}/></div>}
    <div inert={showLanding} className={`app-shell ${view === 'Month & Period' ? 'period-active' : ''}`}>
    <aside className="sidebar"><a href="#" className="brand" onClick={e => {e.preventDefault();setView('Overview')}}><b className="brand-mark">J</b><span><strong>JADE</strong></span></a>
      <div className="organization"><b>GM</b><div><strong>General Mills</strong><small>US Retail Finance</small></div>{icon('imgIcon4')}</div>
      <p className="nav-label">WORKSPACE</p><nav>{nav('Overview', 'imgIcon5', 'Home')}{nav('Escalation Inbox','imgIcon9','Decisions')}{nav('Month & Period','imgIcon6','Close')}<div id="period-navigation" className="subnav" hidden={!periodNavOpen}>{['Period Status','Journal Entries','Verification Gates','Restatement Comparison','Flux & Close Review'].map(x=><button key={x} aria-current={view==='Month & Period'&&periodTab===x?'page':undefined} onClick={()=>{setView('Month & Period');setPeriodTab(x)}}>{x}</button>)}</div>{nav('Interrogation','imgIcon10','Ask')}</nav>
      <p className="nav-label">BEHIND THE SCENES</p><nav>{nav('Onboarding','imgIcon8','Setup')}{nav('Controls Library','imgIcon8')}{nav('Integrations','integration-plug')}{nav('Backtest','imgIcon8','Proof')}{nav('Live Scenario','imgIcon12','Try a scenario')}</nav>
      <div className="sidebar-bottom"><small>AUTONOMY STATUS</small><strong><i/> Month {monthIndex} · {data?.period.state.toLowerCase() ?? 'loading'}</strong><p>{apiMode === 'mock' ? 'Evidence from captured API responses' : 'Live engine · every number from the ledger'}</p><span>{apiMode === 'mock' ? 'Seeded demo · Spec v1.0' : 'Connected API'}</span></div>
    </aside>
    <div className="main-shell"><header className="topbar"><form className="search" onSubmit={e=>{e.preventDefault();setDrawer(query ? `Search: ${query}` : 'Search records')}}>{icon('imgIcon')}<input aria-label="Search records" placeholder="Search programs, controls, evidence…" value={query} onChange={e=>setQuery(e.target.value)}/></form><div className="top-actions"><div className="current-month"><small>MONTH {monthIndex}</small><span>{dateLabel}</span></div><button className="step-button" disabled={stepping||Boolean(stepBlocked)} title={stepBlocked||`Run ${data?.clock.current_period}`} onClick={()=>void stepMonth()}>{stepping?'Running…':data?`Step ${data.clock.current_period}`:'Step month'}</button><button className="icon-button" aria-label="Open escalation inbox" onClick={()=>setView('Escalation Inbox')}>{icon('imgIcon3')}</button><span className="avatar" title="Demo reviewer">AM</span></div></header>
    {(stepError || stepped) && <div className="step-result">{stepError ? <ErrorNotice error={stepError} onRetry={()=>setStepError(undefined)} retryLabel="Dismiss"/> : stepped && <p role="status">{stepped.period} ran · {Object.entries(stepped.states).map(([c,s])=>`${c} ${s.toLowerCase()}`).join(' · ')} · {stepped.findings.length} findings{stepped.findings.some(f=>f[1]==='escalated')?' · cards waiting in the inbox':''} <button onClick={()=>setStepped(undefined)}>Dismiss</button></p>}</div>}
    {view === 'Controls Library' ? <ControlsLibrary controls={data?.controls} period={data?.period} client={client} error={error} onRetry={()=>setRetry(n=>n+1)}/> : view === 'Live Scenario' ? <ScenarioPanel client={client} onUpdated={()=>setRetry(n=>n+1)} onNavigate={setView}/> : view === 'Integrations' ? <IntegrationsPage client={client} onUpdated={()=>setRetry(n=>n+1)}/> : view === 'Backtest' ? <BacktestPage client={client}/> : view === 'Onboarding' ? <OnboardingPage client={client} onDone={()=>setView('Overview')}/> : view === 'Escalation Inbox' ? <EscalationInbox key={focus?.id} client={client} focus={focus} onUpdated={()=>setRetry(n=>n+1)}/> : view === 'Interrogation' ? <InterrogationPage client={client}/> : view === 'Month & Period' ? <PeriodPage period={data?.period} metrics={data?.metrics} client={client} tab={periodTab} onTab={setPeriodTab} error={error} onRetry={()=>setRetry(n=>n+1)}/> : view !== 'Overview' ? <div className="records-view"><button onClick={()=>setView('Overview')}>← Overview</button><h1>{view}</h1><RecordWorkspace initialView={view}/></div> : <HomePage period={data?.period} cards={data?.cards ?? []} onOpen={c=>{setFocus({id:c.id,role:c.to_role});setView('Escalation Inbox')}} onStep={()=>void stepMonth()} stepDisabled={stepping||Boolean(stepBlocked)} stepLabel={stepping?'Running…':data?`Run ${new Date(`${data.clock.current_period}-01T12:00:00`).toLocaleDateString('en-US',{month:'long'})}`:'Run the month'}/>}</div>
    {drawer && <div className="modal-backdrop" onClick={()=>setDrawer('')}><section className="detail-dialog" role="dialog" aria-modal="true" aria-label={drawer} onClick={e=>e.stopPropagation()}><header><h2>{drawer}</h2><button autoFocus aria-label="Close details" onClick={()=>setDrawer('')}>✕</button></header>{drawer==='Restatement evidence'?<div className="evidence-detail"><h3>{usd(finding?.amount)} · {finding?.state}</h3><p>{String(finding?.evidence.summary??'No restatement available.')}</p><pre>{JSON.stringify(finding?.evidence,null,2)}</pre></div>:<RecordWorkspace initialView={drawer}/>}</section></div>}
  </div></>
}
