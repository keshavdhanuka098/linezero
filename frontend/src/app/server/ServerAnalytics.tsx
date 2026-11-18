import { useState } from 'react'
import { api } from '../../api/client'
import { useServer } from '../../api/serverStore'
import type { Analytics } from '../../api/types'
import { Card, Chip, EmptyState, Field, Kpi, PageHeader, Seg } from '../ui/kit'
import { Async, ApiChartCard, NoQueues, QueuePicker, n1, pctOf, tzOffset, useAsync } from './shared'

type Gran = 'hour' | 'day'

export default function ServerAnalytics() {
  const queueId = useServer(s => s.queueId)
  const [gran, setGran] = useState<Gran>('hour')
  const tz = tzOffset()
  const { data, error, loading, reload } = useAsync(async () => {
    const p = { queue_id: queueId, tz_offset_minutes: tz }
    const [overview, arrivals, waits, util, peaks] = await Promise.all([
      api<Analytics>('/analytics/overview', { params: { ...p, compare_previous: true } }),
      api<Analytics>('/analytics/arrivals', { params: { ...p, granularity: gran } }),
      api<Analytics>('/analytics/waiting-times', { params: { ...p, granularity: gran } }),
      api<Analytics>('/analytics/utilization', { params: { ...p, granularity: gran } }),
      api<Analytics>('/analytics/peak-hours', { params: p }),
    ])
    return { overview, arrivals, waits, util, peaks }
  }, [queueId, gran], queueId !== null)

  const k = data?.overview.summary.kpis
  const cmp = data?.overview.summary.comparison?.metrics as Record<string, { change_pct: number | null; verdict: string }> | undefined
  const verdictTone = (v?: string) => (v === 'better' || v === 'improved' ? 'ok' : v === 'worse' ? 'hot' : undefined)
  const peakHours: number[] = data?.peaks.summary.peak_hours ?? []
  const byHour: Record<string, any>[] = data?.peaks.tables.by_hour_of_day ?? []

  return (
    <div className="page">
      <PageHeader title="Queue Analytics" sub="Computed by the LineZero API from recorded queue activity." demo={false}>
        {data?.overview.meta.contains_synthetic_data && <Chip tone="demo">SYNTHETIC DATA</Chip>}
      </PageHeader>
      {queueId === null ? <NoQueues /> : (<>
        <QueuePicker>
          <Field label="Granularity"><Seg<Gran> value={gran} onChange={setGran} label="Granularity" options={[{ v: 'hour', l: 'Hourly' }, { v: 'day', l: 'Daily' }]} /></Field>
        </QueuePicker>
        <Async loading={loading} error={error} onRetry={reload} hasData={!!data}>
          {data && (data.overview.meta.empty ? <Card><EmptyState title="No activity recorded" text="This queue has no customers in the analysed period." /></Card> : (<>
            {data.overview.meta.data_notice && <div className="banner"><span>{data.overview.meta.data_notice}</span></div>}
            <div className="grid g4 kp">
              <Kpi label="Arrivals" value={k.arrivals} sub={cmpText(cmp?.arrivals)} />
              <Kpi label="Avg wait" value={n1(k.avg_waiting_time_min)} unit="min" sub={`p95 ${n1(k.p95_waiting_time_min)} min · ${cmpText(cmp?.avg_waiting_time_min)}`} />
              <Kpi label="Avg service time" value={n1(k.avg_service_time_min)} unit="min" sub={`${n1(k.throughput_per_hour)} served / hour`} />
              <Kpi label="Utilization" value={pctOf(k.avg_utilization)} bar={k.avg_utilization} tone={k.avg_utilization >= 0.92 ? 'hot' : undefined} sub={`avg queue ${n1(k.avg_queue_length)} · max ${k.max_queue_length}`} />
            </div>
            <div className="grid g4 kp">
              <Kpi label="Served" value={k.served} />
              <Kpi label="Abandoned" value={k.abandoned} sub={k.arrivals ? `${((k.abandoned / k.arrivals) * 100).toFixed(1)}% of arrivals` : undefined} tone={k.arrivals && k.abandoned / k.arrivals > 0.1 ? 'hot' : undefined} />
              <Kpi label="Peak hours" value={peakHours.length ? peakHours.map(h => `${String(h).padStart(2, '0')}:00`).join(', ') : 'None'} sub={peakHours.length ? 'statistically significant' : 'no hour stands out'} />
              <Kpi label="Wait vs previous period" value={<Chip tone={verdictTone(cmp?.avg_waiting_time_min?.verdict)}>{cmp?.avg_waiting_time_min?.verdict ?? 'n/a'}</Chip>} />
            </div>
            <div className="grid g2">
              <ApiChartCard chart={data.arrivals.charts.arrivals_over_time} />
              <ApiChartCard chart={data.waits.charts.waiting_time_over_time} />
              <ApiChartCard chart={data.overview.charts.queue_length_over_time} area />
              <ApiChartCard chart={data.util.charts.utilization_over_time} />
              <ApiChartCard chart={data.arrivals.charts.arrivals_by_hour_of_day} />
              <ApiChartCard chart={data.waits.charts.waiting_time_distribution} />
            </div>
            <Card title="Utilization by counter">
              <div className="tw"><table className="tbl"><thead><tr><th>Counter</th><th>Served</th><th>Busy (min)</th><th>Utilization</th></tr></thead><tbody>
                {(data.overview.tables.by_counter ?? []).map(r => <tr key={r.counter_id}><td>{r.counter_name}</td><td className="mono">{r.customers_served}</td><td className="mono">{n1(r.busy_time_min, 0)}</td><td className="mono">{pctOf(r.utilization)}</td></tr>)}
              </tbody></table></div>
            </Card>
            {byHour.length > 0 && (
              <Card title="Peak-hour test" sub="Each hour of the day tested against flat demand">
                <div className="tw"><table className="tbl"><thead><tr><th>Hour</th><th>Mean arrivals/h</th><th>p-value vs flat</th></tr></thead><tbody>
                  {byHour.map(r => <tr key={r.hour}><td className="mono">{r.label}</td><td className="mono">{n1(r.avg_arrivals_per_hour)}</td><td className="mono">{typeof r.p_value_vs_flat_demand === 'number' ? r.p_value_vs_flat_demand.toExponential(1) : '—'}</td></tr>)}
                </tbody></table></div>
              </Card>
            )}
          </>))}
        </Async>
      </>)}
    </div>
  )
}

function cmpText(m?: { change_pct: number | null }) {
  if (!m || m.change_pct === null || m.change_pct === undefined) return 'no previous period'
  if (Math.abs(m.change_pct) > 1000) return 'previous period had almost no data'
  return `${m.change_pct >= 0 ? '+' : ''}${m.change_pct.toFixed(1)}% vs previous`
}
