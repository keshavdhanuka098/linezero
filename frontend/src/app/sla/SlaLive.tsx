import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { PolicyList, SlaMonitor } from '../../api/slaTypes'
import { num, pct } from '../../lib/adaptive'
import { SLA_ORDER, SLA_STATUS, probPct, remainingText, rowClass, sortCustomers } from '../../lib/sla'
import { Card, Chip, EmptyState, Skeleton, toast } from '../ui/kit'
import { KindTag, Note } from '../intelligence/shared'

export default function SlaLive({ mon, policies, queueId, onChanged }: { mon: SlaMonitor | null; policies: PolicyList | null; queueId: number; onChanged(): void }) {
  const [busyId, setBusyId] = useState<number | null>(null)
  if (!mon) return <Skeleton h={260} />
  if (!mon.configured) return null
  const rows = sortCustomers(mon.customers)
  const counts = mon.counts!
  const classes = policies?.policies.map(p => p.service_class) ?? []
  const setClass = async (entryId: number, service_class: string) => {
    setBusyId(entryId)
    try { await api(`/sla/${queueId}/entries/${entryId}/class`, { method: 'POST', body: { service_class } }); toast('Service class updated'); onChanged() }
    catch (e) { toast(errMsg(e), true) } finally { setBusyId(null) }
  }
  const worrying = counts.at_risk + counts.critical + counts.breached
  return (
    <div className="iq-stack">
      <div className="iq-actions">
        {SLA_ORDER.map(k => <Chip key={k} tone={SLA_STATUS[k].tone}>{SLA_STATUS[k].label}: {counts[k]}</Chip>)}
        <span className="twin-note">{mon.serving} being served · {mon.capacity?.active_counters} active counter(s) · {num(mon.capacity?.service_capacity_per_min, 2)} customers/min ({mon.capacity?.service_rate_source.replace(/_/g, ' ')})</span>
      </div>
      {worrying > 0 && <div className="banner warn" role="alert"><AlertTriangle size={16} style={{ flex: 'none', marginTop: 2 }} /><span><b>{worrying} waiting customer{worrying === 1 ? '' : 's'}</b> {counts.breached ? `${counts.breached} already over their SLA` : 'approaching their SLA'}. Open Recommendations to see what could reduce the wait.</span></div>}
      <Card title={`Waiting customers (${rows.length})`} sub="Worst first · refreshes automatically" right={<><KindTag kind="observed" /><KindTag kind="predicted" /></>}>
        {rows.length === 0 ? <EmptyState title="Nobody is waiting" text="Customers appear here as soon as they join the line." /> : (
          <div className="tw"><table className="tbl sla-table" aria-label="Customers waiting, with SLA risk">
            <thead><tr><th>Customer</th><th>Waited</th><th>Predicted total</th><th>SLA target</th><th>Remaining</th><th>Breach probability</th><th>Status</th>{classes.length > 1 && <th>Class</th>}</tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.entry_id} className={rowClass(r.status)} data-status={r.status}>
                <td><b>Token {r.token}</b><div className="twin-note">Queue {r.queue_id} · position {r.position}</div></td>
                <td className="mono">{num(r.current_wait_min, 1)} min</td>
                <td className="mono">{r.predicted_total_wait_min == null ? <span title="No active counter: no finite wait can be predicted">no prediction</span> : `${num(r.predicted_total_wait_min, 1)} min`}</td>
                <td className="mono">{r.sla_target_min} min{r.class_fallback ? <div className="twin-note">standard (class has no policy)</div> : null}</td>
                <td className={`mono${r.remaining_sla_min < 0 ? ' neg' : ''}`}>{remainingText(r.remaining_sla_min)}</td>
                <td><div className="sla-prob" title={`P(wait exceeds target) = ${pct(r.breach_probability, 1)}`}><span className="mono">{probPct(r.breach_probability)}</span><i style={{ width: `${Math.round(r.breach_probability * 100)}%` }} /></div></td>
                <td><Chip tone={SLA_STATUS[r.status].tone}>{SLA_STATUS[r.status].label}</Chip></td>
                {classes.length > 1 && <td><select className="sel sm" aria-label={`Service class of token ${r.token}`} value={r.service_class} disabled={busyId === r.entry_id} onChange={e => void setClass(r.entry_id, e.target.value)}>
                  {classes.map(c => <option key={c} value={c}>{c}</option>)}</select></td>}
              </tr>))}</tbody>
          </table></div>)}
        <Note>Breach probability is the chance the customer’s total wait exceeds their SLA target, given their position, the counters’ current service rate and the time already waited.</Note>
      </Card>
      <details><summary className="twin-note">Model assumptions</summary><ul className="twin-note">{mon.assumptions?.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
    </div>
  )
}
