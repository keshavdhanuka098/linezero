import { Link } from 'react-router-dom'
import { Chip, Card, EmptyState, Kpi, PageHeader } from '../ui/kit'
import { api } from '../../api/client'
import { useServer } from '../../api/serverStore'
import type { Prediction } from '../../api/types'
import type { SlaSummaryRow } from '../../api/slaTypes'
import { atRiskCount } from '../../lib/sla'
import { scoreText } from '../../lib/sla'
import { Async, NoQueues, QueuePicker, n1, useAsync } from './shared'

export default function ServerDashboard() {
  const queues = useServer(s => s.queues), queueId = useServer(s => s.queueId), setQueueId = useServer(s => s.setQueueId)
  const pred = useAsync(() => api<Prediction>(`/predictions/${queueId}`, { params: { store: false } }), [queueId], queueId !== null)
  const waiting = queues.reduce((a, q) => a + q.waiting_count, 0), serving = queues.reduce((a, q) => a + q.serving_count, 0), counters = queues.reduce((a, q) => a + q.counter_count, 0)
  const sla = useAsync(() => api<{ queues: SlaSummaryRow[] }>('/sla/summary'), [queues.length], queues.length > 0)
  const p = pred.data
  const lo = p?.uncertainty ? p.uncertainty.lower_s / 60 : null, hi = p?.uncertainty ? p.uncertainty.upper_s / 60 : null

  return (
    <div className="page">
      <PageHeader title="Dashboard" sub="Queue intelligence overview from the LineZero API." demo={false}>
        {queues.some(q => q.is_synthetic) && <Chip tone="demo">SYNTHETIC DATA PRESENT</Chip>}
      </PageHeader>
      {queues.length === 0 ? <NoQueues /> : (<>
        <div className="grid g4 kp">
          <Kpi label="Queues" value={queues.length} />
          <Kpi label="Counters" value={counters} />
          <Kpi label="Waiting now" value={waiting} />
          <Kpi label="In service" value={serving} />
        </div>
        <QueuePicker label="Predict wait for" />
        <Async loading={pred.loading} error={pred.error} onRetry={pred.reload} hasData={!!p}>
          {p && (
            <Card title="Predicted wait for a customer joining now" sub={`Method: ${p.prediction_method.replace(/_/g, ' ')}`}>
              <div className="grid g4 kp">
                <Kpi label="Predicted wait" value={n1(p.predicted_waiting_time_min)} unit="min" sub={lo !== null && hi !== null ? `${Math.round((p.uncertainty?.level ?? 0) * 100)}% interval ${n1(lo)}–${n1(hi)} min` : 'no interval (not enough validation data)'} />
                <Kpi label="In line" value={p.queue_state.queue_length} />
                <Kpi label="Busy / active counters" value={`${p.queue_state.busy_counters} / ${p.queue_state.active_counters}`} />
              </div>
              {p.notes.map((n, i) => <p key={i} className="hint" style={{ marginTop: 8 }}>{n}</p>)}
            </Card>
          )}
        </Async>
        <Card title="SLA & customer experience" sub="Compliance of customers served in the last hour, and customers waiting now" right={<Link className="btn sm" to="/app/sla-intelligence">Open SLA Intelligence</Link>}>
          <Async loading={sla.loading} error={sla.error} onRetry={sla.reload} hasData={!!sla.data}>
            {sla.data && (
              <div className="tw"><table className="tbl"><thead><tr><th>Queue</th><th>Target</th><th>Compliance (last hour)</th><th>Predicted (waiting now)</th><th>At risk / breached now</th></tr></thead><tbody>
                {sla.data.queues.map(q => (
                  <tr key={q.queue_id}><td>{q.name}{q.is_synthetic ? <> <Chip tone="demo">SYNTHETIC</Chip></> : null}</td>
                    {q.configured ? (<><td className="mono">{q.standard_target_min} min</td>
                      <td className="mono">{q.current_score == null ? 'no completed customers' : `${scoreText(q.current_score)}% (n=${q.current_n})`}</td>
                      <td className="mono">{q.predicted_score == null ? '—' : `${scoreText(q.predicted_score)}%`}</td>
                      <td className="mono">{atRiskCount(q.counts)}</td></>)
                      : <td colSpan={4} className="hint">No SLA target set. <Link to="/app/sla-intelligence">Configure</Link></td>}</tr>))}
              </tbody></table></div>)}
          </Async>
        </Card>
        <Card title="All queues">
          {queues.length === 0 ? <EmptyState title="No queues" /> : (
            <div className="tw"><table className="tbl"><thead><tr><th>Queue</th><th>Waiting</th><th>In service</th><th>Counters</th><th>Status</th><th /></tr></thead><tbody>
              {queues.map(q => (
                <tr key={q.id}><td>{q.name}</td><td className="mono">{q.waiting_count}</td><td className="mono">{q.serving_count}</td><td className="mono">{q.counter_count}</td><td><Chip tone={q.status === 'active' ? 'ok' : undefined}>{q.status}</Chip></td>
                  <td><Link className="btn sm" to="/app/monitor" onClick={() => setQueueId(q.id)}>Open</Link></td></tr>
              ))}
            </tbody></table></div>
          )}
        </Card>
      </>)}
    </div>
  )
}
