import { useState } from 'react'
import type { Posting, TradePromotionApi } from './api'
import './JournalEntries.css'
const customers = { WMT: 'Walmart', COST: 'Costco', KR: 'Kroger' }
const money = (value: string) => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(Number(value))
const pageSize = 12
const types = [['', 'All entries'], ['accrual', 'Accruals'], ['clearing', 'Clearing'], ['dispute', 'Disputes'], ['restatement', 'Restatements'], ['reversal', 'Reversals']] as const
export default function JournalEntries({ postings, client }: { postings: Posting[]; client: TradePromotionApi }) {
  const [page, setPage] = useState(0)
  const [type, setType] = useState('')
  const shown = type ? postings.filter(p => p.entry_type === type) : postings
  const [selected, setSelected] = useState<Posting>()
  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const currentPage = Math.min(page, Math.max(0, Math.ceil(shown.length / pageSize) - 1))
  const rows = shown.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
  async function explain() {
    if (!selected || busy) return
    setBusy(true); setError('')
    try { const result = await client.explainEntry(selected.id); setEvidence(result.text) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <section className="journal-view" aria-label="Journal entries">
    <header className="journal-heading"><h2>Journal entries</h2><select aria-label="Entry type" value={type} onChange={e=>{setType(e.target.value);setPage(0)}}>{types.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select><button disabled title="Creating journal entries is not supported by the current API." aria-describedby="journal-create-note">New journal entry</button></header>
    <div className="journal-table-scroll"><table className="journal-table"><thead><tr>{['Entry', 'Customer / Program', 'Account', 'Debit', 'Credit', 'Source', 'Status'].map(label=><th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{rows.map(p=><tr key={p.id}><td><button onClick={()=>{setSelected(p);setEvidence('');setError('')}}>{p.id}</button></td><td>{customers[p.customer_id]}{p.program_id&&` · ${p.program_id}`}</td><td className="journal-account">{p.account}</td><td>{money(p.debit)}</td><td>{money(p.credit)}</td><td className="journal-source">{p.entry_type.replaceAll('_',' ')}</td><td><span className="journal-posted">● Posted</span></td></tr>)}</tbody></table>{!postings.length&&<p className="journal-empty">No journal entries for this period.</p>}</div>
    <footer className="journal-footer"><span>{shown.length?`${currentPage*pageSize+1}–${Math.min((currentPage+1)*pageSize,shown.length)} of ${shown.length} journal lines`:'0 journal lines'}</span><div><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</button><button disabled={(currentPage+1)*pageSize>=shown.length} onClick={()=>setPage(currentPage+1)}>Next</button></div></footer>
    <p id="journal-create-note" className="journal-note">Journal creation is not available in the current API. Select an entry to inspect its recorded details.</p>
    {selected&&<section className="journal-details" aria-label="Selected journal entry"><header><h3>{selected.id} · {selected.account}</h3><button disabled={busy} onClick={()=>setSelected(undefined)}>Close details</button></header><dl><div><dt>Journal</dt><dd>{selected.journal_id}</dd></div><div><dt>Recorded at</dt><dd>{selected.decision_time}</dd></div><div><dt>Restates</dt><dd>{selected.restates??'—'}</dd></div><div><dt>Approved by</dt><dd>{selected.approved_by??'—'}</dd></div></dl><p>{selected.memo??'No memo supplied.'}</p><button disabled={busy} onClick={explain}>{busy?'Loading evidence…':'Load evidence chain'}</button>{error&&<p role="alert">{error}</p>}{evidence&&<pre>{evidence}</pre>}</section>}
  </section>
}
