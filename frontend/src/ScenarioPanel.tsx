import { useEffect, useState } from 'react'
import type { Clock, Evidence, InjectResult, Injection, ScenarioExample, ScenarioKind, TradePromotionApi } from './api'
import { apiMode } from './api'
import ErrorNotice from './ErrorNotice'
import './ScenarioPanel.css'

const kinds: {id:ScenarioKind;name:string;template:Evidence}[]=[
  {id:'deduction',name:'Deduction',template:{customer_id:'WMT',program_id:'TP-0214',amount:'25000.00',day:3}},
  {id:'duplicate',name:'Duplicate claim',template:{deduction_id:'DD-',day:8}},
  {id:'backup',name:'Claim backup',template:{deduction_id:'DD-',scan_units:10000,scan_rate:'3.80',proof_of_performance:false,day:4}},
  {id:'return',name:'Return',template:{shipment_id:'SH-',cases:500,day:10}},
  {id:'amendment',name:'Amendment',template:{program_id:'TP-0214',new_rate:'4.00',effective_date:'2026-01-01',day:12}},
  {id:'approval_attempt',name:'Approval attempt',template:{actor_id:'sales.walmart',target_type:'deduction',target_id:'DD-',day:9}},
  {id:'handoff',name:'Handoff',template:{from_actor:'deductions.human',deduction_id:'DD-',proposed_decision:'clear',done:'',left_to_do:'',day:4}},
]
const kindName=(k:string)=>kinds.find(x=>x.id===k)?.name??k
const pretty=(v:unknown)=>JSON.stringify(v,null,2)
const human=(v:string)=>v.replaceAll('_',' ')

export default function ScenarioPanel({client,onUpdated,onNavigate}:{client:TradePromotionApi;onUpdated:()=>void;onNavigate:(view:string)=>void}) {
  const [clock,setClock]=useState<Clock>()
  const [examples,setExamples]=useState<ScenarioExample[]>([])
  const [history,setHistory]=useState<Injection[]>([])
  const [chosen,setChosen]=useState('')
  const [kind,setKind]=useState<ScenarioKind>('deduction')
  const [payload,setPayload]=useState(pretty(kinds[0].template))
  const [by,setBy]=useState('judge')
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState<unknown>()
  const [result,setResult]=useState<InjectResult>()
  const [refresh,setRefresh]=useState(0)
  useEffect(()=>{
    const c=new AbortController();const options={signal:c.signal}
    Promise.all([client.getClock(options),client.getScenarioExamples(options),client.getInjections(options)])
      .then(([k,e,h])=>{if(c.signal.aborted)return;setClock(k);setExamples(e);setHistory(h)})
      .catch(e=>{if(!c.signal.aborted)setError(e)}).finally(()=>{if(!c.signal.aborted)setLoading(false)})
    return ()=>c.abort()
  },[client,refresh])
  let parsed:Evidence|undefined,parseError=''
  try{const v=JSON.parse(payload);if(v&&typeof v==='object'&&!Array.isArray(v))parsed=v;else parseError='The payload must be a JSON object.'}catch(e){parseError=e instanceof Error?e.message:String(e)}
  function pick(e:ScenarioExample){setChosen(e.title);setKind(e.kind);setPayload(pretty(e.payload));setResult(undefined);setError(undefined)}
  function pickKind(k:ScenarioKind){setChosen('');setKind(k);setPayload(pretty(kinds.find(x=>x.id===k)!.template))}
  async function inject(step:boolean){
    if(!parsed||busy)return
    setBusy(true);setError(undefined);setResult(undefined)
    try{setResult(await client.injectScenario(kind,parsed,{step,injectedBy:by.trim()||undefined}));onUpdated()}
    catch(e){setError(e)}
    finally{setBusy(false);setRefresh(n=>n+1)}
  }
  const escalated=result?.findings?.filter(f=>f.state==='escalated'||f.state==='open')??[]
  return <main className="scenario-page"><header className="scenario-heading"><p className="eyebrow">JUDGE INPUT</p><h1>Live Scenario</h1><div><p>Hand the system a situation of your own. Rows land in the month the clock is on, and the engine meets them on the next step as it meets everything else. Nothing here decides or posts.</p><span>{clock?`● Lands in ${clock.current_period} · sim date ${clock.sim_date}`:loading?'Loading clock…':'● Clock unavailable'}</span></div></header>
    {apiMode==='mock'&&<p className="scenario-note">Mock mode: you can browse and edit the examples, but injecting needs the engine. Run <code>make api</code> and set <code>VITE_API_MODE=http</code>.</p>}
    <div className="scenario-layout"><aside className="scenario-examples"><h2>Ready-made, against the books as they stand</h2>{loading?<p role="status">Loading examples…</p>:examples.length?examples.map(e=><button key={e.title} className={chosen===e.title?'selected':''} aria-pressed={chosen===e.title} onClick={()=>pick(e)}><small>{kindName(e.kind)}</small><strong>{e.title}</strong></button>):<p className="scenario-empty">No examples for this month.</p>}
      <h2>Or write your own</h2><div className="scenario-kinds">{kinds.map(k=><button key={k.id} className={!chosen&&kind===k.id?'selected':''} onClick={()=>pickKind(k.id)}>{k.name}</button>)}</div></aside>
      <section className="scenario-editor"><header><div><p className="eyebrow">{kindName(kind).toUpperCase()}</p><h2>{chosen||`Custom ${kindName(kind).toLowerCase()}`}</h2></div><label>Injected by <input value={by} onChange={e=>setBy(e.target.value)} placeholder="judge"/></label></header>
        <label htmlFor="scenario-payload" className="scenario-label">Payload</label>
        <textarea id="scenario-payload" spellCheck={false} value={payload} onChange={e=>setPayload(e.target.value)} aria-invalid={Boolean(parseError)} disabled={busy}/>
        {parseError&&<p className="scenario-parse" role="alert">{parseError}</p>}
        <div className="scenario-actions"><button disabled={busy||!parsed} onClick={()=>void inject(false)}>Add to {clock?.current_period??'month'}</button><button className="run" disabled={busy||!parsed} onClick={()=>void inject(true)}>{busy?'Running…':`Add & run ${clock?.current_period??'month'}`}</button></div>
        <ErrorNotice error={error} onRetry={()=>{setError(undefined);setRefresh(n=>n+1)}} retryLabel="Reload"/>
        {result&&<section className="scenario-result" aria-live="polite"><header><p className="eyebrow">{result.id} · LANDED {result.lands_on}</p><h3>{result.step?`${result.period} ran with your rows`:`Added to ${result.period}. Step the month to run it.`}</h3></header>
          <p className="scenario-ids">Created: {result.created_ids.map(id=><code key={id}>{id}</code>)}</p>
          {result.step&&<><div className="scenario-states">{Object.entries(result.step.states).map(([c,s])=><span key={c} className={s==='BLOCKED'?'blocked':''}>{c} · {human(s.toLowerCase())}</span>)}</div>
            <h4>What it did with them</h4>{result.findings?.length?<ul className="scenario-findings">{result.findings.map(f=><li key={f.id} className={f.escalation_type==='sod'?'sod':''}><div><strong>{f.id} · {human(f.state)}</strong><small>{f.escalation_type==='sod'?'Segregation of duties block':f.escalation_type?`${human(f.escalation_type)} escalation`:f.control_id} · {f.customer_id}{f.amount&&` · $${Number(f.amount).toLocaleString('en-US',{minimumFractionDigits:2})}`}</small></div><p>{String(f.evidence.summary??'')}</p></li>)}</ul>:<p className="scenario-empty">No finding names these rows: they passed the controls and settled without a person.</p>}
            {escalated.length>0&&<button onClick={()=>onNavigate('Escalation Inbox')}>Open the {escalated.length} card{escalated.length===1?'':'s'} in the inbox ›</button>}
            <details><summary>Run log ({result.step.log.length})</summary><pre>{result.step.log.join('\n')}</pre></details></>}
        </section>}
      </section></div>
    <section className="scenario-history"><h2>Injected so far · {history.length}</h2>{history.length?<table><thead><tr>{['Id','Kind','Period','Lands','By','Created'].map(h=><th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{history.map(h=><tr key={h.id}><td>{h.id}</td><td>{kindName(h.kind)}</td><td>{h.period}</td><td>{h.sim_date}</td><td>{h.injected_by??'—'}</td><td>{h.created_ids.join(' · ')}</td></tr>)}</tbody></table>:<p className="scenario-empty">Nothing injected yet.</p>}</section>
  </main>
}
