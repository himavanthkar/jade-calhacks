import { useEffect, useState, type ReactNode } from 'react'
import type { Backtest, Metrics, TradePromotionApi } from './api'
import { apiMode } from './api'
import './BacktestPage.css'

// Two categorical slots, validated together (orange #E86F31 ↔ blue #2a78d6: CVD ΔE 25, contrast ≥ 3:1).
// Orange is JADE and its estimates; blue is what General Mills reported. Text never wears either.
const pct = (v: string | number, d = 1) => `${(Number(v) * 100).toFixed(d)}%`
const musd = (v: string | number) => `$${Math.round(Number(v)).toLocaleString('en-US')}M`
type Tip = { x: number; y: number; text: string } | null

function Chart({ title, sub, children, means, table, tip, legend }: { title: string; sub: string; children: ReactNode; means: ReactNode; table: ReactNode; tip: Tip; legend?: ReactNode }) {
  return <section className="bt-card">
    <header><h2>{title}</h2><p>{sub}</p>{legend && <div className="bt-legend">{legend}</div>}</header>
    <div className="bt-plot">{children}{tip && <div className="bt-tip" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>{tip.text}</div>}</div>
    <div className="bt-means"><strong>What it means</strong><p>{means}</p></div>
    <details className="bt-table"><summary>Show the numbers</summary>{table}</details>
  </section>
}
const Key = ({ kind, label }: { kind: 'real' | 'jade' | 'aqua' | 'band' | 'wide'; label: string }) => <span className="bt-key"><span className={`key key-${kind}`}/>{label}</span>

export default function BacktestPage({ client }: { client: TradePromotionApi }) {
  const [bt, setBt] = useState<Backtest>()
  const [series, setSeries] = useState<Metrics[]>([])
  const [error, setError] = useState('')
  const [seriesError, setSeriesError] = useState('')
  const [tips, setTips] = useState<Record<string, Tip>>({})
  const tip = (chart: string, t: Tip) => setTips(s => ({ ...s, [chart]: t }))
  useEffect(() => {
    const c = new AbortController()
    client.getBacktest({ signal: c.signal }).then(setBt).catch(e => { if (!c.signal.aborted) setError(e.message) })
    client.getMetricsSeries({ signal: c.signal }).then(setSeries).catch(e => { if (!c.signal.aborted) setSeriesError(e.message) })   // needs a played year
    return () => c.abort()
  }, [client])
  if (error) return <main className="backtest-page"><p className="bt-error" role="alert">{error}</p></main>
  if (!bt) return <main className="backtest-page"><p role="status">Loading the 10-K backtest…</p></main>

  // ── chart 1: sixteen year ends, and the review ranges around the last ──────────────────
  const years = bt.history.years
  const W = 640, H = 260, L = 44, R = 16, T = 16, B = 30
  const yMax = 0.045
  const x1 = (i: number) => L + i * (W - L - R) / (years.length - 1)
  const y1 = (v: number) => T + (1 - v / yMax) * (H - T - B)
  const prior = Number(years[years.length - 2].ratio), policy = Number(bt.policy_tolerance), quiet = Number(bt.history.quiet_tolerance)
  const last = years.length - 1
  const worst = years.reduce((a, y, i) => (i && Math.abs(Number(y.drift)) > Math.abs(Number(years[a].drift ?? 0)) ? i : a), 1)
  const band = (tol: number) => ({ top: y1(Math.min(prior * (1 + tol), yMax)), bottom: y1(prior * (1 - tol)) })
  const wide = band(policy), tight = band(quiet)

  // ── chart 2: the estimate at each close against what was reported ───────────────────────
  const closes = bt.closes
  const lo = 350, hi = 560
  const x2 = (i: number) => L + 40 + i * (W - L - R - 80) / (closes.length - 1)
  const y2 = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
  const best = bt.best, s = bt.scores[best]

  // ── chart 3: trade expense timing ───────────────────────────────────────────────────────
  const timing = bt.trade_timing
  const tMax = 14
  const x3 = (i: number) => L + 60 + i * 150
  const y3 = (v: number) => T + (1 - (v + tMax) / (2 * tMax)) * (H - T - B)

  // ── chart 4: the played year, who decided each finding ──────────────────────────────────
  const months = series.map(m => ({ as_of: m.as_of ?? '', found: m.counts?.findings_this_month ?? 0, asked: m.counts?.escalated_this_month ?? 0,
    repeats: m.judgment?.repeat_findings ?? 0, settled: m.judgment?.settled_by_precedent ?? 0 }))
  const fMax = Math.max(16, ...months.map(m => m.found))
  const bw = 22
  const x4 = (i: number) => L + 14 + i * (W - L - R - 28) / Math.max(months.length - 1, 1)
  const y4 = (v: number) => T + (1 - v / fMax) * (H - T - B)
  const end = months[months.length - 1]

  return <main className="backtest-page">
    <header className="bt-heading"><p className="eyebrow">REAL DATA · GENERAL MILLS 10-K FILINGS, FY2011–FY2026</p><h1>Backtest</h1>
      <p>Transaction-level trade data is never public, so deduction matching is scored on the simulation's answer key. What can be tested on real books is the part General Mills itself calls a critical accounting estimate: the trade promotion liability at each year end, and the close's checks on it. Every number on this page is quoted from a filing, walked forward so no close sees its own 10-K.</p></header>

    <section className="bt-tiles">
      <article><small>Accrued trade &amp; coupon promotions, FY2026</small><strong>{musd(closes[closes.length - 1].actual_musd)}</strong><span>{pct(closes[closes.length - 1].ratio, 2)} of net sales · a named critical estimate</span></article>
      <article><small>Largest year-on-year swing, 16 years</small><strong>{pct(bt.history.largest_drift)}</strong><span>FY{years[worst].fiscal_year} · audited, not an error</span></article>
      <article><small>Best estimate at the close</small><strong>{pct(s.mape)}</strong><span>mean error, {best === 'naive' ? 'carry last year forward' : best.replace('_', ' ')}, 6 closes</span></article>
      <article><small>Played year: repeats settled by precedent</small><strong>{end ? `${end.settled} of ${end.repeats}` : '—'}</strong><span>{end ? 'simulation · asked once, reused' : 'run a year to see it'}</span></article>
    </section>

    <div className="bt-grid">
      <Chart title="How far the liability moves on its own" sub="Accrued trade and consumer promotions as a share of net sales, each fiscal year end"
        tip={tips.history} legend={<><Key kind="real" label="Reported ratio"/><Key kind="wide" label={`Review range today (±${pct(policy, 0)})`}/><Key kind="band" label={`Calibrated range (±${pct(quiet, 0)})`}/></>}
        means={<>Audited books moved as much as {pct(bt.history.largest_drift)} in a year and {pct(bt.history.mean_abs_drift)} on average. A review range of ±{pct(policy, 0)} can't fail: on $493M it lets ±$246M through. Set from this history (±{pct(quiet, 0)}, the widest real swing), it stays quiet on every audited year and would flag anything wider. Company-level review is a backstop for big misses; a forgotten amendment (about 9% of the liability in the simulation) is caught program by program, where JADE looks. The tolerance is company policy, not GAAP: this is the evidence for choosing it.</>}
        table={<table><thead><tr><th>FY</th><th>Liability</th><th>Net sales</th><th>Ratio</th><th>Change</th></tr></thead><tbody>{years.map(y => <tr key={y.fiscal_year}><td>{y.fiscal_year}</td><td>{musd(y.liability_musd)}</td><td>{musd(y.net_sales_musd)}</td><td>{pct(y.ratio, 2)}</td><td>{y.drift ? pct(y.drift) : '—'}</td></tr>)}</tbody></table>}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Line chart of the trade promotion liability as a share of net sales, FY2011 to FY2026, with review ranges">
          {[0, 0.01, 0.02, 0.03, 0.04].map(v => <g key={v}><line className="grid" x1={L} x2={W - R} y1={y1(v)} y2={y1(v)}/><text className="tick" x={L - 6} y={y1(v) + 3} textAnchor="end">{pct(v, 0)}</text></g>)}
          <rect className="band-wide" x={x1(last) - 18} width="36" y={wide.top} height={wide.bottom - wide.top} rx="4"/>
          <rect className="band-tight" x={x1(last) - 10} width="20" y={tight.top} height={tight.bottom - tight.top} rx="4"/>
          <polyline className="line-real" points={years.map((y, i) => `${x1(i)},${y1(Number(y.ratio))}`).join(' ')}/>
          {years.map((y, i) => <g key={y.fiscal_year}>
            <circle className={`dot-real ${i === worst || i === last ? '' : 'quiet'}`} cx={x1(i)} cy={y1(Number(y.ratio))} r="4"/>
            <rect className="hit" x={x1(i) - 14} y={T} width="28" height={H - T - B} onMouseEnter={() => tip('history', { x: x1(i) / W * 100, y: y1(Number(y.ratio)) / H * 100, text: `FY${y.fiscal_year}: ${pct(y.ratio, 2)} of net sales (${musd(y.liability_musd)})${y.drift ? `, ${Number(y.drift) > 0 ? '+' : ''}${pct(y.drift)} on the year` : ''}` })} onMouseLeave={() => tip('history', null)}/>
            {i % 3 === 0 || i === last ? <text className="tick" x={x1(i)} y={H - 10} textAnchor="middle">FY{String(y.fiscal_year).slice(2)}</text> : null}
          </g>)}
          <text className="note" x={x1(worst)} y={y1(Number(years[worst].ratio)) + 18} textAnchor="middle">{pct(years[worst].drift ?? 0)} in FY{String(years[worst].fiscal_year).slice(2)}</text>
          <text className="note" x={x1(last) - 22} y={wide.top + 10} textAnchor="end">±{pct(policy, 0)}</text>
          <text className="note" x={x1(last) - 22} y={tight.top + 10} textAnchor="end">±{pct(quiet, 0)}</text>
        </svg>
      </Chart>

      <Chart title="The estimate at each close, against the 10-K" sub="Accrued trade and coupon promotion liabilities, $M · estimated before the year's 10-K was public"
        tip={tips.closes} legend={<><Key kind="real" label="Reported in the 10-K"/><Key kind="jade" label="Carry-forward estimate"/></>}
        means={<>The simplest estimate, last year's balance, misses by {pct(s.mape)} on average and by {pct(s.worst)} in its worst year, while scaling by net sales does worse ({pct(bt.scores.annual_ratio.mape)}). The year-end balance isn't explained by sales alone: it depends on which programs are running and how late retailers claim. That is why JADE accrues program by program on shipment, at each agreement's own rate, and trues up from the claims, instead of plugging a top-down ratio.</>}
        table={<table><thead><tr><th>FY</th><th>Reported</th>{Object.keys(bt.scores).map(k => <th key={k}>{k.replace('_', ' ')}</th>)}<th>Review flag</th></tr></thead><tbody>{closes.map(c => <tr key={c.fiscal_year}><td>{c.fiscal_year}</td><td>{musd(c.actual_musd)}</td>{Object.keys(bt.scores).map(k => <td key={k}>{musd(c.estimates_musd[k])}</td>)}<td>{c.review_flagged ? 'flagged' : 'quiet'}</td></tr>)}</tbody></table>}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Reported liability and the carry-forward estimate at each close, FY2021 to FY2026">
          {[400, 450, 500, 550].map(v => <g key={v}><line className="grid" x1={L} x2={W - R} y1={y2(v)} y2={y2(v)}/><text className="tick" x={L - 6} y={y2(v) + 3} textAnchor="end">${v}M</text></g>)}
          {closes.map((c, i) => { const est = Number(c.estimates_musd[best]), act = c.actual_musd, err = est / act - 1; return <g key={c.fiscal_year}>
            <line className="gap" x1={x2(i)} x2={x2(i)} y1={y2(est)} y2={y2(act)}/>
            <circle className="dot-jade" cx={x2(i)} cy={y2(est)} r="5"/><circle className="dot-real" cx={x2(i)} cy={y2(act)} r="5"/>
            {Math.abs(err) >= 0.15 && <text className="note" x={x2(i) + 10} y={(y2(est) + y2(act)) / 2 + 3}>{err > 0 ? '+' : ''}{pct(err, 0)}</text>}
            <rect className="hit" x={x2(i) - 24} y={T} width="48" height={H - T - B} onMouseEnter={() => tip('closes', { x: x2(i) / W * 100, y: Math.min(y2(est), y2(act)) / H * 100, text: `FY${c.fiscal_year}: reported ${musd(act)}, estimated ${musd(est)} (${err > 0 ? '+' : ''}${pct(err)})` })} onMouseLeave={() => tip('closes', null)}/>
            <text className="tick" x={x2(i)} y={H - 10} textAnchor="middle">FY{String(c.fiscal_year).slice(2)}</text>
          </g> })}
        </svg>
      </Chart>

      <Chart title="When the estimate trues up, the quarter moves" sub="Trade expense timing in General Mills' fourth-quarter earnings releases, points of year-on-year growth"
        tip={tips.timing} legend={<><Key kind="real" label="Organic net sales"/><Key kind="aqua" label="Operating profit"/></>}
        means={<>General Mills told investors three years running that trade timing moved the fourth quarter: up to 3 points of sales growth and 13 points of operating profit growth. That is the restatement path made public. JADE's August catch-up, scaled to the company, is about one of these points (~$49M). Finding it in August instead of at year end is the product.</>}
        table={<table><thead><tr><th>Quarter</th><th>Net sales</th><th>Operating profit</th><th>Released</th></tr></thead><tbody>{timing.map(t => <tr key={t.quarter}><td>{t.quarter}</td><td>{t.net_sales_pts > 0 ? '+' : ''}{t.net_sales_pts} pts</td><td>{t.operating_profit_pts == null ? 'not stated' : `${t.operating_profit_pts > 0 ? '+' : ''}${t.operating_profit_pts} pts`}</td><td>{t.released}</td></tr>)}</tbody></table>}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Columns of trade expense timing effects on net sales and operating profit growth by quarter">
          {[-12, -6, 0, 6, 12].map(v => <g key={v}><line className={v ? 'grid' : 'axis'} x1={L} x2={W - R} y1={y3(v)} y2={y3(v)}/><text className="tick" x={L - 6} y={y3(v) + 3} textAnchor="end">{v > 0 ? '+' : ''}{v}</text></g>)}
          {timing.map((t, i) => [['sales', t.net_sales_pts, -16], ['profit', t.operating_profit_pts, 16]].map(([k, v, dx]) => v == null ? null : <g key={`${t.quarter}${k}`}>
            <path className={k === 'sales' ? 'col-real' : 'col-aqua'} d={column(x3(i) + Number(dx), y3(0), y3(Number(v)), 24)}/>
            <text className="value" x={x3(i) + Number(dx)} y={Number(v) >= 0 ? y3(Number(v)) - 6 : y3(Number(v)) + 14} textAnchor="middle">{Number(v) > 0 ? '+' : ''}{String(v)}</text>
            <rect className="hit" x={x3(i) + Number(dx) - 16} y={T} width="32" height={H - T - B} onMouseEnter={() => tip('timing', { x: (x3(i) + Number(dx)) / W * 100, y: 10, text: `${t.quarter}: "${t.quote}"` })} onMouseLeave={() => tip('timing', null)}/>
          </g>))}
          {timing.map((t, i) => <text key={t.quarter} className="tick" x={x3(i)} y={H - 10} textAnchor="middle">{t.quarter}</text>)}
        </svg>
      </Chart>

      <Chart title="Asked once, then settled by precedent" sub={`Simulation, seed 1337 · findings each month: settled by the agent or a precedent, or asked of a person`}
        tip={tips.played} legend={<><Key kind="jade" label="Settled without a person"/><Key kind="real" label="Asked a person"/></>}
        means={months.length ? <>Repeat situations stop reaching people: by December {end.settled} of {end.repeats} repeats were settled by a precedent someone set earlier, and the rest were asked again only because they were larger than anything approved before. The rate of asking isn't a straight line down, and shouldn't be: September spikes when JADE learns a new control (sell-through drifting above the accrual rate) and has new questions to ask once.</> : <>Run a year (<code>make players</code>) to see who decided each finding, month by month.</>}
        table={<table><thead><tr><th>Month</th><th>Findings</th><th>Asked a person</th><th>Repeats so far</th><th>Settled by precedent</th></tr></thead><tbody>{months.map(m => <tr key={m.as_of}><td>{m.as_of}</td><td>{m.found}</td><td>{m.asked}</td><td>{m.repeats}</td><td>{m.settled}</td></tr>)}</tbody></table>}>
        {months.length ? <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Stacked columns of findings per month, split into settled without a person and asked a person">
          {[0, 4, 8, 12, 16].filter(v => v <= fMax).map(v => <g key={v}><line className={v ? 'grid' : 'axis'} x1={L} x2={W - R} y1={y4(v)} y2={y4(v)}/><text className="tick" x={L - 6} y={y4(v) + 3} textAnchor="end">{v}</text></g>)}
          {months.map((m, i) => { const auto = m.found - m.asked; return <g key={m.as_of}>
            <path className="col-jade" d={column(x4(i), y4(0), y4(auto), bw, m.asked === 0)}/>
            {m.asked > 0 && <path className="col-real" d={column(x4(i), y4(auto) - 2, y4(m.found) - 2, bw)}/>}
            <rect className="hit" x={x4(i) - 18} y={T} width="36" height={H - T - B} onMouseEnter={() => tip('played', { x: x4(i) / W * 100, y: y4(m.found) / H * 100, text: `${m.as_of}: ${m.found} findings, ${m.asked} asked a person · ${m.settled} of ${m.repeats} repeats settled by precedent so far` })} onMouseLeave={() => tip('played', null)}/>
            <text className="tick" x={x4(i)} y={H - 10} textAnchor="middle">{new Date(`${m.as_of}-01T12:00:00`).toLocaleDateString('en-US', { month: 'short' })}</text>
          </g> })}
          {(() => { const i = months.findIndex(m => m.as_of.endsWith('-09')); return i >= 0 ? <g><line className="leader" x1={x4(i)} x2={x4(i)} y1={T + 6} y2={y4(months[i].found) - 4}/><text className="note" x={x4(i) + 4} y={T + 2} textAnchor="start">new control learned</text></g> : null })()}
        </svg> : <p className="bt-empty">{seriesError ? `Monthly metrics unavailable: ${seriesError}. Re-seed with make db-reset seed, then make players.` : 'No played year in this database yet.'}</p>}
      </Chart>
    </div>
    <footer className="bt-note">{apiMode === 'mock' ? 'Captured from the API (scripts/backtest_fixture.py).' : 'Connected API.'} 10-K and 8-K figures: SEC EDGAR, CIK 0000040704, each cited in tpa/filings.py. Played-year figures are the simulation.</footer>
  </main>
}

/** A column grown from the baseline: 4px rounded at the data end, square at the baseline. */
function column(cx: number, base: number, end: number, w: number, round = true) {
  const x = cx - w / 2, r = round ? Math.min(4, Math.abs(base - end) / 2) : 0
  if (end <= base) return `M${x},${base} V${end + r} Q${x},${end} ${x + r},${end} H${x + w - r} Q${x + w},${end} ${x + w},${end + r} V${base} Z`
  return `M${x},${base} V${end - r} Q${x},${end} ${x + r},${end} H${x + w - r} Q${x + w},${end} ${x + w},${end - r} V${base} Z`
}
