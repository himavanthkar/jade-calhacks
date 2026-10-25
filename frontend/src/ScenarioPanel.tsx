import { useEffect, useState } from 'react'
import type { Clock, Evidence, InjectResult, Injection, ScenarioExample, ScenarioKind, TradePromotionApi } from './api'
import { ACTORS, apiMode } from './api'
import ErrorNotice from './ErrorNotice'
import './ScenarioPanel.css'

const kinds: {id:ScenarioKind;name:string;template:Evidence}[]=[
  {id:'deduction',name:'Short payment',template:{customer_id:'WMT',program_id:'TP-0214',amount:'25000.00',day:3}},
  {id:'duplicate',name:'Same claim twice',template:{deduction_id:'DD-',day:8}},
  {id:'backup',name:'Claim paperwork arrives',template:{deduction_id:'DD-',scan_units:10000,scan_rate:'3.80',proof_of_performance:false,day:4}},
  {id:'return',name:'Product sent back',template:{shipment_id:'SH-',cases:500,day:10}},
  {id:'amendment',name:'Contract rate changes',template:{program_id:'TP-0214',new_rate:'4.00',effective_date:'2026-01-01',day:12}},
  {id:'approval_attempt',name:'Someone approves their own deal',template:{actor_id:'sales.walmart',target_type:'deduction',target_id:'DD-',day:9}},
  {id:'handoff',name:'Colleague hands work over',template:{from_actor:'deductions.human',deduction_id:'DD-',proposed_decision:'clear',done:'',left_to_do:'',day:4}},
]
const kindName=(k:string)=>kinds.find(x=>x.id===k)?.name??k
const human=(v:string)=>v.replaceAll('_',' ')
const CUSTOMERS:Record<string,string>={WMT:'Walmart',COST:'Costco',KR:'Kroger'}

/** One plain field per payload key: the page builds the payload, nobody types JSON. */
type Field={label:string;type?:'number'|'date'|'select'|'checkbox'|'long';options?:[string,string][];hint?:string}
const PEOPLE:[string,string][]=[['deductions.human','Deduction analyst'],['tpa.human','Trade promotion accountant'],...ACTORS.map(a=>[a.id,a.name] as [string,string])]
const FIELDS:Record<string,Field>={
  customer_id:{label:'Customer',type:'select',options:Object.entries(CUSTOMERS)},
  program_id:{label:'Promotion it cites',hint:'TP-0214'},
  amount:{label:'Amount taken ($)',type:'number'},
  claimed_period:{label:'Month it claims',hint:'2026-10'},
  claimed_rate:{label:'Rate it claims ($ a case)',type:'number'},
  deduction_id:{label:'Which deduction',hint:'DD-0242'},
  scan_units:{label:'Units scanned',type:'number'},
  scan_rate:{label:'Rate on the paperwork ($ a case)',type:'number'},
  proof_of_performance:{label:'Proof of performance attached',type:'checkbox'},
  shipment_id:{label:'Which shipment',hint:'SH-00834'},
  cases:{label:'Cases sent back',type:'number'},
  new_rate:{label:'New rate ($ a case)',type:'number'},
  effective_date:{label:'Effective from',type:'date'},
  actor_id:{label:'Who tries to approve',type:'select',options:ACTORS.map(a=>[a.id,a.name])},
  target_type:{label:'What they approve',type:'select',options:[['deduction','A deduction'],['restatement','A restatement']]},
  target_id:{label:'Which one',hint:'DD-0216'},
  from_actor:{label:'Handed over by',type:'select',options:PEOPLE},
  proposed_program_id:{label:'Promotion they matched it to',hint:'TP-0222'},
  proposed_decision:{label:'What they proposed',type:'select',options:[['clear','Pay it'],['dispute','Dispute it']]},
  done:{label:'What they already did',type:'long'},
  left_to_do:{label:'What is left to do',type:'long'},
  day:{label:'Day of the month it arrives',type:'number'},
}
const WHOLE=new Set(['day','cases','scan_units'])
/** What the engine did, in words: a finding's state for a reader who has never seen a control id. */
function outcome(f:{state:string;escalation_type:string|null}){
  if(f.escalation_type==='sod')return 'Blocked: nobody approves their own deal'
  if(f.state==='auto_resolved')return 'Handled by JADE on its own'
  if(f.state==='escalated'||f.state==='open')return 'Sent to a person to decide'
  return 'Resolved'
}
const PERIOD_STATE:Record<string,string>={ESCALATED:'waiting on a person',REVIEWED:'ready to sign',BLOCKED:'blocked by a check',CONTROLLED:'checked',SIGNED:'signed',CLOSED:'closed',ACCRUED:'in progress',OPEN:'open',RESTATED:'restated'}

export default function ScenarioPanel({client,onUpdated,onNavigate}:{client:TradePromotionApi;onUpdated:()=>void;onNavigate:(view:string)=>void}) {
  const [clock,setClock]=useState<Clock>()
  const [examples,setExamples]=useState<ScenarioExample[]>([])
  const [history,setHistory]=useState<Injection[]>([])
  const [chosen,setChosen]=useState('')
  const [kind,setKind]=useState<ScenarioKind>('deduction')
  const [values,setValues]=useState<Evidence>(kinds[0].template)
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
  const parsed:Evidence=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,WHOLE.has(k)&&v!==''?Number(v):v]))
  const set=(k:string,v:string|boolean)=>setValues(x=>({...x,[k]:v}))
  function pick(e:ScenarioExample){setChosen(e.title);setKind(e.kind);setValues(e.payload);setResult(undefined);setError(undefined)}
  function pickKind(k:ScenarioKind){setChosen('');setKind(k);setValues(kinds.find(x=>x.id===k)!.template);setResult(undefined);setError(undefined)}
  async function inject(step:boolean){
    if(busy)return
    setBusy(true);setError(undefined);setResult(undefined)
    try{setResult(await client.injectScenario(kind,parsed,{step,injectedBy:by.trim()||undefined}));onUpdated()}
    catch(e){setError(e)}
    finally{setBusy(false);setRefresh(n=>n+1)}
  }
  const escalated=result?.findings?.filter(f=>f.state==='escalated'||f.state==='open')??[]
  return <main className="scenario-page"><header className="scenario-heading"><p className="eyebrow">JUDGE INPUT</p><h1>Live Scenario</h1><div><p>Give JADE a situation of your own. It arrives in the current month, and JADE handles it exactly like everything else it sees.</p><span>{clock?`● Lands in ${clock.current_period} · sim date ${clock.sim_date}`:loading?'Loading clock…':'● Clock unavailable'}</span></div></header>
    {apiMode==='mock'&&<p className="scenario-note">Mock mode: you can browse and edit the examples, but injecting needs the engine. Run <code>make api</code> and set <code>VITE_API_MODE=http</code>.</p>}
    <div className="scenario-layout"><aside className="scenario-examples"><h2>Ready-made, against the books as they stand</h2>{loading?<p role="status">Loading examples…</p>:examples.length?examples.map(e=><button key={e.title} className={chosen===e.title?'selected':''} aria-pressed={chosen===e.title} onClick={()=>pick(e)}><small>{kindName(e.kind)}</small><strong>{e.title}</strong></button>):<p className="scenario-empty">No examples for this month.</p>}
      <h2>Or write your own</h2><div className="scenario-kinds">{kinds.map(k=><button key={k.id} className={!chosen&&kind===k.id?'selected':''} onClick={()=>pickKind(k.id)}>{k.name}</button>)}</div></aside>
      <section className="scenario-editor"><header><div><p className="eyebrow">{kindName(kind).toUpperCase()}</p><h2>{chosen||`Custom ${kindName(kind).toLowerCase()}`}</h2></div><label>Injected by <input value={by} onChange={e=>setBy(e.target.value)} placeholder="judge"/></label></header>
        <div className="scenario-form">{Object.entries(values).map(([k,v])=>{
          if(v!==null&&typeof v==='object')return <p key={k} className="scenario-attached">Includes {human(k)}</p>
          const f=FIELDS[k]??{label:human(k)}
          if(f.type==='checkbox')return <label key={k} className="check"><input type="checkbox" checked={Boolean(v)} onChange={e=>set(k,e.target.checked)} disabled={busy}/>{f.label}</label>
          return <label key={k} className={f.type==='long'?'wide':''}>{f.label}
            {f.type==='select'?<select value={String(v??'')} onChange={e=>set(k,e.target.value)} disabled={busy}>{(f.options??[]).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
             :f.type==='long'?<textarea value={String(v??'')} onChange={e=>set(k,e.target.value)} disabled={busy}/>
             :<input type={f.type==='date'?'date':'text'} inputMode={f.type==='number'?'decimal':undefined} value={String(v??'')} placeholder={f.hint} onChange={e=>set(k,e.target.value)} disabled={busy}/>}</label>})}
        </div>
        <div className="scenario-actions"><button disabled={busy} onClick={()=>void inject(false)}>Add to {clock?.current_period??'month'}</button><button className="run" disabled={busy} onClick={()=>void inject(true)}>{busy?'Running…':`Add & run ${clock?.current_period??'month'}`}</button></div>
        <ErrorNotice error={error} onRetry={()=>{setError(undefined);setRefresh(n=>n+1)}} retryLabel="Reload"/>
        {result&&<section className="scenario-result" aria-live="polite"><header><p className="eyebrow">{result.id} · LANDED {result.lands_on}</p><h3>{result.step?`${result.period} ran with your scenario`:`Added to ${result.period}. Run the month to see what JADE does.`}</h3></header>
          {result.note&&<p className="scenario-attached">{result.note}</p>}
          <p className="scenario-ids">Created: {result.created_ids.map(id=><code key={id}>{id}</code>)}</p>
          {result.step&&<><div className="scenario-states">{Object.entries(result.step.states).map(([c,s])=><span key={c} className={s==='BLOCKED'?'blocked':''}>{CUSTOMERS[c]??c} · {PERIOD_STATE[s]??human(s.toLowerCase())}</span>)}</div>
            <h4>What it did with them</h4>{result.findings?.length?<ul className="scenario-findings">{result.findings.map(f=><li key={f.id} className={f.escalation_type==='sod'?'sod':''}><div><strong>{outcome(f)}</strong><small>{f.control_name??human(f.control_id.replace('CTL-','').toLowerCase())} · {CUSTOMERS[f.customer_id]??f.customer_id}{f.amount&&` · $${Math.abs(Number(f.amount)).toLocaleString('en-US',{minimumFractionDigits:2})}`} · {f.id}</small></div><p>{String(f.evidence.summary??'')}</p></li>)}</ul>:<p className="scenario-empty">{result.step.log.some(l=>result.created_ids.some(id=>l.startsWith(id))&&l.includes('unmatched'))?'Held as pending: JADE could not match it to a promotion, so nothing is paid out and the customer still owes the money until it can.':'Nothing needed a person: it passed every check and was settled on its own.'}</p>}
            {escalated.length>0&&<button onClick={()=>onNavigate('Escalation Inbox')}>Open the {escalated.length} card{escalated.length===1?'':'s'} in the inbox ›</button>}
            <details><summary>Run log ({result.step.log.length})</summary><pre>{result.step.log.join('\n')}</pre></details></>}
        </section>}
      </section></div>
    <section className="scenario-history"><h2>Injected so far · {history.length}</h2>{history.length?<table><thead><tr>{['Id','Kind','Period','Lands','By','Created'].map(h=><th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{history.map(h=><tr key={h.id}><td>{h.id}</td><td>{kindName(h.kind)}</td><td>{h.period}</td><td>{h.sim_date}</td><td>{h.injected_by??'—'}</td><td>{h.created_ids.join(' · ')}</td></tr>)}</tbody></table>:<p className="scenario-empty">Nothing injected yet.</p>}</section>
  </main>
}
