import './App.css'

function App() {
  return (
    <main className="workspace">
      <header className="page-header">
        <div><h1>Trade Promotion</h1><p>General Mills</p></div>
        <span className="status">Wireframe · Not connected</span>
      </header>

      <section className="panel" aria-labelledby="period-title">
        <div className="panel-heading"><h2 id="period-title">01 / Month & Period</h2><span>Period: —</span></div>
        <div className="toolbar"><button disabled aria-label="Previous month">←</button><span>Select month</span><button disabled aria-label="Next month">→</button><button disabled>Step month</button></div>
        <div className="summary-grid">
          {['Period status', 'Findings', 'Verification gates', 'Performance metrics'].map(label => <div className="placeholder" key={label}><span>{label}</span><strong>—</strong></div>)}
        </div>
        <div className="placeholder wide">Journal entries / Restatement comparison / Flux & close review</div>
      </section>

      <div className="content-grid">
        <section className="panel" aria-labelledby="controls-title">
          <h2 id="controls-title">02 / Controls Library</h2>
          <div className="table-scroll"><table><thead><tr>{['Rule', 'Threshold', 'Owner', 'Precedent', 'Fired'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody><tr><td colSpan={5}>Controls and supporting records will appear here.</td></tr></tbody></table></div>
        </section>
        <section className="panel" aria-labelledby="inbox-title">
          <h2 id="inbox-title">03 / Escalation Inbox</h2>
          <div className="placeholder wide">Question · Evidence · Decision options</div>
          <p className="hint">Review requests and saved decisions will appear here.</p>
        </section>
      </div>

      <section className="panel" aria-labelledby="explain-title">
        <h2 id="explain-title">04 / Interrogation</h2>
        <label htmlFor="question">Ask why a decision was made</label>
        <div className="question-row"><input id="question" placeholder="Ask it why it did anything." disabled /><button disabled>Ask</button></div>
        <div className="placeholder wide">Explanation / Evidence chain / Then vs now</div>
      </section>
      <footer>Layout placeholder only. Controls are disabled; no transactions or API requests are executed.</footer>
    </main>
  )
}

export default App
