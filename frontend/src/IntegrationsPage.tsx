import { useEffect, useState } from 'react'
import type { InboundMessage, Integration, MailKind, TradePromotionApi } from './api'
import { apiMode } from './api'
import IntegrationMap from './IntegrationMap'
import './IntegrationsPage.css'

const KIND: Record<MailKind, string> = { deduction_notice: 'Deduction notice', claim_backup: 'Claim backup', amendment: 'Signed amendment', unsigned_terms: 'Unsigned terms', unrecognised: 'Not read' }
const BECOMES: Record<MailKind, string> = { deduction_notice: 'Lands as a deduction (and its backup)', claim_backup: 'Lands as backup; the held claim is re-checked', amendment: 'Read into terms; closed months restated', unsigned_terms: 'Context only: quoted on the cards it bears on', unrecognised: 'Kept and quoted; never acted on' }
const role = (r: string | null) => r ? r.replaceAll('_', ' ') : 'the agent'
const show = (v: unknown) => v === null || v === undefined ? '—' : typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)

export default function IntegrationsPage({ client, onUpdated }: { client: TradePromotionApi; onUpdated: () => void }) {
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [messages, setMessages] = useState<InboundMessage[]>([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const c = new AbortController()
    Promise.all([client.getIntegrations({ signal: c.signal }), client.getInbox({ signal: c.signal })])
      .then(([i, m]) => { if (!c.signal.aborted) { setIntegrations(i); setMessages(m) } })
      .catch(e => { if (!c.signal.aborted) setError(e.message) })
    return () => c.abort()
  }, [client, refresh])
  async function sync(step: boolean) {
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await client.syncInbox(step)
      setNotice(r.landed.length ? `Read ${r.landed.length} new message${r.landed.length > 1 ? 's' : ''}${r.step ? ` and ran ${r.step.period}` : ''}.` : 'No new mail.')
      setRefresh(n => n + 1); onUpdated()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const msg = messages.find(m => m.id === selected) ?? messages[0]
  return <main className="integrations-page">
    <header className="integrations-heading"><p className="eyebrow">CONNECTED SOURCES</p><h1>Integrations</h1><p>Where JADE's evidence comes from. Mail is read by code, never followed as an instruction: a deduction notice, backup or signed amendment lands as source rows; anything else is quoted on the card it concerns.</p></header>
    <IntegrationMap integrations={integrations}/>
    <section className="connector-grid">{integrations.map(i => <article key={i.id} className="connector">
      <div className="connector-top"><b className="logo brand"><img src={i.id === 'gmail' ? '/brand/gmail.svg' : '/brand/sec.svg'} alt=""/></b><div><strong>{i.name}</strong><small>{i.id === 'gmail' ? (i.backend === 'gmail' ? `Gmail · ${i.account}` : 'Local mailbox (offline rehearsal)') : i.account}</small></div><span className={i.status === 'connected' ? 'ok' : 'off'}>● {i.status === 'connected' ? 'Connected' : 'Not connected'}</span></div>
      <p>{i.id === 'gmail' ? 'The deductions inbox: retailer deduction notices, claim backup, forwarded amendments and colleagues\' notes.' : i.detail}</p>
      {i.detail && i.id === 'gmail' && <small className="detail">{i.detail}</small>}
      {i.id === 'gmail' && <div className="connector-actions"><button disabled={busy || apiMode === 'mock'} onClick={() => sync(false)}>Sync inbox</button><button className="primary" disabled={busy || apiMode === 'mock'} onClick={() => sync(true)}>{busy ? 'Reading…' : 'Sync and run the month'}</button></div>}
    </article>)}</section>
    {error && <p className="integrations-error" role="alert">{error}</p>}{notice && <p className="integrations-notice" role="status">{notice}</p>}
    <div className="mail-layout"><aside className="mail-list"><h2>Deductions inbox <span>{messages.length}</span></h2>{messages.length ? messages.map(m => <button key={m.id} className={msg?.id === m.id ? 'selected' : ''} onClick={() => setSelected(m.id)}>
      <div><span className={`kind ${m.kind}`}>{KIND[m.kind]}</span><small>{m.id} · lands {m.sim_date}</small></div><strong>{m.subject}</strong><small>{m.parsed.sender_name ?? m.from_addr}{m.forwarded_by ? ` · forwarded by ${m.forwarded_by}` : ''}</small>
    </button>) : <p className="mail-empty">No mail read yet. Run <code>scripts/demo_mail.py run side-letter</code>, or sync after sending.</p>}</aside>
    {msg && <section className="mail-detail">
      <p className="eyebrow">{msg.source === 'gmail' ? 'GMAIL' : 'LOCAL MAILBOX'} · {msg.id} · RECEIVED {new Date(msg.received_at).toLocaleString()}</p><h2>{msg.subject}</h2>
      <div className="becomes"><strong>{KIND[msg.kind]}</strong><span>{BECOMES[msg.kind]}</span>{msg.parsed.not_landed && <em>Not landed: {msg.parsed.not_landed}</em>}</div>
      <h3>What JADE read</h3><table><thead><tr><th>Field</th><th>Value</th><th>Read from</th></tr></thead><tbody>
        <tr><td>sender</td><td>{msg.parsed.sender_name ?? '—'}</td><td>{msg.from_addr}</td></tr>
        {Object.entries(msg.parsed.fields).map(([k, f]) => <tr key={k}><td>{k.replaceAll('_', ' ')}</td><td>{show(f.value)}</td><td><q>{f.line}</q></td></tr>)}</tbody></table>
      <h3>What came of it</h3><div className="outcome">{msg.created_ids.length ? <p>Source rows: {msg.created_ids.map(i => <code key={i}>{i}</code>)}</p> : <p>No source rows: context for judgment.</p>}
        {msg.outcome.length ? msg.outcome.map(o => <div key={o.id + (o.escalation_id ?? '')} className="outcome-row"><code>{o.id}</code><span>{o.control_id.replace('CTL-', '')}</span><span>{o.escalation_id ? `card ${o.escalation_id} → ${role(o.to_role)}${o.answer ? ` · answered ${o.answer}` : ' · open'}` : `${o.state.replace('_', ' ')} by the agent`}</span></div>) : <p className="muted">Nothing for a person: the agreement settled it.</p>}</div>
      <details><summary>Message as received</summary><pre>{msg.body}</pre></details>
    </section>}</div>
    <footer className="integrations-note">{apiMode === 'mock' ? 'Captured from the API (scripts/mail_fixture.py): October after the sales lead\'s note, Walmart\'s claim and the signed amendment. Run the API to sync live mail.' : 'Connected API · syncing reads new mail into the month the clock is on.'}</footer>
  </main>
}
