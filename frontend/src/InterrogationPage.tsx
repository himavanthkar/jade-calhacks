import { useEffect, useRef, useState } from 'react'
import type { AskResponse, TradePromotionApi } from './api'
import { apiMode } from './api'
import './InterrogationPage.css'
const suggestions = ['Why did you post JE-1058?', 'What did it know in March?']
const icon = (id: number) => <img src={`/figma/interrogation/icon${id}.svg`} alt="" />
export default function InterrogationPage({client}:{client:TradePromotionApi}) {
  const [question,setQuestion] = useState(suggestions[0])
  const [answer,setAnswer] = useState<AskResponse>()
  const [busy,setBusy] = useState(true)
  const [error,setError] = useState('')
  const [selected,setSelected] = useState<number|null>(null)
  const request = useRef<AbortController|null>(null)
  useEffect(()=>{
    const controller=new AbortController();request.current=controller
    client.ask(suggestions[0],{signal:controller.signal}).then(result=>{if(!controller.signal.aborted)setAnswer(result)}).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(!controller.signal.aborted)setBusy(false)})
    return ()=>request.current?.abort()
  },[client])
  async function ask(value:string) {
    if(!value.trim()||busy)return
    request.current?.abort();const controller=new AbortController();request.current=controller
    setQuestion(value);setBusy(true);setError('');setSelected(null)
    try{const result=await client.ask(value.trim(),{signal:controller.signal});if(!controller.signal.aborted)setAnswer(result)}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e))}finally{if(!controller.signal.aborted)setBusy(false)}
  }
  const steps=answer?.chains.flatMap(chain=>chain.steps.map(step=>({...step,entry:chain.entry_id})))??[]
  const thenSteps=steps.filter(s=>['rule','terms','inputs','knew-at'].includes(s.label))
  const nowSteps=steps.filter(s=>['restated','reversed','precedent'].includes(s.label))
  const integrity=steps.filter(s=>['knew-at','signed','restated'].includes(s.label))
  const active=selected===null?undefined:steps[selected]
  return <main className="interrogation-page"><header className="interrogation-heading"><p className="eyebrow">EXPLAINABILITY &amp; AUDIT</p><h1>Interrogation</h1><div><p>Ask why the system did anything, with every answer traced to source evidence.</p><span>{steps.length?'● Evidence linked':'● Awaiting evidence'}</span></div></header>
  <div className="interrogation-layout"><section className="interrogation-conversation"><form className="interrogation-form" onSubmit={e=>{e.preventDefault();void ask(question)}}><span className="ai-square">{icon(4)}</span><div><label htmlFor="audit-question">Ask it why it did anything</label><div className="ask-row"><textarea id="audit-question" value={question} onChange={e=>setQuestion(e.target.value)} rows={2} placeholder="Ask about an entry, a decision or a month…"/><button disabled={busy||!question.trim()}>{busy?'Asking…':'Ask AI'}</button></div><div className="question-suggestions"><span>Try:</span>{suggestions.map(q=><button key={q} type="button" disabled={busy} onClick={()=>void ask(q)}>{q}</button>)}</div></div></form>
  {error&&<p className="interrogation-error" role="alert">{error} <button disabled={busy} onClick={()=>void ask(question)}>Retry</button></p>}
  <div className="answer-area" aria-live="polite" aria-busy={busy}><header className="answer-heading"><span className="ai-square">{icon(5)}</span><div><strong>JADE AI</strong><small>{answer?`${steps.length} evidence steps · ${apiMode==='mock'?'Captured backend response':`Drafted by ${answer.drafted_by}`}`:'Loading response…'}</small></div><span>{steps.length?'● Traceable':'No chain supplied'}</span></header>
  {answer&&<><p className="answered-question">{answer.question}</p><h2 className="answer-lede">{answer.answer.split('\n')[0]}</h2>{answer.chains.length>0?<><div className="decision-comparison"><section><p className="comparison-label">THEN · ORIGINAL DECISION</p><h3>{answer.chains[0].head}</h3>{thenSteps.map((s,i)=><div className="decision-fact" key={`${s.entry}-${i}`}><strong>{s.label.replaceAll('-',' ')}</strong><p>{s.text}</p></div>)}</section><section><p className="comparison-label">LATER · RECORDED CHANGES</p><h3>{nowSteps.length?'Subsequent evidence & entries':'No later changes supplied'}</h3>{nowSteps.map((s,i)=><div className="decision-fact" key={`${s.entry}-${i}`}><strong>{s.label}</strong><p>{s.text}</p>{s.ids.map(id=><button key={id} onClick={()=>setSelected(steps.indexOf(s))}>{id}</button>)}</div>)}</section></div><section className="decision-note">{icon(6)}<div><h3>Decision context</h3>{answer.chains.map(c=><p key={c.entry_id}>{c.memo??c.head}</p>)}</div></section></>:<p className="interrogation-empty">No supporting chain was returned. Try one of the captured questions above or include an entry ID.</p>}
  <details className="full-response"><summary>Full API answer</summary><pre>{answer.answer}</pre>{answer.knowledge&&<pre>{JSON.stringify(answer.knowledge,null,2)}</pre>}</details></>}
  </div></section><aside className="interrogation-evidence"><section><header><h2>Evidence Chain</h2><span>● {steps.length} steps</span></header>{steps.length?<ol className="evidence-timeline">{steps.map((s,i)=><li key={`${s.entry}-${i}`}><button aria-expanded={selected===i} onClick={()=>setSelected(selected===i?null:i)}><span className={s.label==='restated'?'changed':''}>{i+1}</span><div><strong>{s.label.replaceAll('-',' ')}</strong><small>{s.ids.length?s.ids.join(' · '):s.entry}</small></div></button>{selected===i&&<p className="evidence-step-detail">{s.text}</p>}</li>)}</ol>:<p className="interrogation-empty">Evidence appears here when the API returns a chain.</p>}</section><section className="integrity-section"><header><h2>Decision integrity</h2></header>{integrity.map((s,i)=><article key={`${s.entry}-${i}`}>{icon(7)}<div><strong>{s.label==='knew-at'?'Knowledge at decision time':s.label==='signed'?'Recorded sign-off':'Linked restatement'}</strong><p>{s.text}</p></div></article>)}</section>{active&&<div className="source-selection" role="status">Selected evidence: {active.entry} · {active.label}</div>}</aside></div>
  </main>
}
