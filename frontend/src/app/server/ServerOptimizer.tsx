import { useState } from 'react'
import { FilePlus, Sparkles, SlidersHorizontal } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { Allocation, OptMetrics, Optimization } from '../../api/types'
import { useServer } from '../../api/serverStore'
import { numberIn } from '../../lib/validate'
import { Card, Chip, EmptyState, Field, Kpi, PageHeader, Spinner, cx, toast } from '../ui/kit'
import { NoQueues, QueuePicker, n1, pctOf } from './shared'

export default function ServerOptimizer() {
  const queueId = useServer(s => s.queueId)
  const [maxC, setMaxC] = useState('8'), [newC, setNewC] = useState('2'), [reps, setReps] = useState('6')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<Optimization | null>(null)
  const errs = [numberIn(maxC, 1, 100, 'Max counters', true), numberIn(newC, 0, 20, 'New counters', true), numberIn(reps, 2, 30, 'Replications', true)]
  const run = async () => {
    if (queueId === null) return
    setBusy(true)
    try {
      setRes(await api<Optimization>('/optimization/run', { method: 'POST', body: { queue_id: queueId, constraints: { max_active_counters: Number(maxC), allow_new_counters: Number(newC) }, simulation: { duration_minutes: 480, replications: Number(reps) } } }))
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const r = res && res.queue_id === queueId ? res : null
  const saveReport = async () => {
    if (!r) return
    try { await api('/reports/generate', { method: 'POST', body: { report_type: 'optimization_comparison', optimization_id: r.optimization_id } }); toast('Saved to Reports') }
    catch (e) { toast(errMsg(e), true) }
  }
  const w = r?.estimated_improvement.avg_waiting_time_min

  return (
    <div className="page">
      <PageHeader title="Resource Optimizer" sub="Searches counter-allocation candidates and scores each with replicated SimPy simulations." demo={false}>
        <button className="btn" onClick={saveReport} disabled={!r}><FilePlus size={16} />Save as report</button>
        <button className="btn p" onClick={run} disabled={busy || queueId === null || errs.some(Boolean)}>{busy ? <Spinner /> : <Sparkles size={16} />}Run optimization</button>
      </PageHeader>
      {queueId === null ? <NoQueues /> : (<>
        <QueuePicker>
          <Field label="Max active counters" error={errs[0]}><input className={cx('in', errs[0] && 'bad')} style={{ width: 110 }} value={maxC} onChange={e => setMaxC(e.target.value)} /></Field>
          <Field label="New counters allowed" error={errs[1]}><input className={cx('in', errs[1] && 'bad')} style={{ width: 110 }} value={newC} onChange={e => setNewC(e.target.value)} /></Field>
          <Field label="Replications" error={errs[2]} hint="More = tighter estimate, slower"><input className={cx('in', errs[2] && 'bad')} style={{ width: 110 }} value={reps} onChange={e => setReps(e.target.value)} /></Field>
        </QueuePicker>
        {!r || !w ? <Card><EmptyState icon={SlidersHorizontal} title="No optimization yet" text="Run an optimization to compare the current allocation with the best candidate found. It can take several seconds." /></Card> : (<>
          <div className="banner"><Sparkles size={16} style={{ flex: 'none', marginTop: 2 }} /><span>{r.explanation} <b>{r.details.optimality}</b></span></div>
          <div className="grid g4 kp">
            <Kpi label="Avg wait (current → proposed)" value={<>{n1(w.current)} <small>→</small> {n1(w.proposed)}</>} unit="min" sub={!r.estimated_improvement.is_improvement ? 'no improvement found' : w.percent_reduction ? `${n1(w.percent_reduction, 0)}% lower` : 'wait unchanged'} tone={r.estimated_improvement.is_improvement ? undefined : 'warn'} />
            <Kpi label="Statistical confidence" value={<Chip tone={w.paired_difference.significant ? 'ok' : 'warn'}>{w.paired_difference.significant ? 'significant' : 'not significant'}</Chip>} sub={`95% CI ${n1(w.paired_difference.ci95[0])} to ${n1(w.paired_difference.ci95[1])} min`} />
            <Kpi label="Counters" value={<>{r.current_allocation.active_counter_count} <small>→</small> {r.proposed_allocation.active_counter_count}</>} sub={r.resource_requirements.new_counters_required ? `${r.resource_requirements.new_counters_required} new required` : 'no new counters'} />
            <Kpi label="Cost / hour" value={<>{n1(r.current_allocation.cost_per_hour)} <small>→</small> {n1(r.proposed_allocation.cost_per_hour)}</>} sub={`${r.resource_requirements.cost_change_per_hour >= 0 ? '+' : ''}${n1(r.resource_requirements.cost_change_per_hour)} per hour`} />
          </div>
          <div className="grid g2">
            <AllocCard title="Current allocation" a={r.current_allocation} m={r.current_metrics} />
            <AllocCard title="Proposed allocation" a={r.proposed_allocation} m={r.proposed_metrics} proposed />
          </div>
          <Card title="Constraints & assumptions">
            <div className="toolbar" style={{ flexWrap: 'wrap' }}>{r.resource_requirements.constraint_checks.map(c => <Chip key={c.name} tone={c.ok ? 'ok' : 'crit'}>{c.name.replace(/_/g, ' ')}</Chip>)}</div>
            <ul className="hint" style={{ margin: '10px 0 0', paddingLeft: 18 }}>{r.details.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </Card>
        </>)}
      </>)}
    </div>
  )
}

function AllocCard({ title, a, m, proposed }: { title: string; a: Allocation; m: OptMetrics; proposed?: boolean }) {
  return (
    <Card title={title} sub={`Assignment policy: ${a.assignment_policy.replace('_', ' ')}`} right={proposed ? <Chip tone="ok">Proposed</Chip> : undefined}>
      <div className="tw"><table className="tbl"><thead><tr><th>Counter</th><th>Rate /min</th><th>Action</th></tr></thead><tbody>
        {a.counters.map(c => <tr key={c.key}><td>{c.name ?? c.key}</td><td className="mono">{n1(c.service_rate_per_min, 2)}</td><td><Chip tone={c.action === 'keep' ? undefined : c.action === 'add_new' ? 'vio' : 'warn'}>{c.action.replace('_', ' ')}</Chip></td></tr>)}
      </tbody></table></div>
      <div className="hint" style={{ marginTop: 10 }}>avg wait {n1(m.avg_waiting_time_min)} min · p95 {n1(m.p95_waiting_time_min)} min · utilization {pctOf(m.avg_utilization)} · demand/capacity {n1(m.demand_to_capacity_ratio, 2)}</div>
    </Card>
  )
}
