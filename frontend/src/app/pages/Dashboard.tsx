import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity, AlertTriangle, BellRing, Clock, Gauge, GitFork, Layers, Pause, Play, Plus, Radio, Timer, Users, FileText } from 'lucide-react'
import { useStore } from '../../store/store'
import { demandProfile, demoHour, demoTimeLabel, fmtMin, pct, queueMetrics, queueRisk, riskLevel, systemMetrics } from '../../lib/metrics'
import { deriveAlerts } from '../../lib/alerts'
import { Bar as Meter, Card, Chip, DemoBadge, EmptyState, Field, Kpi, Modal, PageHeader, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'
import ServerDashboard from '../server/ServerDashboard'
import { useServerMode } from '../../api/serverStore'

const tone = (r: number) => (r >= 80 ? 'crit' : r >= 60 ? 'hot' : r >= 35 ? 'warn' : 'ok') as 'crit' | 'hot' | 'warn' | 'ok'

function DashboardLocal() {
  const s = useStore()
  const nav = useNavigate()
  const animate = useAnimate()
  const [addOpen, setAddOpen] = useState(false)
  const sys = useMemo(() => systemMetrics(s), [s.queues, s.counters, s.completed, s.history, s.settings.thresholds])
  const alerts = useMemo(() => deriveAlerts(s), [s.queues, s.counters, s.history, s.settings.thresholds])
  const fmt = s.settings.timeFormat, th = s.settings.thresholds
  const hist = s.history.slice(-60)

  const volume = hist.map(h => ({ t: demoTimeLabel(h.t, fmt), Waiting: h.waiting, 'In service': h.serving }))
  const arrivals = useMemo(() => {
    const rate = s.queues.reduce((a, q) => a + q.arrivalRate, 0)
    const out: { t: string; Actual?: number; Predicted: number }[] = []
    const all = s.history
    for (let i = Math.max(0, all.length - 60); i < all.length; i++) {
      let act = 0; for (let k = Math.max(0, i - 4); k <= i; k++) act += all[k].arrivals
      let pred = 0; for (let k = i - 4; k <= i; k++) pred += rate * demandProfile(demoHour(all[i].t + (k - i)))
      out.push({ t: demoTimeLabel(all[i].t, fmt), Actual: act, Predicted: Math.round(pred * 10) / 10 })
    }
    const last = all[all.length - 1]?.t ?? s.clock
    for (let f = 1; f <= 15; f++) { let pred = 0; for (let k = -4; k <= 0; k++) pred += rate * demandProfile(demoHour(last + f + k)); out.push({ t: demoTimeLabel(last + f, fmt), Predicted: Math.round(pred * 10) / 10 }) }
    return out
  }, [s.history, s.queues, s.clock, fmt])
  const waits = hist.map(h => ({ t: demoTimeLabel(h.t, fmt), 'Avg wait (min)': Math.round(h.avgWait * 10) / 10 }))
  const counterRows = s.counters.map(c => ({ name: c.name.replace('Counter ', '').replace(/ \(.*\)/, ''), full: c.name, util: Math.round(c.utilEma * 100), paused: c.status === 'paused', waiting: c.waiting.length, serving: c.serving.length }))
  const qm = s.queues.map(q => ({ q, m: queueMetrics(q, s.counters), risk: queueRisk(q, s.counters, s.history, th) }))
  const riskTrend = hist.map(h => ({ t: demoTimeLabel(h.t, fmt), 'Peak risk score': h.risk }))
  const feed = [...s.activity].reverse().slice(0, 7)

  return (
    <div className="page">
      <PageHeader title="Queue Intelligence Overview" sub="Real-time view of queue load, waiting time and congestion risk across all service queues.">
        <button className="btn p" onClick={() => setAddOpen(true)} disabled={!s.queues.length}><Plus size={16} />Add customer</button>
      </PageHeader>
      <div className="banner"><Activity size={16} style={{ flex: 'none', marginTop: 2 }} /><span><b>Demo simulation.</b> Every figure on this page comes from LineZero’s built‑in demo engine (1 tick = 1 demo minute). No live institutional data source is connected, and risk scores are transparent heuristics — not machine‑learning forecasts.</span></div>

      {!s.queues.length ? (
        <Card><EmptyState icon={Layers} title="No queues yet" text="Create your first queue in the Live Monitor to start seeing operational metrics." action={<Link className="btn p" to="/app/monitor">Open Live Monitor</Link>} /></Card>
      ) : (<>
        <div className="grid g6 kp">
          <Kpi label="Total Active Queues" icon={Layers} value={sys.activeQueues} unit={`/ ${sys.totalQueues}`} sub={`${sys.activeCounters} active · ${sys.pausedCounters} paused counters`} />
          <Kpi label="People Currently Waiting" icon={Users} value={sys.waiting} sub={`${sys.serving} being served now`} tone={sys.waiting > 40 ? 'warn' : undefined} />
          <Kpi label="Average Waiting Time" icon={Clock} value={fmtMin(sys.avgWait)} sub={`last ${sys.observed} completed · target ${th.waitSla}m`} tone={sys.avgWait > th.waitSla ? 'hot' : undefined} />
          <Kpi label="Average Service Time" icon={Timer} value={fmtMin(sys.avgService)} sub="per customer, recent" />
          <Kpi label="System Utilization" icon={Gauge} value={pct(sys.util)} bar={sys.util} tone={sys.util >= th.highUtil ? 'hot' : sys.util >= 0.7 ? 'warn' : undefined} sub="capacity-weighted" />
          <Kpi label="Predicted Congestion Risk" icon={AlertTriangle} value={sys.riskLevel} sub={`score ${sys.risk}/100 · heuristic`} tone={tone(sys.risk)} bar={sys.risk / 100} />
        </div>

        <div className="grid g2">
          <Card title="Live queue volume" sub="People waiting and in service, last 60 demo minutes" right={<DemoBadge />}>
            <ChartBox><ResponsiveContainer><AreaChart data={volume} margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" minTickGap={40} /><YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip />} />
              <Area type="monotone" dataKey="Waiting" stroke={C.violet} fill={C.violet} fillOpacity={0.18} strokeWidth={2} isAnimationActive={animate} />
              <Area type="monotone" dataKey="In service" stroke={C.teal} fill={C.teal} fillOpacity={0.1} strokeWidth={2} isAnimationActive={animate} />
            </AreaChart></ResponsiveContainer></ChartBox>
            <Legend items={[{ label: 'Waiting', color: C.violet }, { label: 'In service', color: C.teal }]} />
          </Card>
          <Card title="Actual vs predicted arrivals" sub="Arrivals per rolling 5 min · prediction = baseline demand profile, not ML" right={<DemoBadge />}>
            <ChartBox><ResponsiveContainer><LineChart data={arrivals} margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" minTickGap={40} /><YAxis {...axisProps} />
              <Tooltip content={<ChartTooltip />} />
              <Line type="monotone" dataKey="Predicted" stroke={C.amber} strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={animate} />
              <Line type="monotone" dataKey="Actual" stroke={C.teal} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={animate} />
            </LineChart></ResponsiveContainer></ChartBox>
            <Legend items={[{ label: 'Actual (demo)', color: C.teal }, { label: 'Predicted baseline (incl. next 15 min)', color: C.amber, dashed: true }]} />
          </Card>
          <Card title="Average waiting time trend" sub="Mean wait of the last 25 completed customers" right={<DemoBadge />}>
            <ChartBox><ResponsiveContainer><LineChart data={waits} margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" minTickGap={40} /><YAxis {...axisProps} unit="m" />
              <Tooltip content={<ChartTooltip fmt={v => `${v.toFixed(1)} min`} />} />
              <ReferenceLine y={th.waitSla} stroke={C.warn} strokeDasharray="4 4" label={{ value: `Target ${th.waitSla}m`, fill: C.warn, fontSize: 11, position: 'insideTopRight' }} />
              <Line type="monotone" dataKey="Avg wait (min)" stroke={C.violet} strokeWidth={2} dot={false} isAnimationActive={animate} />
            </LineChart></ResponsiveContainer></ChartBox>
          </Card>
          <Card title="Counter utilization comparison" sub={`Smoothed busy share · above ${pct(th.highUtil)} flagged`} right={<DemoBadge />}>
            <ChartBox><ResponsiveContainer><BarChart data={counterRows} margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} interval={0} /><YAxis {...axisProps} unit="%" domain={[0, 100]} />
              <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${v}%`} labelFmt={l => counterRows.find(r => r.name === l)?.full ?? String(l)} />} />
              <ReferenceLine y={th.highUtil * 100} stroke={C.warn} strokeDasharray="4 4" />
              <Bar dataKey="util" name="Utilization" radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={animate}>
                {counterRows.map(r => <Cell key={r.full} fill={r.paused ? '#3a4766' : r.util >= th.highUtil * 100 ? C.warn : C.violet} />)}
              </Bar>
            </BarChart></ResponsiveContainer></ChartBox>
            <Legend items={[{ label: 'Normal', color: C.violet }, { label: 'Above limit', color: C.warn }, { label: 'Paused', color: '#3a4766' }]} />
          </Card>
          <Card title="Queue distribution by service counter" sub="People waiting in each counter line + currently served" right={<DemoBadge />}>
            <ChartBox><ResponsiveContainer><BarChart data={counterRows} margin={{ left: -18, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} interval={0} /><YAxis {...axisProps} allowDecimals={false} />
              <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip labelFmt={l => counterRows.find(r => r.name === l)?.full ?? String(l)} />} />
              <Bar dataKey="waiting" name="Waiting" stackId="a" fill={C.violet} maxBarSize={26} isAnimationActive={animate} />
              <Bar dataKey="serving" name="Being served" stackId="a" fill={C.teal} radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={animate} />
            </BarChart></ResponsiveContainer></ChartBox>
            <Legend items={[{ label: 'Waiting', color: C.violet }, { label: 'Being served', color: C.teal }]} />
          </Card>
          <Card title="Congestion risk overview" sub="Heuristic score: utilization + wait vs target + queue trend" right={<DemoBadge />} className="" >
            <div style={{ display: 'grid', gap: 12 }}>
              {qm.map(({ q, m, risk }) => (
                <div key={q.id} style={{ display: 'grid', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                    <b style={{ fontWeight: 500 }}>{q.name}</b>
                    <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span style={{ color: 'var(--muted)', fontSize: 12 }}>est. wait {fmtMin(m.estWait)}</span><Chip tone={tone(risk)}>{riskLevel(risk)} · {risk}</Chip></span>
                  </div>
                  <Meter v={risk / 100} tone={risk >= 60 ? 'hot' : risk >= 35 ? 'warm' : undefined} />
                </div>
              ))}
            </div>
            <ChartBox h={110}><ResponsiveContainer><AreaChart data={riskTrend} margin={{ left: 0, right: 6, top: 10 }}>
              <XAxis dataKey="t" hide /><YAxis {...axisProps} domain={[0, 100]} width={40} ticks={[0, 50, 100]} />
              <Tooltip content={<ChartTooltip />} /><ReferenceLine y={60} stroke={C.warn} strokeDasharray="3 4" />
              <Area type="monotone" dataKey="Peak risk score" stroke={C.warn} fill={C.warn} fillOpacity={0.12} strokeWidth={2} isAnimationActive={animate} />
            </AreaChart></ResponsiveContainer></ChartBox>
          </Card>
        </div>

        <div className="grid g4">
          <Card title="Active alerts" right={<Chip tone={alerts.some(a => a.severity === 'crit') ? 'crit' : alerts.length ? 'warn' : 'ok'}>{alerts.length}</Chip>}>
            {alerts.length === 0 ? <EmptyState icon={BellRing} title="All clear" text="No thresholds are currently breached." /> : alerts.slice(0, 5).map(a => (
              <Link to={a.to} key={a.id} className="act-li" style={{ alignItems: 'flex-start' }}><i className="ico-b" style={{ background: a.severity === 'crit' ? C.crit : a.severity === 'warn' ? C.amber : C.violet }} /><div><div>{a.title}</div><small style={{ color: 'var(--muted)' }}>{a.detail}</small></div></Link>
            ))}
          </Card>
          <Card title="Recent activity">
            {feed.length === 0 ? <EmptyState title="No activity yet" /> : feed.map(a => <div className="act-li" key={a.id}><time>{demoTimeLabel(a.t, fmt)}</time><span>{a.text}</span></div>)}
          </Card>
          <Card title="System status">
            {[
              ['Demo simulation feed', s.settings.liveFeed ? <Chip tone="ok">Running</Chip> : <Chip tone="warn">Paused</Chip>],
              ['Data source', <Chip tone="vio">Synthetic demo</Chip>],
              ['Live institutional feed', <Chip>Not connected</Chip>],
              ['Backend / ML engine', <Chip>Not in this phase</Chip>],
              ['Counters online', <b className="mono">{sys.activeCounters} / {s.counters.length}</b>],
              ['Demo clock', <b className="mono">{demoTimeLabel(s.clock, fmt)}</b>],
            ].map(([k, v], i) => <div className="act-li" key={i} style={{ justifyContent: 'space-between', alignItems: 'center' }}><span style={{ color: 'var(--muted)' }}>{k}</span>{v}</div>)}
          </Card>
          <Card title="Quick actions">
            <div style={{ display: 'grid', gap: 8 }}>
              <button className="btn" onClick={() => setAddOpen(true)}><Plus size={16} />Add customer to a queue</button>
              <button className="btn" onClick={() => nav('/app/monitor')}><Radio size={16} />Open Live Monitor</button>
              <button className="btn" onClick={() => nav('/app/simulator')}><Gauge size={16} />Run a simulation</button>
              <button className="btn" onClick={() => nav('/app/bottlenecks')}><GitFork size={16} />Investigate bottlenecks</button>
              <button className="btn" onClick={() => {
                s.addReport({ type: 'metrics', title: `Metrics snapshot ${demoTimeLabel(s.clock, fmt)}`, status: 'Completed', synthetic: true,
                  summary: { 'People waiting': sys.waiting, 'Avg wait (min)': +sys.avgWait.toFixed(2), 'Avg service (min)': +sys.avgService.toFixed(2), Utilization: pct(sys.util), 'Risk score': sys.risk }, rows: qm.map(({ q, m, risk }) => ({ Queue: q.name, Waiting: m.waiting, 'Est wait (min)': Number.isFinite(m.estWait) ? +m.estWait.toFixed(1) : 'n/a', Utilization: pct(m.util), Risk: risk })) })
                toast('Snapshot saved to Reports')
              }}><FileText size={16} />Save metrics snapshot</button>
              <button className="btn" onClick={() => s.setLive(!s.settings.liveFeed)}>{s.settings.liveFeed ? <Pause size={16} /> : <Play size={16} />}{s.settings.liveFeed ? 'Pause demo feed' : 'Resume demo feed'}</button>
            </div>
          </Card>
        </div>
      </>)}
      {addOpen && <AddCustomerModal onClose={() => setAddOpen(false)} />}
    </div>
  )
}

function AddCustomerModal({ onClose }: { onClose(): void }) {
  const queues = useStore(s => s.queues), add = useStore(s => s.addCustomer)
  const [qid, setQid] = useState(queues[0]?.id ?? ''), [label, setLabel] = useState('')
  return (
    <Modal title="Add customer" sub="Joins the selected queue and is routed to a counter line." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn p" onClick={() => { add(qid, label); toast('Customer added'); onClose() }}>Add customer</button></>}>
      <Field label="Queue"><select className="sel" value={qid} onChange={e => setQid(e.target.value)}>{queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field>
      <Field label="Name or note (optional)"><input className="in" value={label} maxLength={40} onChange={e => setLabel(e.target.value)} placeholder="e.g. Walk-in" /></Field>
    </Modal>
  )
}

export default function Dashboard() {
  return useServerMode() ? <ServerDashboard /> : <DashboardLocal />
}
