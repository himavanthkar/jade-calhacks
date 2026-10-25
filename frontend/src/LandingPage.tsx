import { useEffect, useRef, useState, type CSSProperties } from 'react'
import './LandingPage.css'
import './LandingCinematic.css'
const features = [
 ['Process the month','Review journals, verification gates,\nand the close in one place.'],
 ['Resolve exceptions','Route questions to the right owner\nand keep the supporting evidence.'],
 ['Explain every decision','Trace entries to terms, controls,\nand the decisions behind them.'],
]
/** Independent decorative layer; disable through showGrid without changing content. */
export default function LandingPage({onEnter,showGrid=true}:{onEnter:()=>void;showGrid?:boolean}){
 const cinematic=new URLSearchParams(window.location.search).get('landing')==='v2'
 const [leaving,setLeaving]=useState(false)
 const enter=useRef(onEnter)
 useEffect(()=>{enter.current=onEnter},[onEnter])
 useEffect(()=>{
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const leaveTimer=window.setTimeout(()=>setLeaving(true),cinematic?(reduced?10000:10600):(reduced?7000:7600))
  const enterTimer=window.setTimeout(()=>enter.current(),cinematic?(reduced?10000:11600):(reduced?7000:8600))
  return ()=>{window.clearTimeout(leaveTimer);window.clearTimeout(enterTimer)}
 },[cinematic])
 return <main className={`jade-landing ${cinematic?'landing-cinematic':''} ${leaving?'landing-leaving':''}`}>
 {showGrid&&<div className="landing-matrix" aria-hidden="true">{Array.from({length:252},(_,i)=>{const row=Math.floor(i/18),column=i%18;return <i key={i} style={{'--gather-x':`${(8.5-column)*100/18}vw`,'--gather-y':`${(6.5-row)*50}px`,'--index':i,'--alpha':Math.pow(row/13,1.8)*(.035+.24*Math.pow(Math.abs(column-8.5)/8.5,1.4)),'--dx':`${(column-8.5)*32}px`,'--dy':`${180+(13-row)*14}px`,'--delay':`${((column*7+row*3)%12)*35}ms`} as CSSProperties}/>})}</div>}
 {cinematic&&<div className="cinema-atmosphere" aria-hidden="true"><div className="cinema-orbit"/><div className="cinema-sweep"/><span className="cinema-monogram">J</span></div>}
 <header className="landing-nav"><span className="landing-brand">JADE</span><div className="landing-nav-actions"><a href={cinematic?'?landing=v1':'?landing=v2'}>{cinematic?'Classic version':'Cinematic version'}</a><button onClick={onEnter}>Open workspace ↗</button></div></header>
 <section className="landing-intro"><p className="landing-eyebrow">TRADE PROMOTION, WITH CLARITY</p><h1><span>Less chasing.</span><br/><span>More clarity.</span></h1><p className="landing-description">Meet JADE: a workspace for trade promotion finance.<br/>Move from monthly activity to decisions you can explain.</p></section>
 <section className="landing-capabilities" aria-label="JADE capabilities">{features.map(([title,description],i)=><article key={title}><span>0{i+1}</span><h2>{title}</h2><p>{description}</p></article>)}</section>
 <footer className="landing-footer"><span>TRADE PROMOTION · EVIDENCE · CLARITY</span></footer>
 </main>
}
