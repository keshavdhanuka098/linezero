import { useMemo, useRef, useState } from 'react'
import { runSimulation } from '../lib/simEngine'

/** Two runs of the real simulation engine on identical seeds (common random numbers): 3 counters vs 4 counters under high demand. */
const BASE = { arrivalRate: 0.85, avgService: 4, duration: 240, arrivalCV: 1, serviceCV: 0.6, seed: 7 }
const W = 560, H = 230, M = { l: 38, r: 12, t: 14, b: 28 }

export default function TwinCompare() {
  const runs = useMemo(() => [3, 4].map(c => ({ c, ...runSimulation({ ...BASE, counters: c }) })), [])
  const [hover, setHover] = useState<number | null>(null)
  const ref = useRef<SVGSVGElement>(null)
  const a = runs[0], b = runs[1]
  const maxQ = Math.max(4, ...a.series.map(p => p.queue), ...b.series.map(p => p.queue))
  const yMax = Math.ceil(maxQ / 5) * 5
  const x = (t: number) => M.l + (t / BASE.duration) * (W - M.l - M.r)
  const y = (q: number) => H - M.b - (q / yMax) * (H - M.t - M.b)
  const path = (s: typeof a.series) => s.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.queue).toFixed(1)}`).join(' ')
  const peak = (s: typeof a.series) => Math.max(...s.map(p => p.queue))
  const move = (e: React.PointerEvent) => {
    const r = ref.current?.getBoundingClientRect(); if (!r) return
    const px = ((e.clientX - r.left) / r.width) * W
    const t = ((px - M.l) / (W - M.l - M.r)) * BASE.duration
    const i = Math.round(t / (a.series[1].t - a.series[0].t))
    setHover(Math.max(0, Math.min(a.series.length - 1, i)))
  }
  const hp = hover === null ? null : { a: a.series[hover], b: b.series[Math.min(hover, b.series.length - 1)] }
  const rows: [string, string, string][] = [
    ['Average wait', `${a.metrics.avgWait.toFixed(1)} min`, `${b.metrics.avgWait.toFixed(1)} min`],
    ['Peak queue', String(peak(a.series)), String(peak(b.series))],
    ['Customers served', String(a.metrics.served), String(b.metrics.served)],
    ['Counter utilization', `${Math.round(a.metrics.utilization * 100)}%`, `${Math.round(b.metrics.utilization * 100)}%`],
  ]
  return (
    <figure className="tc">
      <figcaption><b>Same demand, one more counter</b><span>4-hour run · 0.85 arrivals/min · identical random seed</span></figcaption>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Queue length over four hours with three counters versus four counters" onPointerMove={move} onPointerLeave={() => setHover(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map(f => <g key={f}><line x1={M.l} x2={W - M.r} y1={y(yMax * f)} y2={y(yMax * f)} className="tc-grid" /><text x={M.l - 8} y={y(yMax * f) + 4} textAnchor="end" className="tc-ax">{Math.round(yMax * f)}</text></g>)}
        {[0, 60, 120, 180, 240].map(t => <text key={t} x={x(t)} y={H - 8} textAnchor={t === 0 ? 'start' : t === 240 ? 'end' : 'middle'} className="tc-ax">{t === 0 ? '0' : `${t / 60}h`}</text>)}
        <path d={path(a.series)} className="tc-l a" /><path d={path(b.series)} className="tc-l b" />
        {hp && <g><line x1={x(hp.a.t)} x2={x(hp.a.t)} y1={M.t} y2={H - M.b} className="tc-cur" /><circle cx={x(hp.a.t)} cy={y(hp.a.queue)} r="4" className="tc-d a" /><circle cx={x(hp.b.t)} cy={y(hp.b.queue)} r="4" className="tc-d b" /></g>}
      </svg>
      <div className="tc-tip" aria-live="polite">{hp ? <>At {Math.round(hp.a.t)} min · <i className="a" />3 counters: <b>{hp.a.queue}</b> in line · <i className="b" />4 counters: <b>{hp.b.queue}</b> in line</> : 'Hover the chart to compare the two lines.'}</div>
      <table className="tc-t"><thead><tr><th>Result</th><th><i className="a" />3 counters</th><th><i className="b" />4 counters</th></tr></thead>
        <tbody>{rows.map(r => <tr key={r[0]}><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td></tr>)}</tbody></table>
    </figure>
  )
}
