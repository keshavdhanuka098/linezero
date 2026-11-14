import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useServer } from '../../api/serverStore'
import { errMsg } from '../../api/client'
import type { ApiChart } from '../../api/types'
import { Card, EmptyState, ErrorState, Field, Skeleton } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'

export const tzOffset = () => -new Date().getTimezoneOffset()

export function QueuePicker({ label = 'Server queue', children }: { label?: string; children?: ReactNode }) {
  const queues = useServer(s => s.queues), id = useServer(s => s.queueId), set = useServer(s => s.setQueueId)
  return (
    <Card>
      <div className="toolbar" style={{ alignItems: 'flex-end', gap: 18 }}>
        <Field label={label}>
          <select className="sel" style={{ minWidth: 260 }} value={id ?? ''} onChange={e => set(Number(e.target.value))} aria-label={label}>
            {queues.map(q => <option key={q.id} value={q.id}>{q.name} · {q.counter_count} counters</option>)}
          </select>
        </Field>
        {children}
      </div>
    </Card>
  )
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState<string | null>(null), [loading, setLoading] = useState(false)
  const seq = useRef(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const run = useCallback(async () => {
    const my = ++seq.current
    setLoading(true); setError(null)
    try { const d = await fnRef.current(); if (my === seq.current) setData(d) }
    catch (e) { if (my === seq.current) setError(errMsg(e)) }
    finally { if (my === seq.current) setLoading(false) }
  }, [])
  useEffect(() => { if (enabled) void run() }, [enabled, run, ...deps])
  return { data, error, loading, reload: run, setData }
}

export function NoQueues() {
  return <Card><EmptyState title="No queues on the server" text="Seed the database: python -m app.seed.generate_demo_data --scenario all --reset" /></Card>
}

export function Async({ loading, error, onRetry, hasData, children }: { loading: boolean; error: string | null; onRetry(): void; hasData: boolean; children: ReactNode }) {
  if (error) return <Card><ErrorState text={error} onRetry={onRetry} /></Card>
  if (!hasData && loading) return <Skeleton h={220} />
  return <div style={{ display: 'grid', gap: 16, opacity: loading ? 0.65 : 1, transition: 'opacity .15s' }}>{children}</div>
}

export function chartRows(chart: ApiChart) {
  const rows = new Map<string | number, Record<string, string | number | null>>()
  for (const s of chart.series) for (const p of s.data) { const r = rows.get(p.x) ?? { x: p.x }; r[s.key] = p.y; rows.set(p.x, r) }
  return [...rows.values()]
}

const xLabel = (chart: ApiChart, v: string | number) => {
  if (chart.x.type !== 'time') return String(v)
  const d = new Date(String(v))
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function ApiChartCard({ chart, h = 240, area }: { chart: ApiChart | undefined; h?: number; area?: boolean }) {
  const animate = useAnimate()
  if (!chart) return null
  const rows = chartRows(chart)
  const unit = chart.y.unit && chart.y.unit !== 'customers' ? chart.y.unit : ''
  const fmt = (v: number) => `${(Math.round(v * 100) / 100).toLocaleString()}${unit && unit.length <= 3 ? unit : ''}`
  return (
    <Card title={chart.title} sub={`${chart.y.label}${chart.y.unit ? ` (${chart.y.unit})` : ''}`}>
      {rows.length === 0 ? <EmptyState title="No data in this period" /> : (<>
        <ChartBox h={h}><ResponsiveContainer>
          {chart.type === 'bar' ? (
            <BarChart data={rows} margin={{ left: -14, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="x" {...axisProps} tickFormatter={v => xLabel(chart, v)} minTickGap={24} /><YAxis {...axisProps} />
              <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={fmt} labelFmt={l => xLabel(chart, l)} />} />
              {chart.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.name} fill={C.cat[i % C.cat.length]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={animate} />)}
            </BarChart>
          ) : area ? (
            <AreaChart data={rows} margin={{ left: -14, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="x" {...axisProps} tickFormatter={v => xLabel(chart, v)} minTickGap={36} /><YAxis {...axisProps} />
              <Tooltip content={<ChartTooltip fmt={fmt} labelFmt={l => xLabel(chart, l)} />} />
              {chart.series.map((s, i) => <Area key={s.key} dataKey={s.key} name={s.name} stroke={C.cat[i % C.cat.length]} fill={C.cat[i % C.cat.length]} fillOpacity={0.15} connectNulls={false} dot={false} isAnimationActive={animate} />)}
            </AreaChart>
          ) : (
            <LineChart data={rows} margin={{ left: -14, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="x" {...axisProps} tickFormatter={v => xLabel(chart, v)} minTickGap={36} /><YAxis {...axisProps} />
              <Tooltip content={<ChartTooltip fmt={fmt} labelFmt={l => xLabel(chart, l)} />} />
              {chart.series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={C.cat[i % C.cat.length]} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={animate} />)}
            </LineChart>
          )}
        </ResponsiveContainer></ChartBox>
        {chart.series.length > 1 && <Legend items={chart.series.map((s, i) => ({ label: s.name, color: C.cat[i % C.cat.length] }))} />}
      </>)}
    </Card>
  )
}

export const n1 = (v: unknown, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—')
export const pctOf = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(0)}%` : '—')

export function download(blob: Blob, name: string) {
  const u = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(u), 1000)
}
