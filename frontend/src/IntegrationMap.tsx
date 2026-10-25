import type { Integration } from './api'

/** Where JADE's evidence comes from and where its work goes. Live connections carry moving dashes;
 *  planned ones are dashed outlines with no logo, so nothing on the map claims more than the code does. */
type Node = { id: string; x: number; y: number; name: string; note: string; icon?: string; planned?: boolean; flow: string; side: 'in' | 'out' | 'up' }
const NODES: Node[] = [
  { id: 'gmail', x: 140, y: 110, name: 'Gmail', note: 'deductions inbox', icon: '/brand/gmail.svg', flow: 'notices · backup · amendments', side: 'in' },
  { id: 'edgar', x: 140, y: 240, name: 'SEC EDGAR', note: '10-K figures', icon: '/brand/sec.svg', flow: 'the ratio the close checks', side: 'in' },
  { id: 'retail', x: 140, y: 370, name: 'Retail Link · EDI 820', note: 'planned', planned: true, flow: 'portal deductions, remittances', side: 'in' },
  { id: 'claude', x: 480, y: 84, name: 'Claude', note: 'drafts card wording', icon: '/brand/claude.svg', flow: 'words only, never numbers', side: 'up' },
  { id: 'inbox', x: 820, y: 110, name: 'Escalation inbox', note: 'controller · analysts', flow: 'cards for a person', side: 'out' },
  { id: 'ledger', x: 820, y: 240, name: 'Postgres ledger', note: 'insert-only, bitemporal', icon: '/brand/postgresql.svg', flow: 'one write path', side: 'out' },
  { id: 'export', x: 820, y: 370, name: 'Excel close package', note: 'CSV with check rows', flow: 'signed by a person', side: 'out' },
]
const HUB = { x: 480, y: 250 }

function path(n: Node) {
  if (n.side === 'up') return `M${n.x},${n.y + 40} L${HUB.x},${HUB.y - 52}`
  const from = n.side === 'in' ? n.x + 44 : HUB.x + 52
  const to = n.side === 'in' ? HUB.x - 52 : n.x - 44
  const [y1, y2] = n.side === 'in' ? [n.y, HUB.y] : [HUB.y, n.y]
  const mid = (from + to) / 2
  return `M${from},${y1} C${mid},${y1} ${mid},${y2} ${to},${y2}`
}

export default function IntegrationMap({ integrations }: { integrations: Integration[] }) {
  const live = (id: string) => integrations.find(i => i.id === id)?.status !== 'not_connected'
  return <figure className="integration-map">
    <svg viewBox="0 0 960 470" role="img" aria-labelledby="map-title map-desc">
      <title id="map-title">JADE's integrations</title>
      <desc id="map-desc">Gmail and SEC EDGAR feed the JADE engine; Claude drafts card wording; the engine writes to an insert-only Postgres ledger, sends cards to the escalation inbox and exports the close package. Retail Link and EDI 820 are planned.</desc>
      <defs>
        <filter id="tile-shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#5b241d" floodOpacity=".12"/></filter>
        <radialGradient id="parchment" cx="50%" cy="45%" r="75%"><stop offset="0" stopColor="#fbf6ef"/><stop offset="1" stopColor="#f1e6d8"/></radialGradient>
      </defs>
      <rect x="8" y="8" width="944" height="454" rx="22" fill="url(#parchment)" stroke="#eaded0"/>
      {NODES.map(n => <g key={`p-${n.id}`}>
        <path d={path(n)} className={`map-line ${n.planned ? 'planned' : live(n.id) ? 'live' : 'off'}`}/>
        <text className="map-flow" x={n.side === 'up' ? n.x + 10 : n.side === 'in' ? n.x + 56 : n.x - 56}
          y={n.side === 'up' ? (n.y + 40 + HUB.y - 52) / 2 + 4 : n.y - 8} textAnchor={n.side === 'out' ? 'end' : 'start'}>{n.flow}</text>
      </g>)}
      <g className="map-hub">
        <rect x={HUB.x - 52} y={HUB.y - 52} width="104" height="104" rx="22" fill="#E86F31" filter="url(#tile-shadow)"/>
        <text x={HUB.x} y={HUB.y + 14} textAnchor="middle" className="map-hub-mark">J</text>
        <text x={HUB.x} y={HUB.y + 78} textAnchor="middle" className="map-name">JADE engine</text>
        <text x={HUB.x} y={HUB.y + 94} textAnchor="middle" className="map-note">controls · precedents · gates</text>
        <text className="map-mono" x={HUB.x} y={HUB.y + 122} textAnchor="middle">UNIFIED TRADE CONTEXT</text>
      </g>
      {NODES.map(n => <g key={n.id} className={`map-node ${n.planned ? 'planned' : ''}`}>
        <rect x={n.x - 40} y={n.y - 40} width="80" height="80" rx="18" fill={n.planned ? 'transparent' : '#fff'} filter={n.planned ? undefined : 'url(#tile-shadow)'}
          stroke={n.planned ? '#c9b6a2' : '#efe5d9'} strokeDasharray={n.planned ? '5 4' : undefined}/>
        {n.icon ? <image href={n.icon} x={n.x - 20} y={n.y - 20} width="40" height="40"/>
          : <text x={n.x} y={n.y + 8} textAnchor="middle" className="map-glyph">{n.id === 'inbox' ? '✉' : n.id === 'export' ? '⊞' : '⇄'}</text>}
        {!n.planned && n.side !== 'up' && <circle cx={n.x + 34} cy={n.y - 34} r="5" fill={live(n.id) ? '#21654a' : '#9b3b22'} stroke="#fff" strokeWidth="2"/>}
        {n.side === 'up'
          ? <><text x={n.x + 52} y={n.y - 4} className="map-name">{n.name}</text><text x={n.x + 52} y={n.y + 12} className="map-note">{n.note}</text></>
          : <><text x={n.x} y={n.y + 58} textAnchor="middle" className="map-name">{n.name}</text><text x={n.x} y={n.y + 74} textAnchor="middle" className="map-note">{n.note}</text></>}
      </g>)}
    </svg>
    <figcaption><span><i className="dot live"/>Live</span><span><i className="dot planned"/>Planned</span><span>Every arrow into the engine is evidence, never an instruction. Only code posts to the ledger.</span></figcaption>
  </figure>
}
