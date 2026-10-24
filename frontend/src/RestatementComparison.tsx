import { useState } from 'react'
import type { Period, TradePromotionApi, Json } from './api'
import './RestatementComparison.css'
const record=(v:Json|undefined):Record<string,Json>=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v:{}
const text=(v:Json|undefined)=>typeof v==='string'?v:'—'
const money=(v:Json|undefined)=>typeof v==='string'&&Number.isFinite(Number(v))?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(v)):'—'
export default function RestatementComparison({period,client}:{period:Period;client:TradePromotionApi}){
 const [selected,setSelected]=useState(0),[detail,setDetail]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const finding=period.findings.find(f=>f.conflict_type==='amendment_not_applied')
 const evidence=finding?.evidence??{}
 const rows=Array.isArray(evidence.periods)?evidence.periods.map(record):[]
 const row=rows[selected]??rows[0]
 const resolution=record(evidence.resolution)
 const corrections=period.postings.filter(p=>p.entry_type==='restatement'&&p.source_finding_id===finding?.id)
 const correction=corrections.find(p=>p.restates===row?.liability_line)
 async function explain(id:string){if(busy||id==='—')return;setBusy(true);setError('');try{setDetail((await client.explainEntry(id)).text)}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
 async function explainCorrection(){
  if(busy||!row)return
  setBusy(true);setError('');setDetail('')
  try{
   const result=await client.explainEntry(text(row.liability_line))
   const entries=result.restated_by
   setDetail(entries.length?JSON.stringify(entries,null,2):'No linked correction was returned for this original ledger entry.')
  }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
 }
 if(!finding)return <section className="restatement-empty">No restatement comparison was returned for this period.</section>
 return <section className="restatement-view"><header className="restatement-banner"><div><p className="restatement-kicker">● {text(evidence.program_id)} · {finding.customer_id}</p><h2>New evidence changes prior-period accounting</h2><p>{text(evidence.summary)}</p></div><aside><small>Total restatement</small><strong>{money(finding.amount)}</strong><button onClick={()=>setDetail(JSON.stringify(evidence,null,2))}>Inspect evidence</button></aside></header>
 {rows.length>0&&<><div className="restatement-panels"><section><header><h3>Then · {text(row.origin)}</h3><span>● Original close</span></header><div className="restatement-value"><small>Accrual recorded</small><strong>{money(row.original_amount)}</strong><p>Rate {money(row.old_rate)} / case · Projected redemption {typeof row.projected_redemption==='string'?`${Number(row.projected_redemption)*100}%`:'—'}</p></div><p className="restatement-section-label">EVIDENCE AVAILABLE THEN</p><details><summary>Original terms · {text(evidence.program_id)}</summary><p>Rate: {money(row.old_rate)} / case</p><p>Known at: {text(row.original_known_at)}</p></details><details><summary>Original close approval</summary><p>{text(row.signed_by)} · {text(row.period_state)}</p></details><button className="ledger-link" disabled={busy} onClick={()=>void explain(text(row.liability_line))}>Open original ledger · {text(row.journal_id)} →</button></section>
 <section><header><h3>Now · {text(evidence.entered_on)}</h3><span>● {finding.state}</span></header><div className="restatement-value revised"><small>Additional adjustment</small><strong>{money(row.catch_up)}</strong><p>Amended rate {money(row.new_rate)} / case</p></div><p className="restatement-section-label">NEW EVIDENCE LEARNED</p><details><summary>Amendment · {text(evidence.amendment_id)}</summary><p>Effective: {text(evidence.effective_date)}</p><p>Received: {text(evidence.entered_on)}</p></details><details><summary>Approval · {text(resolution.by)}</summary><p>{text(resolution.decision)} · {text(resolution.at)}</p><p>Precedent: {text(evidence.precedent_id)}</p></details><button className="ledger-link" disabled={busy} onClick={()=>void explainCorrection()}>Open correction{correction?` · ${correction.journal_id}`:''} →</button></section></div>
 <section className="restatement-impact"><h3>Prior-period impact</h3><div className="table-scroll"><table><thead><tr>{['Period','Original','Adjustment','Amended rate','Ledger record'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={text(r.origin)} className={selected===i?'selected':''}><td><button aria-pressed={selected===i} onClick={()=>{setSelected(i);setDetail('')}}>{text(r.origin)}</button></td><td>{money(r.original_amount)}</td><td className="adjustment">{money(r.catch_up)}</td><td>{money(r.new_rate)} / case</td><td><button disabled={busy} onClick={()=>void explain(text(r.liability_line))}>{text(r.journal_id)} →</button></td></tr>)}</tbody></table></div></section></>}
 {error&&<p role="alert" className="restatement-error">{error}</p>}{busy&&<p role="status">Loading ledger evidence…</p>}{detail&&<section className="restatement-evidence" aria-label="Restatement evidence"><header><h3>Evidence</h3><button onClick={()=>setDetail('')}>Close evidence</button></header><pre>{detail}</pre></section>}</section>
}
