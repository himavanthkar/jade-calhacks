import { useEffect, useRef, useState } from 'react'
import './LandingPage.css'

// Figures from the seeded General Mills ledger (the August 2026 close in fixtures/moment.json).
const rows = [
 ['$404,266.80','Held'],
 ['$1,391,636.52','Restated'],
 ['DD-0179','Matched'],
 ['$16,125,879.94','Reconciled'],
 ['5 of 5 gates','Passed'],
 ['$38,501.60','Disputed'],
]
const steps = [
 ['Matching DD-0179 to TP-0214','Walmart · 0.4s'],
 ['Checking verification gates','5 passed'],
 ['Restating a closed period','Amendment not applied'],
 ['Packaging the close','Signed · close reviewer'],
]
const features = [
 ['Process the month','Accrue on shipment, match deductions, and run the gates before anyone signs.'],
 ['Resolve exceptions','Route questions to the right owner and keep the supporting evidence.'],
 ['Explain every decision','Trace entries to terms, controls, and the decisions behind them.'],
]

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Sand-grain strands drifting behind the light sheet; grain count follows the sheet's area. */
function useStrands(canvas: React.RefObject<HTMLCanvasElement | null>) {
 useEffect(() => {
  const el = canvas.current, ctx = el?.getContext('2d')
  if (!el || !ctx) return
  let frame = 0, raf = 0, grains: { strand: number; t: number; j: number; s: number }[] = []
  const draw = () => {
   const w = el.clientWidth, h = el.clientHeight, dpr = Math.min(devicePixelRatio, 2)
   if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
    el.width = Math.round(w * dpr); el.height = Math.round(h * dpr)
    grains = Array.from({ length: Math.min(36000, Math.round(w * h / 70)) }, () => ({ strand: Math.random(), t: Math.random(), j: (Math.random() + Math.random() + Math.random() - 1.5) / 1.5, s: Math.random() }))
   }
   ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
   ctx.clearRect(0, 0, w, h)
   const count = Math.max(3, Math.round(w / 240)), gap = w / count, time = frame / 700
   for (const g of grains) {
    const k = Math.floor(g.strand * count * 2), side = k % 2 ? 1 : -1, column = Math.floor(k / 2)
    const y = g.t * h, phase = y / 170 + column * 1.7 + time
    const x = (column + .5) * gap + side * Math.sin(phase) * gap * .34 + g.j * (8 + 16 * Math.abs(Math.cos(phase)))
    ctx.fillStyle = `rgba(122,84,66,${.12 + g.s * .3})`
    const size = g.s > .95 ? 1.8 : 1.1
    ctx.fillRect(x, y + g.j * 4, size, size)
   }
   frame++
   if (!reducedMotion()) raf = requestAnimationFrame(draw)
  }
  draw()
  const onResize = () => { if (reducedMotion()) draw() }
  addEventListener('resize', onResize)
  return () => { cancelAnimationFrame(raf); removeEventListener('resize', onResize) }
 }, [canvas])
}

/** Dark dune of grains that opens the page, then dissolves into the light sheet. */
function useDunes(canvas: React.RefObject<HTMLCanvasElement | null>, active: boolean) {
 useEffect(() => {
  const el = canvas.current, ctx = el?.getContext('2d')
  if (!el || !ctx || !active) return
  let raf = 0
  const start = performance.now()
  const draw = (now: number) => {
   const w = el.clientWidth, h = el.clientHeight, dpr = Math.min(devicePixelRatio, 2)
   if (el.width !== w * dpr) { el.width = w * dpr; el.height = h * dpr }
   ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
   ctx.fillStyle = '#140d0b'; ctx.fillRect(0, 0, w, h)
   const t = (now - start) / 1000
   for (let band = 0; band < 7; band++) {
    const base = h * (.12 + band * .14)
    for (let i = 0; i < 1500; i++) {
     const x = (i * 9973 % 10007) / 10007 * w
     const crest = base + Math.sin(x / 260 + band * 1.3 + t * .6) * 70 + Math.sin(x / 90 + band) * 14
     const spread = ((i * 7919 % 1009) / 1009) ** 2 * 120
     const a = .5 - spread / 260
     ctx.fillStyle = `rgba(255,232,214,${a * (.6 + band * .08)})`
     ctx.fillRect(x, crest + spread, 1.2, 1.2)
    }
   }
   raf = requestAnimationFrame(draw)
  }
  raf = requestAnimationFrame(draw)
  return () => cancelAnimationFrame(raf)
 }, [canvas, active])
}

export default function LandingPage({ onEnter }: { onEnter: (view?: string) => void }) {
 const [intro, setIntro] = useState(() => !reducedMotion())
 const [leaving, setLeaving] = useState(false)
 const [step, setStep] = useState(0)
 const strands = useRef<HTMLCanvasElement>(null), dunes = useRef<HTMLCanvasElement>(null)
 useStrands(strands)
 useDunes(dunes, intro)
 useEffect(() => { if (!intro) return; const t = setTimeout(() => setIntro(false), 2600); return () => clearTimeout(t) }, [intro])
 useEffect(() => { const t = setInterval(() => setStep(s => (s + 1) % steps.length), 3200); return () => clearInterval(t) }, [])
 // Dissolve over the dashboard that is already rendered underneath.
 const enter = (view?: string) => {
  if (leaving) return
  if (reducedMotion()) return onEnter(view)
  setLeaving(true); setTimeout(() => onEnter(view), 650)
 }
 return <main className={`jade-landing ${leaving ? 'landing-leaving' : ''}`}>
  <div className={`landing-intro-veil ${intro ? '' : 'done'}`} aria-hidden="true"><canvas ref={dunes}/></div>
  <header className="landing-nav">
   <a className="landing-brand" href="#" onClick={e => e.preventDefault()}>JADE</a>
   <nav aria-label="Workspace sections">
    <button onClick={() => enter('Escalation Inbox')}>Decisions</button>
    <button onClick={() => enter('Month & Period')}>Close</button>
    <button onClick={() => enter('Backtest')}>Proof</button>
    <button onClick={() => enter('Live Scenario')}>Try a scenario</button>
   </nav>
   <div className="landing-nav-actions">
    <button className="ghost" onClick={() => enter('Interrogation')}>Ask JADE</button>
    <button className="accent" onClick={() => enter()}>Open workspace</button>
   </div>
  </header>
  <div className="landing-sheet">
   <canvas ref={strands} className="landing-strands" aria-hidden="true"/>
   <section className="landing-hero">
    <span className="landing-app-icon" aria-hidden="true"><b>J</b></span>
    <h1>JADE</h1>
    <p>The autonomous close for trade promotion</p>
    <div className="landing-cta">
     <span>General Mills · US Retail · August 2026</span>
     <button onClick={() => enter()}>Open workspace</button>
    </div>
   </section>
   <figure className="landing-media" aria-label="JADE working through the August close">
    <div className="landing-ledger" aria-hidden="true">
     <div className="landing-ledger-track">{[...rows, ...rows].map(([amount, state], i) => <div key={i}><span>{amount}</span><span>{state}</span></div>)}</div>
    </div>
    <div className="landing-chip" role="status">
     <i aria-hidden="true">J</i>
     <span key={step}><strong>{steps[step][0]}</strong> · {steps[step][1]}</span>
    </div>
   </figure>
   <p className="landing-note">Figures from the seeded General Mills ledger, August 2026 close. Every number in the workspace traces to a journal ID.</p>
   <section className="landing-capabilities" aria-label="JADE capabilities">
    {features.map(([title, description], i) => <article key={title}><span>0{i + 1}</span><h2>{title}</h2><p>{description}</p></article>)}
   </section>
  </div>
  <footer className="landing-footer">
   <div><strong>JADE</strong><p>Trade promotion autonomy · Cal Hacks 13.0, Hyphenate track</p><p>Accruals as contra-revenue under ASC 606. Credit loss evaluated separately under ASC 326.</p></div>
   <div><p>Built for the trade promotion accountant</p><p>and the deduction analyst</p></div>
   <div><button onClick={() => enter()}>Open workspace ↗</button></div>
  </footer>
 </main>
}
