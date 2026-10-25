import { useState } from 'react'
import { apiMode } from './api'
import type { Period, Metrics, TradePromotionApi, Finding } from './api'
import './PeriodPage.css'
import JournalEntries from './JournalEntries'
import VerificationGates from './VerificationGates'
import FluxReview from './FluxReview'
import RestatementComparison from './RestatementComparison'
const periodTabs = ['Period Status', 'Journal Entries', 'Verification Gates', 'Restatement Comparison', 'Flux & Close Review'] as const
const names = {WMT:'Walmart', COST:'Costco', KR:'Kroger'}
const money = (v: string | null) => v == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(v))
const human = (v: string) => v.replaceAll('_',' ')
export default function PeriodPage({period, metrics, client, tab, onTab, error, onRetry}: {period?:Period;metrics?:Metrics;client:TradePromotionApi;tab:string;onTab:(tab:string)=>void;error:string;onRetry:()=>void}) {
  const [expanded, setExpanded] = useState<string>('')
  const [detail, setDetail] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const gates = Object.values(period?.gates??{})
  const restatements = period?.findings.filter(f=>f.conflict_type==='amendment_not_applied')??[]
  const date = period ? new Date(`${period.period}-01T12:00:00`).toLocaleDateString('en-US',{month:'long',year:'numeric'}) : ''
  async function run(action:()=>Promise<void>) {if(busy)return;setBusy(true);setActionError('');try{await action()}catch(e){setActionError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  async function exportPackage(){if(!period)return;await run(async()=>{const result=await client.getPackage(period.period);const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`close-package-${period.period}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
  const findingList = (items:Finding[]) => items.length ? items.map(f=><details key={f.id}><summary>{f.id} · {human(f.state)} · {money(f.amount)}</summary><p>{String(f.evidence.summary??f.control_id)}</p><pre>{JSON.stringify(f.evidence,null,2)}</pre></details>) : <p className="period-empty">No findings in this period.</p>
  const gateList = <div className="period-gates">{gates.map((g,i)=><details key={g.name}><summary><span className={`gate-dot ${g.passed?'passed':''}`}>{g.passed?<img src="/figma/jade/gate-check.svg" alt=""/>:i+1}</span><span><strong>{human(g.name)}</strong><small>{g.passed?'Passed':`${g.violations.length} violations`}</small></span><b className={g.passed?'green':'review'}>● {g.passed?'Complete':'Review'}</b></summary><p>{g.description}</p>{g.violations.length>0&&<pre>{JSON.stringify(g.violations,null,2)}</pre>}</details>)}{!gates.length&&<p className="period-empty">No verification results available.</p>}</div>
  return <main className="period-page"><header className="period-heading"><div><p className="eyebrow">{period?`MONTH ${Number(period.period.slice(5))} · ${date.toUpperCase()}`:'LOADING PERIOD'}</p><h1>Month &amp; Period</h1><p>Process the month, verify outputs, and restate prior accounting when new evidence changes the decision.</p></div><div className="period-actions"><button disabled={!period||apiMode==='mock'} title={apiMode==='mock'?'Run the API to open the close report.':'Open the close report; print it to PDF'} onClick={()=>period&&window.open(client.exportUrl(period.period,'close_report.html'),'_blank')}>Close report</button><button disabled={!period||busy||(apiMode==='mock'&&period.period!=='2026-02')} title="Download the close package as JSON" onClick={exportPackage}>{busy?'Loading…':'JSON'}</button><button className="orange" disabled={!period} onClick={()=>onTab('Flux & Close Review')}>{period?.state==='CLOSED'?'Review close':'Continue close'}</button></div></header>
  <nav className="period-tabs" aria-label="Period views">{periodTabs.map(t=><button key={t} aria-current={tab===t?'page':undefined} className={tab===t?'selected':''} onClick={()=>{onTab(t);setDetail('')}}>{t}{t==='Restatement Comparison'&&<span>{restatements.length}</span>}</button>)}</nav>
  {(error||actionError)&&<div className="error" role="alert">{error||actionError} <button onClick={onRetry}>Refresh</button></div>}
  {!period?<p role="status">{error?'Unable to load period.':'Loading period records…'}</p>:<>
  {tab === 'Period Status' && <section className="period-summary"><div><span>Period status</span><strong className={period.state==='CLOSED'?'green':'review'}>● {human(period.state.toLowerCase())}</strong></div><div><span>Autonomy</span><strong>{metrics?.autonomy==null?'—':`${(metrics.autonomy*100).toFixed(1)}%`}</strong></div><div><span>Recorded restatement</span><strong className="review">{restatements.length===1?money(restatements[0].amount):`${restatements.length} findings`}</strong></div><div><span>Verification gates</span><strong>{gates.filter(g=>g.passed).length} of {gates.length} passed</strong></div></section>}
  {tab==='Period Status'&&<div className="period-columns"><section><h2>Findings by customer</h2>{period.customers.map(c=>{const findings=period.findings.filter(f=>f.customer_id===c.customer_id);const unresolved=findings.filter(f=>f.state==='open'||f.state==='escalated');return <div key={c.customer_id}><button className="customer-row" aria-expanded={expanded===c.customer_id} onClick={()=>setExpanded(expanded===c.customer_id?'':c.customer_id)}><b className="customer-mark">{names[c.customer_id][0]}</b><span><strong>{names[c.customer_id]}</strong><small>{findings.length} findings · {unresolved.length} open</small></span><b className={unresolved.length?'review':'green'}>● {human(c.state.toLowerCase())}</b></button>{!unresolved.length&&!c.signed_at&&<button className="sign-off" disabled={busy||apiMode==='mock'} onClick={()=>run(async()=>{await client.signPeriod(period.period,c.customer_id);onRetry()})}>Sign off {names[c.customer_id]}</button>}{c.signed_at&&<span className="signed-by">Signed by {human(c.signed_by??'')} · {c.signed_at.slice(0,10)}</span>}{expanded===c.customer_id&&<div className="customer-findings">{findingList(findings)}</div>}</div>})}</section><section><h2>Verification Gates</h2>{gateList}</section></div>}
  {tab==='Verification Gates'&&<VerificationGates period={period}/>}
  {tab==='Journal Entries'&&<JournalEntries postings={period.postings} client={client}/>}
  {tab==='Restatement Comparison'&&<RestatementComparison period={period} client={client}/>}
  {tab==='Flux & Close Review'&&<FluxReview flux={period.flux} client={client}/>}
  </>}{detail&&<div className="period-evidence" role="region" aria-label="Journal evidence"><button onClick={()=>setDetail('')}>Close evidence</button><pre>{detail}</pre></div>}</main>
}
