import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, ChevronRight, FileDown, Lightbulb, Save, SlidersHorizontal, TriangleAlert } from 'lucide-react'
import { useStore } from '../../store/store'
import { detectBottlenecks, recentArrivalRate, routingShare, type Finding, type Sev } from '../../lib/bottleneck'
import { pct } from '../../lib/metrics'
import { downloadCsv } from '../../lib/exporters'
import { Card, Chip, DemoBadge, EmptyState, PageHeader, Seg, cx, toast } from '../ui/kit'
import { C } from '../charts/theme'
import ServerBottlenecks from '../server/ServerBottlenecks'
import { useServerMode } from '../../api/serverStore'

const SEV_TONE: Record<Sev, 'crit' | 'hot' | 'warn' | 'ok'> = { critical: 'crit', high: 'hot', medium: 'warn', low: 'ok' }
const SEV_COL: Record<Sev, string> = { critical: C.crit, high: C.warn, medium: C.amber, low: C.teal }

function BottlenecksLocal() {
  const s = useStore()
  const findings = useMemo(() => detectBottlenecks(s), [s.queues, s.counters, s.history, s.settings.thresholds])
  const [sev, setSev] = useState<'all' | Sev>('all')
  const [selId, setSelId] = useState<string | null>(null)
  const shown = findings.filter(f => sev === 'all' || f.severity === sev)
  const sel = findings.find(f => f.id === selId) ?? null
  useEffect(() => { if (selId && !findings.some(f => f.id === selId)) setSelId(null) }, [findings, selId])
  const origin = findings[0]
  const counts = (['critical', 'high', 'medium', 'low'] as Sev[]).map(k => [k, findings.filter(f => f.severity === k).length] as const)

  const save = () => {
    s.addReport({ type: 'bottleneck', title: `Bottleneck report · ${new Date().toLocaleDateString()}`, status: 'Completed', synthetic: true,
      summary: { Findings: findings.length, Critical: counts[0][1], High: counts[1][1], 'Most affected': origin ? (origin.counterName ?? origin.queueName) : 'none', 'Top finding': origin?.type ?? 'none' },
      rows: findings.map(f => ({ Type: f.type, Severity: f.severity, Queue: f.queueName, Counter: f.counterName ?? '', Why: f.why, Impact: f.impact, Action: f.action })) })
    toast('Bottleneck report saved')
  }

  return (
    <div className="page">
      <PageHeader title="Bottleneck Investigator" sub="Rule-based analysis of the live demo state. Each finding explains the numbers and thresholds behind it.">
        <button className="btn" onClick={() => downloadCsv('linezero-bottlenecks.csv', findings.map(f => ({ Type: f.type, Severity: f.severity, Queue: f.queueName, Counter: f.counterName ?? '', Why: f.why, Impact: f.impact, Action: f.action })))} disabled={!findings.length}><FileDown size={16} />Export CSV</button>
        <button className="btn t" onClick={save} disabled={!findings.length}><Save size={16} />Save report</button>
      </PageHeader>

      {s.queues.length === 0 ? <Card><EmptyState title="Nothing to investigate" text="Create queues and counters in the Live Monitor first." action={<Link className="btn p" to="/app/monitor">Open Live Monitor</Link>} /></Card> : (<>
        <div className="grid g4 kp">
          {counts.map(([k, n]) => <div className="card kpi" key={k}><div className="l" style={{ textTransform: 'capitalize' }}><i className="ico-b" style={{ background: SEV_COL[k], margin: 0 }} />{k}</div><div className="v">{n}</div></div>)}
        </div>

        <Card title="Congestion flow" sub={origin ? <>Likely origin: <b style={{ color: 'var(--text)' }}>{origin.counterName ?? origin.queueName}</b> — {origin.type.toLowerCase()}. Click a node to inspect its findings.</> : 'No congestion detected. Flow width shows recent arrival / routing share.'} right={<DemoBadge />}>
          <FlowGraph findings={findings} selected={sel} onSelect={id => setSelId(id)} originId={origin?.counterId ?? origin?.queueId} />
          <div className="legend" style={{ marginTop: 8 }}><span><i style={{ background: C.teal }} />Healthy</span><span><i style={{ background: C.amber }} />Watch</span><span><i style={{ background: C.warn }} />Overloaded</span><span><i style={{ background: 'transparent', border: `2px solid ${C.crit}` }} />Congestion origin</span></div>
        </Card>

        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <h2 className="hd" style={{ fontSize: 18 }}>Findings <span style={{ color: 'var(--muted)', fontSize: 14 }}>({shown.length})</span></h2>
          <Seg<'all' | Sev> value={sev} onChange={setSev} label="Severity filter" options={[{ v: 'all', l: 'All' }, { v: 'critical', l: 'Critical' }, { v: 'high', l: 'High' }, { v: 'medium', l: 'Medium' }, { v: 'low', l: 'Low' }]} />
        </div>
        {shown.length === 0 ? <Card><EmptyState icon={CheckCircle2} title={findings.length ? 'No findings at this severity' : 'No bottlenecks detected'} text={findings.length ? 'Try another severity filter.' : 'All counters are within thresholds. Findings appear here when utilization, service time or arrival patterns cross them — try pausing a counter in the Live Monitor.'} /></Card>
          : <div style={{ display: 'grid', gap: 12 }}>{shown.map(f => <FindingCard key={f.id} f={f} selected={f.id === selId} onSelect={() => setSelId(f.id === selId ? null : f.id)} />)}</div>}
      </>)}
    </div>
  )
}

function FindingCard({ f, selected, onSelect }: { f: Finding; selected: boolean; onSelect(): void }) {
  return (
    <section className={cx('card bn', f.severity === 'critical' ? 'crit' : f.severity === 'high' ? 'high' : f.severity === 'medium' ? 'med' : 'low', selected && 'sel')} id={`f-${f.id}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <TriangleAlert size={18} color={SEV_COL[f.severity]} /><h3 style={{ fontSize: 16 }}>{f.type}</h3>
          <Chip tone={SEV_TONE[f.severity]}>{f.severity}</Chip><Chip>{f.queueName}</Chip>{f.counterName && <Chip tone="vio">{f.counterName}</Chip>}
        </div>
        <button className="btn sm g" onClick={onSelect}>{selected ? 'Hide in graph' : 'Show in graph'}<ChevronRight size={14} /></button>
      </div>
      <div className="kv">{f.metrics.map(([k, v]) => <div key={k}><small>{k}</small><b>{v}</b></div>)}</div>
      <div className="why"><b style={{ color: 'var(--text)' }}>Why this was detected. </b>{f.why}</div>
      <div className="grid g2" style={{ gap: 10 }}>
        <div className="why"><b style={{ color: 'var(--text)' }}>Potential impact. </b>{f.impact}</div>
        <div className="why" style={{ borderColor: 'rgba(32,214,197,.35)' }}><b style={{ color: 'var(--teal)' }}><Lightbulb size={13} style={{ verticalAlign: -2 }} /> Suggested action. </b>{f.action}</div>
      </div>
      <div><Link className="btn sm" to="/app/optimizer"><SlidersHorizontal size={14} />Test in Resource Optimizer</Link></div>
    </section>
  )
}

function FlowGraph({ findings, selected, onSelect, originId }: { findings: Finding[]; selected: Finding | null; onSelect(id: string | null): void; originId?: string }) {
  const s = useStore()
  const th = s.settings.thresholds
  const rowH = 30, counterRows = s.counters.length, H = Math.max(220, counterRows * rowH + 40), W = 900
  const cX = 690, qX = 380, aX = 70
  let row = 0
  const qNodes = s.queues.map(q => {
    const cs = s.counters.filter(c => c.queueId === q.id)
    const nodes = cs.map(c => ({ c, y: 24 + (row++) * rowH + rowH / 2 }))
    const y = nodes.length ? nodes.reduce((a, n) => a + n.y, 0) / nodes.length : 24 + row++ * rowH
    return { q, nodes, y }
  })
  const midY = H / 2
  const lamMax = Math.max(0.1, ...s.queues.map(q => recentArrivalRate(s, q)))
  const fq = (id: string) => findings.filter(f => f.queueId === id)
  const hot = (id?: string) => !!selected && (selected.counterId === id || (!selected.counterId && selected.queueId === id))
  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 640, height: 'auto', maxHeight: 560 }} role="img" aria-label="Flow of customers from arrivals through queues to counters">
        <defs><filter id="glow"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter></defs>
        {qNodes.map(({ q, nodes, y }) => {
          const lam = recentArrivalRate(s, q), qf = fq(q.id)
          return (<g key={q.id}>
            <path d={`M${aX + 40},${midY} C${(aX + qX) / 2},${midY} ${(aX + qX) / 2},${y} ${qX - 52},${y}`} fill="none" stroke={C.violet} strokeOpacity={0.55} strokeWidth={2 + (lam / lamMax) * 8} strokeLinecap="round" />
            {nodes.map(({ c, y: cy }) => {
              const share = routingShare(q, c, nodes.map(n => n.c)), isHot = c.status === 'active' && c.utilEma >= th.highUtil
              return <path key={c.id} d={`M${qX + 52},${y} C${(qX + cX) / 2},${y} ${(qX + cX) / 2},${cy} ${cX - 50},${cy}`} fill="none" stroke={c.status === 'paused' ? '#3a4766' : isHot ? C.warn : C.teal} strokeOpacity={c.status === 'paused' ? 0.6 : 0.6} strokeWidth={1.5 + share * 10} strokeDasharray={c.status === 'paused' ? '4 4' : undefined} strokeLinecap="round" />
            })}
            <g onClick={() => onSelect(qf[0]?.id ?? null)} style={{ cursor: qf.length ? 'pointer' : 'default' }}>
              <rect x={qX - 52} y={y - 20} width={104} height={40} rx={10} fill="#0d1527" stroke={originId === q.id ? C.crit : hot(q.id) ? C.violet : qf.length ? C.amber : '#26365A'} strokeWidth={originId === q.id || hot(q.id) ? 2.5 : 1.5} filter={originId === q.id ? 'url(#glow)' : undefined} />
              <text x={qX} y={y - 3} textAnchor="middle" fill="#E9F0FA" fontSize="11" fontWeight="600" fontFamily="Space Grotesk">{q.name.length > 15 ? q.name.slice(0, 14) + '…' : q.name}</text>
              <text x={qX} y={y + 12} textAnchor="middle" fill="#8997AD" fontSize="10">{lam.toFixed(2)}/min in</text>
            </g>
            {nodes.map(({ c, y: cy }) => {
              const isHot = c.status === 'active' && c.utilEma >= th.highUtil, low = c.status === 'active' && c.utilEma <= th.lowUtil, col = c.status === 'paused' ? '#3a4766' : isHot ? C.warn : low ? C.amber : C.teal
              const cf = findings.find(f => f.counterId === c.id), isOrigin = originId === c.id
              return (
                <g key={c.id} onClick={() => onSelect(cf?.id ?? null)} style={{ cursor: cf ? 'pointer' : 'default' }}>
                  {isOrigin && <rect x={cX - 52} y={cy - 13} width={152} height={26} rx={8} fill="none" stroke={C.crit} strokeWidth={2} filter="url(#glow)"><animate attributeName="opacity" values="1;.35;1" dur="1.8s" repeatCount="indefinite" /></rect>}
                  <rect x={cX - 50} y={cy - 11} width={148} height={22} rx={7} fill="#0d1527" stroke={hot(c.id) ? C.violet : '#26365A'} strokeWidth={hot(c.id) ? 2.5 : 1} />
                  <rect x={cX - 50} y={cy - 11} width={Math.max(3, 148 * c.utilEma)} height={22} rx={7} fill={col} fillOpacity={0.28} />
                  <text x={cX - 42} y={cy + 4} fill="#E9F0FA" fontSize="11" fontFamily="Space Grotesk">{c.name.replace('Counter ', '').replace(/ \(.*\)/, '')}{c.status === 'paused' ? ' · paused' : ''}</text>
                  <text x={cX + 90} y={cy + 4} textAnchor="end" fill={isHot ? C.warn : '#8997AD'} fontSize="11" fontFamily="Space Grotesk">{pct(c.utilEma)} · {c.waiting.length}</text>
                </g>
              )
            })}
          </g>)
        })}
        <g><circle cx={aX} cy={midY} r={36} fill="#0d1527" stroke={C.teal} strokeWidth={1.5} /><text x={aX} y={midY - 2} textAnchor="middle" fill="#E9F0FA" fontSize="11" fontFamily="Space Grotesk" fontWeight="600">Incoming</text><text x={aX} y={midY + 12} textAnchor="middle" fill="#8997AD" fontSize="10">demand</text></g>
        <text x={qX} y={14} textAnchor="middle" fill="#58698a" fontSize="10" letterSpacing="2">QUEUES</text>
        <text x={cX + 24} y={14} textAnchor="middle" fill="#58698a" fontSize="10" letterSpacing="2">COUNTERS · UTIL · LINE</text>
      </svg>
    </div>
  )
}

export default function Bottlenecks() {
  return useServerMode() ? <ServerBottlenecks /> : <BottlenecksLocal />
}
