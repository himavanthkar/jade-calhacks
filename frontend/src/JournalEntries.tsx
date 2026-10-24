import { useState } from 'react'
import type { Posting, TradePromotionApi } from './api'
import './JournalEntries.css'
const customers = { WMT: 'Walmart', COST: 'Costco', KR: 'Kroger' }
const money = (value: string) => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(Number(value))
const pageSize = 12
export default function JournalEntries({ postings, client }: { postings: Posting[]; client: TradePromotionApi }) {
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Posting>()
  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const currentPage = Math.min(page, Math.max(0, Math.ceil(postings.length / pageSize) - 1))
  const rows = postings.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
  async function explain() {
    if (!selected || busy) return
    setBusy(true); setError('')
    try { const result = await client.explainEntry(selected.id); setEvidence(result.text) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <section className="journal-view" aria-label="Journal entries">
    <header className="journal-heading"><h2>Journal entries</h2><button disabled title="Creating journal entries is not supported by the current API." aria-describedby="journal-create-note">New journal entry</button></header>
    <div className="journal-table-scroll"><table className="journal-table"><thead><tr>{['Entry', 'Customer / Program', 'Period', 'Debit', 'Credit', 'Source', 'Status'].map(label=><th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{rows.map(p=><tr key={p.id}><td><button onClick={()=>{setSelected(p);setEvidence('');setError('')}}>{p.id}</button></td><td>{customers[p.customer_id]}{p.program_id&&` · ${p.program_id}`}</td><td>{p.period}</td><td>{money(p.debit)}</td><td>{money(p.credit)}</td><td className="journal-source">{p.entry_type.replaceAll('_',' ')}</td><td><span className="journal-posted">● Posted</span></td></tr>)}</tbody></table>{!postings.length&&<p className="journal-empty">No journal entries for this period.</p>}</div>
    <footer className="journal-footer"><span>{postings.length?`${currentPage*pageSize+1}–${Math.min((currentPage+1)*pageSize,postings.length)} of ${postings.length} journal lines`:'0 journal lines'}</span><div><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</button><button disabled={(currentPage+1)*pageSize>=postings.length} onClick={()=>setPage(currentPage+1)}>Next</button></div></footer>
    <p id="journal-create-note" className="journal-note">Journal creation is not available in the current API. Select an entry to inspect its recorded details.</p>
    {selected&&<section className="journal-details" aria-label="Selected journal entry"><header><h3>{selected.id} · {selected.account}</h3><button disabled={busy} onClick={()=>setSelected(undefined)}>Close details</button></header><dl><div><dt>Journal</dt><dd>{selected.journal_id}</dd></div><div><dt>Recorded at</dt><dd>{selected.decision_time}</dd></div><div><dt>Restates</dt><dd>{selected.restates??'—'}</dd></div><div><dt>Approved by</dt><dd>{selected.approved_by??'—'}</dd></div></dl><p>{selected.memo??'No memo supplied.'}</p><button disabled={busy} onClick={explain}>{busy?'Loading evidence…':'Load evidence chain'}</button>{error&&<p role="alert">{error}</p>}{evidence&&<pre>{evidence}</pre>}</section>}
  </section>
}
