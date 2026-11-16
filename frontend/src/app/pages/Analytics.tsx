import { useDeferredValue, useMemo, useState } from 'react'
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CalendarX, Download, Layers } from 'lucide-react'
import { useStore } from '../../store/store'
import { DATASET_DAYS, aggregate, datasetRange, generateDataset, parseYmd, type Filters } from '../../lib/analyticsData'
import { fmtMin, pct } from '../../lib/metrics'
import { downloadCsv } from '../../lib/exporters'
import { Bar as Meter, Card, Chip, DemoBadge, EmptyState, ErrorState, Field, Kpi, PageHeader, Seg, Skeleton, cx } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'
import ServerAnalytics from '../server/ServerAnalytics'
import { useServerMode } from '../../api/serverStore'

type Preset = '7' | '14' | '30' | '90' | 'custom'
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const shift = (ymdStr: string, days: number) => { const d = parseYmd(ymdStr); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

function AnalyticsLocal() {
  const queues = useStore(s => s.queues), counters = useStore(s => s.counters), sla = useStore(s => s.settings.thresholds.waitSla)
  const animate = useAnimate()
  const range = datasetRange()
  const [preset, setPreset] = useState<Preset>('14')
  const [custom, setCustom] = useState({ start: shift(range.end, -20), end: range.end })
  const [sel, setSel] = useState<string[] | null>(null)
  const qids = (sel ?? queues.map(q => q.id)).filter(id => queues.some(q => q.id === id))
  const qKey = queues.map(q => `${q.id}:${q.arrivalRate}`).join('|') + counters.map(c => `${c.id}:${c.servers}:${c.avgService}:${c.routeWeight}`).join('|')
  const dataset = useMemo(() => generateDataset(queues, counters), [qKey])

  let start = custom.start, end = custom.end
  if (preset !== 'custom') { end = range.end; start = shift(range.end, -(Number(preset) - 1)) }
  const dateError = preset === 'custom' ? (!custom.start || !custom.end ? 'Choose both dates' : custom.start > custom.end ? 'Start date must be on or before the end date' : custom.start < range.start || custom.end > range.end ? `Dates must be between ${range.start} and ${range.end}` : undefined) : undefined
  const filters: Filters = { start, end, queueIds: qids, target: sla }
  const deferred = useDeferredValue(filters)
  const pending = deferred !== filters && JSON.stringify(deferred) !== JSON.stringify(filters)
  const A = useMemo(() => (dateError ? null : aggregate(dataset, deferred, queues, counters)), [dataset, deferred, dateError, queues, counters])

  const toggleQ = (id: string) => { const cur = sel ?? queues.map(q => q.id); const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]; setSel(next.length === queues.length ? null : next) }
  const exportCsv = () => { if (!A) return; downloadCsv(`linezero-analytics-${start}_${end}.csv`, A.daily.map(d => ({ Date: d.date, Arrivals: d.arrivals, 'Avg wait (min)': +d.avgWait.toFixed(2), 'Arrivals 7d MA': d.ma7, 'Abandonment rate': d.abandon === null ? 'n/a' : +(d.abandon * 100).toFixed(2) }))) }
  const empty = !dateError && A && (A.cells === 0 || qids.length === 0)

  return (
    <div className="page">
      <PageHeader title="Queue Analytics" sub="Demand, waiting and service patterns over a selectable window." >
        <button className="btn" onClick={exportCsv} disabled={!A || !A.cells}><Download size={16} />Export CSV</button>
      </PageHeader>
      <div className="banner warn"><CalendarX size={16} style={{ flex: 'none', marginTop: 2 }} /><span><b>Synthetic demonstration dataset.</b> {DATASET_DAYS} days of seeded history ({range.start} → {range.end}) generated from the current queue configuration. These are <u>not</u> real operational measurements. Distributions are modelled (log‑normal), and abandonment is only available for queues that track it.</span></div>

      <Card>
        <div className="toolbar" style={{ justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div className="toolbar" style={{ alignItems: 'flex-end' }}>
            <Field label="Date range"><Seg<Preset> value={preset} onChange={setPreset} label="Date range" options={[{ v: '7', l: '7 days' }, { v: '14', l: '14 days' }, { v: '30', l: '30 days' }, { v: '90', l: '90 days' }, { v: 'custom', l: 'Custom' }]} /></Field>
            {preset === 'custom' && <>
              <Field label="From"><input type="date" className={cx('in', dateError && 'bad')} style={{ width: 150 }} min={range.start} max={range.end} value={custom.start} onChange={e => setCustom({ ...custom, start: e.target.value })} /></Field>
              <Field label="To"><input type="date" className={cx('in', dateError && 'bad')} style={{ width: 150 }} min={range.start} max={range.end} value={custom.end} onChange={e => setCustom({ ...custom, end: e.target.value })} /></Field>
            </>}
          </div>
          <Field label="Queues">
            <div className="toolbar" style={{ gap: 6 }}>
              {queues.map(q => { const on = qids.includes(q.id); return <button key={q.id} className="chip" aria-pressed={on} onClick={() => toggleQ(q.id)} style={{ cursor: 'pointer', height: 30, color: on ? 'var(--text)' : 'var(--muted)', borderColor: on ? 'var(--violet)' : undefined, background: on ? 'var(--violet-soft)' : undefined }}>{q.name}</button> })}
            </div>
          </Field>
        </div>
        {dateError && <div className="err" role="alert" style={{ marginTop: 8 }}>{dateError}</div>}
      </Card>

      {dateError ? <Card><ErrorState title="Invalid date range" text={dateError} onRetry={() => { setPreset('14') }} /></Card>
        : !queues.length ? <Card><EmptyState icon={Layers} title="No queues to analyze" text="Create a queue in the Live Monitor first." /></Card>
        : empty ? <Card><EmptyState title="No data for this selection" text="Select at least one queue and a date range inside the dataset." action={<button className="btn" onClick={() => setSel(null)}>Select all queues</button>} /></Card>
        : !A || pending ? <div className="grid g3"><Skeleton h={110} /><Skeleton h={110} /><Skeleton h={110} /><Skeleton h={280} /><Skeleton h={280} /><Skeleton h={280} /></div>
        : <Body A={A} animate={animate} sla={sla} />}
    </div>
  )
}

function Body({ A, animate, sla }: { A: NonNullable<ReturnType<typeof aggregate>>; animate: boolean; sla: number }) {
  const t = A.totals
  const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00`
  return (<>
    <div className="grid g6 kp">
      <Kpi label="Total arrivals" value={t.arrivals.toLocaleString()} sub={`${t.days} days · ${Math.round(t.arrivals / t.days)}/day`} />
      <Kpi label="Average wait" value={fmtMin(t.avgWait)} tone={t.avgWait > sla ? 'hot' : undefined} sub={`target ${sla}m`} />
      <Kpi label="Average service time" value={fmtMin(t.avgService)} />
      <Kpi label="Queue efficiency" value={pct(t.efficiency)} bar={t.efficiency} sub={`customers waiting ≤ ${sla} min`} tone={t.efficiency < 0.7 ? 'hot' : t.efficiency < 0.85 ? 'warn' : undefined} />
      <Kpi label="Avg utilization" value={pct(t.util)} bar={t.util} />
      <Kpi label="Abandonment" value={t.abandonRate === null ? 'n/a' : pct(t.abandonRate, 1)} sub={t.abandonRate === null ? 'not tracked by selected queues' : 'of tracked arrivals'} />
    </div>
    <div className="grid g2">
      <Card title="Hourly arrival pattern" sub="Average arrivals per hour of day · peak hours highlighted" right={<DemoBadge label="Synthetic" />}>
        <ChartBox><ResponsiveContainer><BarChart data={A.hourly} margin={{ left: -18, right: 6, top: 6 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="label" {...axisProps} /><YAxis {...axisProps} />
          <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${v} / hour`} />} />
          <Bar dataKey="arrivals" name="Avg arrivals" radius={[4, 4, 0, 0]} maxBarSize={30} isAnimationActive={animate}>{A.hourly.map(h => <Cell key={h.hour} fill={h.peak ? C.warn : C.violet} />)}</Bar>
        </BarChart></ResponsiveContainer></ChartBox>
        <Legend items={[{ label: 'Normal hour', color: C.violet }, { label: 'Peak (≥ 1.25× average hour)', color: C.warn }]} />
      </Card>
      <Card title="Daily demand trend" sub="Arrivals per day with 7-day moving average" right={<DemoBadge label="Synthetic" />}>
        <ChartBox><ResponsiveContainer><ComposedChart data={A.daily} margin={{ left: -10, right: 6, top: 6 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={30} /><YAxis {...axisProps} />
          <Tooltip content={<ChartTooltip />} />
          <Area type="monotone" dataKey="arrivals" name="Arrivals" stroke={C.violet} fill={C.violet} fillOpacity={0.16} strokeWidth={2} isAnimationActive={animate} />
          <Line type="monotone" dataKey="ma7" name="7-day average" stroke={C.teal} strokeWidth={2} dot={false} isAnimationActive={animate} />
        </ComposedChart></ResponsiveContainer></ChartBox>
        <Legend items={[{ label: 'Daily arrivals', color: C.violet }, { label: '7-day moving average', color: C.teal }]} />
      </Card>
      <Card title="Waiting time distribution" sub="Customers by wait (minutes) — modelled log-normal per hour" right={<DemoBadge label="Synthetic" />}>
        <ChartBox><ResponsiveContainer><BarChart data={A.waitHist} margin={{ left: -10, right: 6, top: 6 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="bin" {...axisProps} unit="m" /><YAxis {...axisProps} />
          <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${v.toLocaleString()} customers`} labelFmt={l => `${l} min wait`} />} />
          <Bar dataKey="customers" name="Customers" radius={[4, 4, 0, 0]} isAnimationActive={animate}>{A.waitHist.map((b, i) => <Cell key={i} fill={b.beyondTarget ? C.warn : C.violet} />)}</Bar>
        </BarChart></ResponsiveContainer></ChartBox>
        <Legend items={[{ label: `Within ${sla} min target`, color: C.violet }, { label: 'Beyond target', color: C.warn }]} />
      </Card>
      <Card title="Service time distribution" sub="Customers by time at the counter (minutes)" right={<DemoBadge label="Synthetic" />}>
        <ChartBox><ResponsiveContainer><BarChart data={A.svcHist} margin={{ left: -10, right: 6, top: 6 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="bin" {...axisProps} unit="m" /><YAxis {...axisProps} />
          <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${v.toLocaleString()} customers`} labelFmt={l => `${l} min service`} />} />
          <Bar dataKey="customers" name="Customers" fill={C.teal} radius={[4, 4, 0, 0]} isAnimationActive={animate} />
        </BarChart></ResponsiveContainer></ChartBox>
      </Card>
      <Card title="Counter-wise utilization" sub="Estimated from arrival load share × service time ÷ capacity" right={<DemoBadge label="Synthetic" />}>
        <ChartBox h={Math.max(220, A.counterUtil.length * 28)}><ResponsiveContainer><BarChart data={A.counterUtil.map(c => ({ ...c, pct: Math.round(c.util * 100) }))} layout="vertical" margin={{ left: 10, right: 20, top: 6 }}>
          <CartesianGrid {...gridProps} horizontal={false} vertical /><XAxis type="number" domain={[0, 100]} unit="%" {...axisProps} /><YAxis type="category" dataKey="name" width={64} {...axisProps} />
          <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${v}%`} />} />
          <ReferenceLine x={85} stroke={C.warn} strokeDasharray="4 4" />
          <Bar dataKey="pct" name="Utilization" radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={animate}>{A.counterUtil.map((c, i) => <Cell key={i} fill={c.util >= 0.85 ? C.warn : C.violet} />)}</Bar>
        </BarChart></ResponsiveContainer></ChartBox>
      </Card>
      <Card title="Peak-hour detection" sub="Hours ≥ 1.25× the average hourly arrivals · weekday × hour heatmap" right={<DemoBadge label="Synthetic" />}>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          {A.peaks.length ? A.peaks.map(p => <Chip key={p.hour} tone="hot">{hourLabel(p.hour)}–{hourLabel(p.hour + 1)} · {p.arrivals}/h</Chip>) : <Chip>No pronounced peak in this selection</Chip>}
        </div>
        <Heatmap A={A} />
      </Card>
      <Card title="Queue efficiency" sub={`Share of customers who waited ≤ ${sla} min, by queue`} right={<DemoBadge label="Synthetic" />}>
        <div style={{ display: 'grid', gap: 12 }}>
          {A.perQueue.map(q => (
            <div key={q.id}><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}><span>{q.name}</span><span className="mono">{pct(q.efficiency)} · avg wait {fmtMin(q.avgWait)}</span></div><Meter v={q.efficiency} tone={q.efficiency < 0.7 ? 'hot' : q.efficiency < 0.85 ? 'warm' : undefined} /></div>
          ))}
        </div>
      </Card>
      <Card title="Abandonment rate" sub="Share of arrivals leaving before service, daily · only queues that track it" right={<DemoBadge label="Synthetic" />}>
        {A.totals.abandonRate === null ? <EmptyState title="No abandonment data" text="None of the selected queues record abandonment. Select a queue that does to see this chart." /> : (<>
          <ChartBox h={200}><ResponsiveContainer><LineChart data={A.daily.map(d => ({ ...d, rate: d.abandon === null ? null : +(d.abandon * 100).toFixed(2) }))} margin={{ left: -10, right: 6, top: 6 }}>
            <CartesianGrid {...gridProps} /><XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={30} /><YAxis {...axisProps} unit="%" />
            <Tooltip content={<ChartTooltip fmt={v => `${v}%`} />} />
            <Line type="monotone" dataKey="rate" name="Abandonment" stroke={C.crit} strokeWidth={2} dot={false} isAnimationActive={animate} />
          </LineChart></ResponsiveContainer></ChartBox>
          <div className="toolbar" style={{ marginTop: 8 }}>{A.perQueue.map(q => <Chip key={q.id} tone={q.abandonRate === null ? undefined : q.abandonRate > 0.05 ? 'hot' : 'ok'}>{q.name}: {q.abandonRate === null ? 'not tracked' : pct(q.abandonRate, 1)}</Chip>)}</div>
        </>)}
      </Card>
    </div>
  </>)
}

function Heatmap({ A }: { A: NonNullable<ReturnType<typeof aggregate>> }) {
  const hours = [...new Set(A.heat.map(h => h.hour))]
  return (
    <div role="table" aria-label="Average arrivals by weekday and hour" style={{ display: 'grid', gridTemplateColumns: `36px repeat(${hours.length},minmax(0,1fr))`, gap: 3, fontSize: 10, color: 'var(--muted)' }}>
      <span />{hours.map(h => <span key={h} style={{ textAlign: 'center' }}>{h}</span>)}
      {[1, 2, 3, 4, 5, 6, 0].map(d => (<div key={d} style={{ display: 'contents' }}>
        <span style={{ alignSelf: 'center' }}>{DAYS[d]}</span>
        {hours.map(h => { const v = A.heat.find(x => x.dow === d && x.hour === h)?.v ?? 0, k = A.heatMax ? v / A.heatMax : 0
          return <span key={h} title={`${DAYS[d]} ${String(h).padStart(2, '0')}:00 — ${v.toFixed(1)} arrivals/h`} style={{ height: 24, borderRadius: 4, background: `rgba(107,101,255,${0.08 + k * 0.85})`, outline: k > 0.85 ? `1.5px solid ${C.warn}` : 'none' }} /> })}
      </div>))}
    </div>
  )
}

export default function Analytics() {
  return useServerMode() ? <ServerAnalytics /> : <AnalyticsLocal />
}
