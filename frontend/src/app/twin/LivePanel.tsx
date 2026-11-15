import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { RefreshCw, Wand2 } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import { useServer } from '../../api/serverStore'
import type { ForecastResponse, LiveResponse } from '../../api/twinTypes'
import { Card, Chip, EmptyState, ErrorState, Kpi, Skeleton, Spinner, cx } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps } from '../charts/theme'
import type { CounterView, SceneCounter } from '../../lib/twinPlayback'
import FloorView from './FloorView'
import { f1 } from './common'

const STATUS: Record<LiveResponse['operational_status'], { tone: 'ok' | 'warn' | 'crit'; text: string }> = {
  normal: { tone: 'ok', text: 'Normal' }, busy: { tone: 'warn', text: 'All counters busy' },
  congested: { tone: 'crit', text: 'Congested' }, no_capacity: { tone: 'crit', text: 'No active counters' },
}
const MAX_DOTS = 36

export default function LivePanel({ onUseAsBase }: { onUseAsBase(live: LiveResponse): void }) {
  const queueId = useServer(s => s.queueId)
  const queues = useServer(s => s.queues)
  const setQueueId = useServer(s => s.setQueueId)
  const [live, setLive] = useState<LiveResponse | null>(null)
  const [fc, setFc] = useState<ForecastResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [fcErr, setFcErr] = useState<string | null>(null)
  const [fcBusy, setFcBusy] = useState(false)
  const [auto, setAuto] = useState(true)
  const seq = useRef(0)

  const load = useCallback(async () => {
    if (queueId === null) return
    const my = ++seq.current
    try { const d = await api<LiveResponse>(`/twin/live/${queueId}`); if (my === seq.current) { setLive(d); setErr(null) } }
    catch (e) { if (my === seq.current) setErr(errMsg(e)) }
  }, [queueId])
  const loadForecast = useCallback(async () => {
    if (queueId === null) return
    setFcBusy(true); setFcErr(null)
    try { setFc(await api<ForecastResponse>(`/twin/forecast/${queueId}`, { params: { replications: 40 } })) }
    catch (e) { setFc(null); setFcErr(errMsg(e)) } finally { setFcBusy(false) }
  }, [queueId])

  useEffect(() => { setLive(null); setFc(null); void load(); void loadForecast() }, [load, loadForecast])
  useEffect(() => {
    if (!auto) return
    const id = window.setInterval(() => { if (!document.hidden) void load() }, 5000)
    return () => window.clearInterval(id)
  }, [auto, load])

  const view = useMemo(() => {
    if (!live) return null
    const counters: SceneCounter[] = live.counters.map(c => {
      const serving = live.serving.find(s => s.counter_id === c.id)
      const state: CounterView = !c.active ? 'closed' : c.busy ? 'busy' : 'idle'
      return { index: c.index, name: c.name, state, servingId: c.busy ? serving?.token ?? -c.id : null }
    })
    const dots = live.waiting.slice(0, MAX_DOTS).map((w, i) => ({ id: w.token, slot: i }))
    return { counters, dots, overflow: Math.max(0, live.metrics.queue_length - dots.length) }
  }, [live])

  if (queueId === null) return <Card><EmptyState title="No queue selected" text="Seed demo data: python -m app.seed.generate_demo_data --scenario all --reset" /></Card>
  if (err && !live) return <Card><ErrorState text={err} onRetry={load} /></Card>
  if (!live || !view) return <Skeleton h={320} />
  const m = live.metrics, st = STATUS[live.operational_status]
  const fcData = fc ? [{ x: 'now', mean: m.queue_length, p10: m.queue_length, p90: m.queue_length }, ...fc.horizons.map(h => ({ x: `+${h.horizon_min}m`, mean: h.queue_length.mean, p10: h.queue_length.p10, p90: h.queue_length.p90 }))] : []

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Card title={live.queue.name} sub={`Updated ${new Date(live.as_of).toLocaleTimeString()}${live.queue.is_synthetic ? ' · synthetic demo data' : ''}`}
        right={<>
          {queues.length > 1 && <select className="sel" style={{ width: 220 }} value={queueId} onChange={e => setQueueId(Number(e.target.value))} aria-label="Queue">{queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select>}
          <Chip tone={st.tone}>{st.text}</Chip>
          <label className="chip" style={{ cursor: 'pointer' }}><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />Auto-refresh</label>
          <button className="btn sm" onClick={() => { void load(); void loadForecast() }}><RefreshCw size={13} />Refresh</button>
        </>}>
        <FloorView counters={view.counters} dots={view.dots} overflow={view.overflow} waiting={m.queue_length} label={c => `token ${c.servingId}`} transitionMs={500} title="Live queue" />
        <div className="grid g4 kp" style={{ marginTop: 10 }}>
          <Kpi label="Queue length" value={m.queue_length} tone={m.queue_length >= m.congestion_threshold ? 'crit' : undefined} sub={`congested at ≥ ${m.congestion_threshold}`} />
          <Kpi label="Longest wait" value={f1(m.longest_current_wait_min, 1)} unit="min" sub={`average ${f1(m.avg_current_wait_min, 1)} min`} />
          <Kpi label="Counter utilization" value={m.counter_utilization_now === null ? '—' : `${Math.round(m.counter_utilization_now * 100)}%`} bar={m.counter_utilization_now ?? 0} sub={`${m.busy_counters} busy · ${m.idle_counters} idle · ${live.counters.length - m.active_counters} inactive`} />
          <Kpi label="Predicted wait if you join now" value={live.predicted_wait_now ? f1(live.predicted_wait_now.waiting_time_min, 1) : '—'} unit="min" sub={live.predicted_wait_now ? `existing prediction engine (${live.predicted_wait_now.method.replace(/_/g, ' ')})` : 'unavailable'} />
        </div>
        <div className="kv" style={{ marginTop: 10 }}>
          <div><small>Arrival rate</small><b>{m.arrival_rate_per_min === null ? 'n/a' : `${f1(m.arrival_rate_per_min)}/min`}</b></div>
          <div><small>Service capacity</small><b>{f1(m.service_capacity_per_min)}/min</b></div>
          <div><small>Demand / capacity</small><b>{m.load_ratio === null ? 'n/a' : f1(m.load_ratio)}</b></div>
          <div><small>Completed (all time)</small><b>{m.completed_total}</b></div>
          <div><small>Abandoned (all time)</small><b>{m.abandoned_total}</b></div>
        </div>
        <p className="twin-note" style={{ marginBottom: 0 }}>Data: {Object.entries(live.data_provenance).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · ')}. Arrival rate source: {m.arrival_rate_source.replace(/_/g, ' ')}.</p>
        {err && <p className="err" role="alert">Refresh failed: {err}</p>}
      </Card>

      <Card title="Forecast: 5, 15, 30 and 60 minutes" sub={fc ? `${fc.replications} SimPy replications started from the current queue state` : 'Simulated from the current queue state'}
        right={<>
          {live.suggested_configuration && <button className="btn sm t" onClick={() => onUseAsBase(live)}><Wand2 size={13} />Use this queue as what-if base</button>}
          <button className="btn sm" disabled={fcBusy} onClick={loadForecast}>{fcBusy ? <Spinner size={13} /> : <RefreshCw size={13} />}Re-run</button>
        </>}>
        {fcErr && <ErrorState text={fcErr} onRetry={loadForecast} />}
        {!fc && !fcErr && <Skeleton h={160} />}
        {fc && (<>
          <div className="fc-grid">
            {fc.horizons.map(h => (
              <div key={h.horizon_min} className="fc">
                <h4>+{h.horizon_min} min <Chip tone={h.congestion.risk === 'high' ? 'crit' : h.congestion.risk === 'moderate' ? 'warn' : 'ok'}>{h.congestion.risk} risk</Chip></h4>
                <dl>
                  <dt>Queue length</dt><dd>{f1(h.queue_length.mean, 1)} <small>({f1(h.queue_length.p10, 0)}–{f1(h.queue_length.p90, 0)})</small></dd>
                  <dt>Waiting time</dt><dd>{f1(h.waiting_time_min.mean, 1)} min</dd>
                  <dt>Arrivals so far</dt><dd>{f1(h.arrivals_since_now.mean, 0)}</dd>
                  <dt>Utilization</dt><dd>{f1(h.counter_utilization.mean * 100, 0)}%</dd>
                  <dt>P(congestion)</dt><dd>{f1(h.congestion.probability * 100, 0)}%</dd>
                </dl>
              </div>
            ))}
          </div>
          <ChartBox h={200}><ResponsiveContainer>
            <LineChart data={fcData} margin={{ left: -14, right: 6, top: 10 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="x" {...axisProps} /><YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip fmt={v => f1(v, 1)} />} />
              <Line dataKey="p90" name="P90" stroke={C.warn} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              <Line dataKey="mean" name="Mean" stroke={C.violet} strokeWidth={2} dot isAnimationActive={false} />
              <Line dataKey="p10" name="P10" stroke={C.teal} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer></ChartBox>
          <Legend items={[{ label: 'Mean queue', color: C.violet }, { label: 'P90', color: C.warn, dashed: true }, { label: 'P10', color: C.teal, dashed: true }]} />
          <details style={{ marginTop: 8 }}><summary className={cx('twin-note')}>How this forecast is made, and what it assumes</summary>
            <ul className="twin-note">{fc.assumptions.map(a => <li key={a}>{a}</li>)}<li>Arrival rate source: {fc.starting_state.arrival_rate_source?.replace(/_/g, ' ')}. {fc.notes.arrival_rate_floored ? 'No recent arrivals were found, so a near-zero rate was used.' : ''}</li></ul>
            <p className="twin-note">Waiting time uses the prediction engine’s baseline formula on each simulated state. The (min–max) range is the 10th–90th percentile across replications, not a validated prediction interval, and no accuracy claim is made.</p>
          </details>
        </>)}
      </Card>
    </div>
  )
}
