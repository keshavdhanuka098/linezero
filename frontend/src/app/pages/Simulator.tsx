import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { GitCompare, Pause, Play, RotateCcw, Save, Shuffle } from 'lucide-react'
import { useStore } from '../../store/store'
import { Simulation, runSimulation, type SimMetrics, type SimParams, type SimPoint } from '../../lib/simEngine'
import { allenCunneenWq } from '../../lib/queueMath'
import { fmtMin, pct } from '../../lib/metrics'
import { numberIn } from '../../lib/validate'
import { Bar as Meter, Card, Chip, DemoBadge, Field, PageHeader, Seg, cx, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'
import ServerSimulator from '../server/ServerSimulator'
import { useServerMode } from '../../api/serverStore'

type K = 'arrivalRate' | 'avgService' | 'counters' | 'duration' | 'arrivalCV' | 'serviceCV' | 'seed'
const SPEC: Record<K, { label: string; min: number; max: number; step: number; int?: boolean; unit: string; hint: string }> = {
  arrivalRate: { label: 'Customer arrival rate', min: 0.1, max: 8, step: 0.1, unit: '/min', hint: 'Average arrivals per minute' },
  avgService: { label: 'Average service time', min: 0.5, max: 30, step: 0.5, unit: 'min', hint: 'Mean time at a counter' },
  counters: { label: 'Service counters', min: 1, max: 20, step: 1, int: true, unit: '', hint: 'Identical counters sharing one line' },
  duration: { label: 'Simulation duration', min: 10, max: 480, step: 10, int: true, unit: 'min', hint: 'Arrivals stop and the run ends here' },
  arrivalCV: { label: 'Arrival variability (CV)', min: 0, max: 2, step: 0.1, unit: '', hint: '0 = evenly spaced · 1 = random (Poisson) · >1 = bursty' },
  serviceCV: { label: 'Service-time variability (CV)', min: 0, max: 2, step: 0.1, unit: '', hint: '0 = identical · 1 = exponential · >1 = very uneven' },
  seed: { label: 'Random seed', min: 1, max: 999999, step: 1, int: true, unit: '', hint: 'Same seed + parameters = same result' },
}
const SPEEDS = [{ v: '2', l: 'Slow' }, { v: '6', l: 'Normal' }, { v: '16', l: 'Fast' }, { v: '45', l: 'Max' }] as const
type Status = 'idle' | 'running' | 'paused' | 'done'

function SimulatorLocal() {
  const defaults = useStore(s => s.settings.sim), addReport = useStore(s => s.addReport)
  const animate = useAnimate()
  const [p, setP] = useState<Record<K, string>>(() => Object.fromEntries((Object.keys(SPEC) as K[]).map(k => [k, String(defaults[k])])) as Record<K, string>)
  const [speed, setSpeed] = useState('6')
  const [status, setStatus] = useState<Status>('idle')
  const [m, setM] = useState<SimMetrics | null>(null)
  const [series, setSeries] = useState<SimPoint[]>([])
  const [cmp, setCmp] = useState<null | { a: SimMetrics; b: SimMetrics; sa: SimPoint[]; sb: SimPoint[]; bCounters: number }>(null)
  const [bCount, setBCount] = useState(String(Math.min(20, Number(defaults.counters) + 1)))
  const simRef = useRef<Simulation | null>(null), statusRef = useRef<Status>('idle'), speedRef = useRef(6)
  speedRef.current = Number(speed)
  const setSt = (s: Status) => { statusRef.current = s; setStatus(s) }

  const errors = useMemo(() => Object.fromEntries((Object.keys(SPEC) as K[]).map(k => [k, numberIn(p[k], SPEC[k].min, SPEC[k].max, SPEC[k].label, SPEC[k].int)])) as Record<K, string | undefined>, [p])
  const valid = !Object.values(errors).some(Boolean)
  const params = (): SimParams => ({ arrivalRate: Number(p.arrivalRate), avgService: Number(p.avgService), counters: Number(p.counters), duration: Number(p.duration), arrivalCV: Number(p.arrivalCV), serviceCV: Number(p.serviceCV), seed: Number(p.seed) })
  const locked = status === 'running' || status === 'paused'

  const rho = valid ? (Number(p.arrivalRate) * Number(p.avgService)) / Number(p.counters) : NaN
  const theory = valid ? allenCunneenWq(Number(p.arrivalRate), Number(p.avgService), Number(p.counters), Number(p.arrivalCV), Number(p.serviceCV)) : NaN

  const canvasRef = useRef<HTMLCanvasElement>(null), wrapRef = useRef<HTMLDivElement>(null)
  const parts = useRef<{ x0: number; y0: number; x1: number; y1: number; t0: number; dur: number; kind: 'in' | 'out' }[]>([])
  const last = useRef({ arrived: 0, served: 0 })
  const lastUi = useRef(0)

  const draw = useCallback((now: number) => {
    const cv = canvasRef.current, sim = simRef.current
    if (!cv) return
    const w = cv.clientWidth, h = cv.clientHeight, dpr = Math.min(2, window.devicePixelRatio || 1)
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr) }
    const g = cv.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h)
    const nC = sim ? sim.p.counters : Number(p.counters) || 1
    const view = sim?.view()
    const entryX = 34, qX0 = 86, cX = w - 150, exitX = w - 24, cy = h / 2
    const laneH = Math.min(34, (h - 24) / nC), top = cy - (laneH * nC) / 2
    g.strokeStyle = '#1c2842'; g.lineWidth = 2; g.lineCap = 'round'
    g.beginPath(); g.moveTo(entryX, cy); g.lineTo(cX - 10, cy); g.stroke()
    for (let i = 0; i < nC; i++) { const y = top + laneH * (i + 0.5); g.beginPath(); g.moveTo(cX - 10, cy); g.bezierCurveTo(cX - 40, cy, cX - 40, y, cX, y); g.moveTo(cX + 96, y); g.lineTo(exitX, y); g.stroke() }
    g.fillStyle = '#8997AD'; g.font = '11px Inter, sans-serif'; g.textAlign = 'center'
    g.fillText('ARRIVALS', entryX, h - 8); g.fillText('QUEUE', (qX0 + cX - 40) / 2, h - 8); g.fillText('COUNTERS', cX + 48, h - 8); g.fillText('SERVED', exitX - 4, h - 8)
    g.fillStyle = '#20D6C5'; g.beginPath(); g.arc(entryX, cy, 6, 0, 7); g.fill()
    for (let i = 0; i < nC; i++) {
      const y = top + laneH * (i + 0.5), c = view?.counters[i], util = sim?.metrics().counterUtil[i] ?? 0
      g.fillStyle = '#0d1527'; g.strokeStyle = c?.busy ? '#6B65FF' : '#26365A'; g.lineWidth = 1.5
      g.beginPath(); g.roundRect(cX, y - laneH / 2 + 3, 96, laneH - 6, 7); g.fill(); g.stroke()
      if (c?.busy) { g.fillStyle = 'rgba(107,101,255,.35)'; g.beginPath(); g.roundRect(cX, y - laneH / 2 + 3, Math.max(8, 96 * Math.min(1, c.progress)), laneH - 6, 7); g.fill() }
      g.fillStyle = c?.busy ? '#E9F0FA' : '#64748f'; g.textAlign = 'left'; g.font = '11px Space Grotesk, Inter, sans-serif'
      g.fillText(`C${i + 1}`, cX + 8, y + 4); g.textAlign = 'right'; g.fillStyle = util > 0.9 ? '#FF7A45' : '#8997AD'; g.fillText(`${Math.round(util * 100)}%`, cX + 90, y + 4)
    }
    if (view) {
      const line = view.line, cols = Math.max(4, Math.floor((cX - 50 - qX0) / 12)), rows = Math.max(1, Math.floor((h - 36) / 12)), cap = cols * rows
      const slots = Math.min(line.length, cap)
      for (let i = 0; i < slots; i++) {
        const col = Math.floor(i / rows), row = i % rows
        const x = cX - 48 - col * 12, y = cy - ((rows - 1) * 12) / 2 + row * 12, age = line[i]
        g.fillStyle = age > 15 ? '#FF7A45' : age > 6 ? '#F5B84B' : '#20D6C5'
        g.beginPath(); g.arc(x, y, 4, 0, 7); g.fill()
      }
      if (line.length > cap) { g.fillStyle = '#E9F0FA'; g.textAlign = 'left'; g.fillText(`+${line.length - cap} more`, qX0, 18) }
    }
    if (sim) {
      const arr = sim.arrived - last.current.arrived, srv = sim.served - last.current.served
      for (let k = 0; k < Math.min(arr, 10); k++) parts.current.push({ x0: entryX, y0: cy, x1: cX - 52, y1: cy, t0: now + k * 40, dur: 500, kind: 'in' })
      if (srv > 0) sim.departures.slice(-Math.min(srv, 10)).forEach((d, k) => { const y = top + laneH * (d.counter + 0.5); parts.current.push({ x0: cX + 96, y0: y, x1: exitX, y1: y, t0: now + k * 40, dur: 600, kind: 'out' }) })
      last.current = { arrived: sim.arrived, served: sim.served }
    }
    parts.current = parts.current.filter(q => now - q.t0 < q.dur)
    for (const q of parts.current) {
      const t = Math.max(0, (now - q.t0) / q.dur), e = t * t * (3 - 2 * t)
      g.globalAlpha = q.kind === 'out' ? 1 - t * 0.6 : 0.4 + t * 0.6
      g.fillStyle = q.kind === 'out' ? '#20D6C5' : '#6B65FF'; g.beginPath(); g.arc(q.x0 + (q.x1 - q.x0) * e, q.y0 + (q.y1 - q.y0) * e, 4.5, 0, 7); g.fill(); g.globalAlpha = 1
    }
  }, [p.counters])

  useEffect(() => {
    let raf = 0, prev = performance.now()
    const loop = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000); prev = now
      const sim = simRef.current
      if (sim && statusRef.current === 'running') {
        sim.advanceTo(sim.t + dt * speedRef.current)
        if (now - lastUi.current > 90 || sim.done) {
          lastUi.current = now; setM(sim.metrics()); setSeries(sim.series.slice())
          if (sim.done) setSt('done')
        }
      }
      draw(now); raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [draw])

  const start = () => {
    if (!valid) return
    simRef.current = new Simulation(params()); last.current = { arrived: 0, served: 0 }; parts.current = []
    setSeries([]); setM(simRef.current.metrics()); setSt('running'); toast('Simulation started')
  }
  const reset = () => { simRef.current = null; parts.current = []; last.current = { arrived: 0, served: 0 }; setM(null); setSeries([]); setSt('idle') }
  const runCompare = () => {
    const eB = numberIn(bCount, 1, 20, 'Comparison counters', true)
    if (!valid || eB) { if (eB) toast(eB, true); return }
    const pa = params(), pb = { ...pa, counters: Number(bCount) }
    const a = runSimulation(pa), b = runSimulation(pb)
    setCmp({ a: a.metrics, b: b.metrics, sa: a.series, sb: b.series, bCounters: pb.counters })
  }
  const save = () => {
    const sim = simRef.current; if (!sim || status !== 'done') return
    const pr = sim.p, mm = sim.metrics()
    addReport({ type: 'simulation', title: `Simulation: ${pr.counters} counters, ${pr.arrivalRate}/min, ${pr.avgService}m service`, status: 'Completed', synthetic: true,
      summary: { Counters: pr.counters, 'Arrival rate /min': pr.arrivalRate, 'Avg service (min)': pr.avgService, 'Duration (min)': pr.duration, 'Arrival CV': pr.arrivalCV, 'Service CV': pr.serviceCV, Seed: pr.seed, Arrived: mm.arrived, Served: mm.served, Remaining: mm.remaining, 'Avg wait (min)': +mm.avgWait.toFixed(2), 'Max wait (min)': +mm.maxWait.toFixed(2), Utilization: pct(mm.utilization) },
      rows: sim.series.filter((_, i) => i % 4 === 0).map(s => ({ 'Time (min)': s.t, 'Queue length': s.queue, 'In service': s.inService, 'Avg wait (min)': +s.avgWait.toFixed(2) })) })
    toast('Run saved to Reports')
  }

  const mt = m ?? { queueLength: 0, avgWait: 0, maxWait: 0, served: 0, remaining: 0, utilization: 0, t: 0, arrived: 0, inService: 0, counterUtil: [], done: false }
  const progress = m ? Math.min(1, m.t / Number(p.duration || 1)) : 0
  const stable = rho < 1

  return (
    <div className="page">
      <PageHeader title="Queue Simulator" sub="Configure arrivals, service and counters, then watch customers flow through the system. Results are deterministic for a given seed.">
        {status === 'idle' || status === 'done' ? <button className="btn p" onClick={start} disabled={!valid}><Play size={16} />{status === 'done' ? 'Run again' : 'Start simulation'}</button>
          : status === 'running' ? <button className="btn p" onClick={() => setSt('paused')}><Pause size={16} />Pause simulation</button>
          : <button className="btn p" onClick={() => setSt('running')}><Play size={16} />Resume simulation</button>}
        <button className="btn" onClick={reset} disabled={status === 'idle'}><RotateCcw size={16} />Reset</button>
        <button className="btn t" onClick={save} disabled={status !== 'done'}><Save size={16} />Save run</button>
      </PageHeader>

      <div className="grid g12" style={{ alignItems: 'start' }}>
        <Card title="Parameters" sub={locked ? 'Locked while running — reset to edit' : 'Edit, then start'} right={<DemoBadge label="SIMULATION" />}>
          <div style={{ display: 'grid', gap: 14 }}>
            {(Object.keys(SPEC) as K[]).map(k => (
              <Field key={k} label={SPEC[k].label} error={errors[k]} hint={SPEC[k].hint} right={<span style={{ display: 'flex', gap: 4, alignItems: 'center' }}><input className={cx('in', errors[k] && 'bad')} style={{ width: 78, height: 28, textAlign: 'right' }} inputMode="decimal" disabled={locked} value={p[k]} aria-label={SPEC[k].label} onChange={e => setP({ ...p, [k]: e.target.value })} />{SPEC[k].unit && <em style={{ fontSize: 11, color: 'var(--muted)' }}>{SPEC[k].unit}</em>}</span>}>
                {k !== 'seed' && <input type="range" min={SPEC[k].min} max={SPEC[k].max} step={SPEC[k].step} disabled={locked} value={Number.isFinite(Number(p[k])) ? Number(p[k]) : SPEC[k].min} onChange={e => setP({ ...p, [k]: e.target.value })} aria-label={`${SPEC[k].label} slider`} />}
              </Field>
            ))}
            <button className="btn sm" disabled={locked} onClick={() => setP({ ...p, seed: String(Math.floor(Math.random() * 999999) + 1) })}><Shuffle size={14} />New random seed</button>
          </div>
        </Card>

        <div style={{ display: 'grid', gap: 14, minWidth: 0 }}>
          <Card title="Flow visualization" right={<div className="toolbar"><Seg value={speed} onChange={setSpeed} label="Speed" options={SPEEDS.map(s => ({ v: s.v, l: s.l }))} /></div>}
            sub={<>Load ρ = λ·s ÷ c = <b className="mono" style={{ color: stable ? 'var(--teal)' : 'var(--warn)' }}>{Number.isFinite(rho) ? rho.toFixed(2) : '—'}</b> {Number.isFinite(rho) && (stable ? '· stable on average' : '· demand exceeds capacity — the line will keep growing')}{Number.isFinite(theory) && stable ? ` · analytic mean wait ≈ ${fmtMin(theory)} (Allen–Cunneen approx.)` : ''}</>}>
            <div className="simbox" ref={wrapRef} style={{ height: Math.max(240, Math.min(420, (Number(p.counters) || 1) * 36 + 50)) }}><canvas ref={canvasRef} aria-label="Queue simulation visualization" role="img" /></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, gap: 12, flexWrap: 'wrap' }}>
              <div className="legend"><span><i style={{ background: C.teal }} />Waiting &lt; 6 min</span><span><i style={{ background: C.amber }} />6–15 min</span><span><i style={{ background: C.warn }} />&gt; 15 min</span></div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 220 }}><span className="mono" style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{Math.round(m?.t ?? 0)} / {p.duration} min</span><div style={{ flex: 1 }}><Meter v={progress} tone="vio" /></div><Chip tone={status === 'running' ? 'ok' : status === 'done' ? 'vio' : status === 'paused' ? 'warn' : undefined}>{status}</Chip></div>
            </div>
          </Card>
          <div className="grid g6 kp">
            {([['Queue length', mt.queueLength], ['Avg waiting time', fmtMin(mt.avgWait)], ['Max waiting time', fmtMin(mt.maxWait)], ['Customers served', mt.served], ['Remaining in system', mt.remaining], ['Counter utilization', pct(mt.utilization)]] as [string, string | number][]).map(([k, v]) => (
              <div className="card kpi" key={k}><div className="l">{k}</div><div className="v">{v}</div></div>
            ))}
          </div>
          <Card title="Queue growth and reduction" sub="People in line over simulated time" right={<DemoBadge label="SIMULATION" />}>
            {series.length < 2 ? <div className="empty" style={{ padding: 28 }}><p>Start the simulation to plot queue length over time.</p></div> : (<>
              <ChartBox h={230}><ResponsiveContainer><AreaChart data={series} margin={{ left: -18, right: 6, top: 6 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="t" type="number" domain={[0, Number(p.duration)]} {...axisProps} unit="m" /><YAxis {...axisProps} allowDecimals={false} />
                <Tooltip content={<ChartTooltip labelFmt={l => `t = ${l} min`} />} />
                <Area type="stepAfter" dataKey="queue" name="In line" stroke={C.violet} fill={C.violet} fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} />
                <Area type="stepAfter" dataKey="inService" name="In service" stroke={C.teal} fill={C.teal} fillOpacity={0.08} strokeWidth={1.5} isAnimationActive={false} />
              </AreaChart></ResponsiveContainer></ChartBox>
              <Legend items={[{ label: 'In line', color: C.violet }, { label: 'In service', color: C.teal }]} />
            </>)}
          </Card>
        </div>
      </div>

      <Card title="Run comparison" sub="Re-runs the full scenario with the same seed and arrivals, changing only the number of counters" right={<DemoBadge label="SIMULATION" />}>
        <div className="toolbar" style={{ alignItems: 'flex-end', marginBottom: 12 }}>
          <Field label="Scenario B counters"><input className="in" style={{ width: 110 }} inputMode="numeric" value={bCount} onChange={e => setBCount(e.target.value)} /></Field>
          <button className="btn p" onClick={runCompare} disabled={!valid}><GitCompare size={16} />Run comparison</button>
          {cmp && <button className="btn g" onClick={() => setCmp(null)}>Clear</button>}
          {cmp && <button className="btn t" onClick={() => {
            addReport({ type: 'simulation', title: `Comparison: ${p.counters} vs ${cmp.bCounters} counters`, status: 'Completed', synthetic: true, summary: { 'A counters': Number(p.counters), 'B counters': cmp.bCounters, 'A avg wait (min)': +cmp.a.avgWait.toFixed(2), 'B avg wait (min)': +cmp.b.avgWait.toFixed(2), 'A max wait (min)': +cmp.a.maxWait.toFixed(2), 'B max wait (min)': +cmp.b.maxWait.toFixed(2), Seed: Number(p.seed) }, rows: [] }); toast('Comparison saved to Reports')
          }}><Save size={16} />Save comparison</button>}
        </div>
        {!cmp ? <div className="empty" style={{ padding: 20 }}><p>Pick a second counter count and run a side‑by‑side comparison against the current parameters.</p></div> : (
          <div className="grid g2">
            <div className="tw"><table className="tbl"><thead><tr><th>Metric</th><th>A · {p.counters} counters</th><th>B · {cmp.bCounters} counters</th><th>Change</th></tr></thead><tbody>
              {([['Avg wait (min)', cmp.a.avgWait, cmp.b.avgWait, 2], ['Max wait (min)', cmp.a.maxWait, cmp.b.maxWait, 2], ['Customers served', cmp.a.served, cmp.b.served, 0], ['Remaining in system', cmp.a.remaining, cmp.b.remaining, 0], ['Utilization', cmp.a.utilization * 100, cmp.b.utilization * 100, 1]] as [string, number, number, number][]).map(([k, a, b, d]) => {
                const diff = b - a, better = k === 'Customers served' ? diff > 0 : diff < 0
                return <tr key={k}><td>{k}</td><td className="mono">{a.toFixed(d)}</td><td className="mono">{b.toFixed(d)}</td><td><Chip tone={Math.abs(diff) < 1e-9 ? undefined : k === 'Utilization' ? 'vio' : better ? 'ok' : 'hot'}>{diff > 0 ? '+' : ''}{diff.toFixed(d)}</Chip></td></tr>
              })}
            </tbody></table></div>
            <div><ChartBox h={220}><ResponsiveContainer><LineChart margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="t" type="number" domain={[0, Number(p.duration)]} {...axisProps} unit="m" /><YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip labelFmt={l => `t = ${l} min`} />} />
              <Line data={cmp.sa} dataKey="queue" name={`A · ${p.counters} counters`} stroke={C.violet} strokeWidth={2} dot={false} type="stepAfter" isAnimationActive={animate} />
              <Line data={cmp.sb} dataKey="queue" name={`B · ${cmp.bCounters} counters`} stroke={C.teal} strokeWidth={2} dot={false} type="stepAfter" isAnimationActive={animate} />
            </LineChart></ResponsiveContainer></ChartBox><Legend items={[{ label: `A · ${p.counters} counters`, color: C.violet }, { label: `B · ${cmp.bCounters} counters`, color: C.teal }]} /></div>
          </div>
        )}
      </Card>
    </div>
  )
}

export default function Simulator() {
  return useServerMode() ? <ServerSimulator /> : <SimulatorLocal />
}
