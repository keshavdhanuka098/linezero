import { useState } from 'react'
import { Check, ChevronsRight, Pause, Play, Plus, UserMinus } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import { useServer } from '../../api/serverStore'
import { Card, Chip, EmptyState, Kpi, PageHeader, toast } from '../ui/kit'
import { Async, NoQueues, QueuePicker, n1, useAsync } from './shared'

interface Entry { id: number; token_number: number; status: string; position: number | null; counter_id: number | null; waiting_time_seconds: number | null }
interface Ctr { id: number; name: string; service_rate: number; status: string; current_load: number }
interface State { queue_status: string; waiting_count: number; serving_count: number; completed_count: number; abandoned_count: number; idle_counters: number; waiting: Entry[]; serving: Entry[]; counters: Ctr[]; waiting_truncated?: boolean }

const mins = (s: number | null) => (s === null ? '—' : `${(s / 60).toFixed(1)} min`)

export default function ServerMonitor() {
  const queueId = useServer(s => s.queueId), refreshQueues = useServer(s => s.refresh)
  const [busy, setBusy] = useState(false)
  const st = useAsync(() => api<State>(`/queues/${queueId}/state`), [queueId], queueId !== null)

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true)
    try { await fn(); if (ok) toast(ok); await st.reload(); void refreshQueues() } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const d = st.data
  const byId = new Map(d?.counters.map(c => [c.id, c.name]))

  return (
    <div className="page">
      <PageHeader title="Live Queue Monitor" sub="Manage customers and counters stored on the LineZero API." demo={false}>
        <button className="btn" onClick={() => void st.reload()} disabled={st.loading}>Refresh</button>
        <button className="btn" onClick={() => act(() => api(`/queues/${queueId}/serve-next`, { method: 'POST' }), 'Next customer assigned')} disabled={busy || !d?.waiting_count}><ChevronsRight size={16} />Serve next</button>
        <button className="btn p" onClick={() => act(() => api(`/queues/${queueId}/entries`, { method: 'POST' }), 'Customer added')} disabled={busy || queueId === null}><Plus size={16} />Add customer</button>
      </PageHeader>
      {queueId === null ? <NoQueues /> : (<>
        <QueuePicker />
        <Async loading={st.loading} error={st.error} onRetry={st.reload} hasData={!!d}>
          {d && (<>
            <div className="grid g4 kp">
              <Kpi label="Waiting" value={d.waiting_count} />
              <Kpi label="In service" value={d.serving_count} sub={`${d.idle_counters} idle counters`} />
              <Kpi label="Completed" value={d.completed_count} />
              <Kpi label="Abandoned" value={d.abandoned_count} />
            </div>
            <div className="grid g21">
              <Card title="Waiting line" sub={d.waiting_truncated ? 'Showing the first part of the line' : undefined}>
                {d.waiting.length === 0 ? <EmptyState title="Nobody is waiting" /> : (
                  <div className="tw" style={{ maxHeight: 380, overflow: 'auto' }}><table className="tbl"><thead><tr><th>Pos</th><th>Token</th><th>Waited</th><th>Assign</th><th /></tr></thead><tbody>
                    {d.waiting.map(e => (
                      <tr key={e.id}><td className="mono">{e.position}</td><td className="mono">#{e.token_number}</td><td className="mono">{mins(e.waiting_time_seconds)}</td>
                        <td><select className="sel" aria-label={`Assign token ${e.token_number}`} value="" onChange={ev => ev.target.value && act(() => api(`/queues/${queueId}/entries/${e.id}/assign`, { method: 'POST', body: { counter_id: Number(ev.target.value) } }), 'Customer assigned')}>
                          <option value="">Counter…</option>{d.counters.filter(c => c.status === 'active').map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></td>
                        <td><button className="btn sm g ic" aria-label={`Remove token ${e.token_number}`} onClick={() => act(() => api(`/queues/${queueId}/entries/${e.id}`, { method: 'DELETE' }), 'Customer removed')}><UserMinus size={14} /></button></td></tr>
                    ))}
                  </tbody></table></div>
                )}
              </Card>
              <Card title="Counters">
                <div style={{ display: 'grid', gap: 10 }}>
                  {d.counters.map(c => {
                    const cur = d.serving.find(e => e.counter_id === c.id)
                    return (
                      <div key={c.id} className="toolbar" style={{ justifyContent: 'space-between', gap: 8 }}>
                        <div><b style={{ fontWeight: 500 }}>{c.name}</b><div className="hint">{n1(c.service_rate, 2)}/min · {cur ? `serving #${cur.token_number}` : c.status === 'active' ? 'idle' : c.status}</div></div>
                        <div className="toolbar" style={{ gap: 4 }}>
                          {cur && <button className="btn sm" onClick={() => act(() => api(`/queues/${queueId}/entries/${cur.id}/complete`, { method: 'POST' }), 'Service completed')}><Check size={14} />Done</button>}
                          {c.status === 'active' ? <button className="btn sm g" aria-label={`Pause ${c.name}`} onClick={() => act(() => api(`/counters/${c.id}/pause`, { method: 'POST' }))}><Pause size={14} /></button>
                            : c.status === 'paused' ? <button className="btn sm g" aria-label={`Resume ${c.name}`} onClick={() => act(() => api(`/counters/${c.id}/resume`, { method: 'POST' }))}><Play size={14} /></button> : <Chip>{c.status}</Chip>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Card>
            </div>
            <Card title="In service">
              {d.serving.length === 0 ? <EmptyState title="No one is being served" /> : (
                <div className="tw"><table className="tbl"><thead><tr><th>Token</th><th>Counter</th><th>Waited</th></tr></thead><tbody>
                  {d.serving.map(e => <tr key={e.id}><td className="mono">#{e.token_number}</td><td>{e.counter_id !== null ? byId.get(e.counter_id) : '—'}</td><td className="mono">{mins(e.waiting_time_seconds)}</td></tr>)}
                </tbody></table></div>
              )}
            </Card>
          </>)}
        </Async>
      </>)}
    </div>
  )
}
