import { useState } from 'react'
import { GitCompare, Play, Trash2 } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { SimCompare, SimResults, SimRun } from '../../api/types'
import { Card, Chip, EmptyState, Field, Kpi, PageHeader, Spinner, cx, toast } from '../ui/kit'
import { numberIn } from '../../lib/validate'
import { Async, ApiChartCard, n1, pctOf, useAsync } from './shared'

interface Form { arrival_rate: string; mean_service_time: string; num_counters: string; duration: string; seed: string; arrival_distribution: string; service_distribution: string; abandon: boolean; patience: string; assignment: string }
const INIT: Form = { arrival_rate: '1.2', mean_service_time: '4', num_counters: '5', duration: '120', seed: '2026', arrival_distribution: 'poisson', service_distribution: 'exponential', abandon: false, patience: '10', assignment: 'longest_idle' }

export default function ServerSimulator() {
  const [f, setF] = useState<Form>(INIT)
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<SimRun | null>(null)
  const [cmp, setCmp] = useState<SimCompare | null>(null)
  const history = useAsync(() => api<SimRun[]>('/simulations', { params: { limit: 15 } }), [])

  const errs = {
    arrival_rate: numberIn(f.arrival_rate, 0.01, 100, 'Arrival rate'),
    mean_service_time: numberIn(f.mean_service_time, 0.1, 240, 'Service time'),
    num_counters: numberIn(f.num_counters, 1, 100, 'Counters', true),
    duration: numberIn(f.duration, 1, 10080, 'Duration', true),
    seed: numberIn(f.seed, 0, 4294967295, 'Seed', true),
    patience: f.abandon ? numberIn(f.patience, 0.1, 1000, 'Patience') : undefined,
  }
  const invalid = Object.values(errs).some(Boolean)
  const set = (k: keyof Form, v: string | boolean) => setF(p => ({ ...p, [k]: v }))
  const config = (counters = Number(f.num_counters)) => ({
    arrival_rate: Number(f.arrival_rate), mean_service_time: Number(f.mean_service_time), num_counters: counters, duration: Number(f.duration), seed: Number(f.seed),
    arrival_distribution: f.arrival_distribution, service_distribution: f.service_distribution, counter_assignment: f.assignment,
    abandonment_enabled: f.abandon, mean_patience: f.abandon ? Number(f.patience) : null,
  })

  const exec = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn(); void history.reload() } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const runOne = () => exec(async () => { setCmp(null); setRun(await api<SimRun>('/simulations/run', { method: 'POST', body: { name: 'UI run', configuration: config() } })) })
  const compare = () => exec(async () => {
    const n = Number(f.num_counters)
    const r = await api<SimCompare>('/simulations/compare', { method: 'POST', body: { seed: Number(f.seed), configurations: [{ name: `${n} counters`, configuration: config(n) }, { name: `${n + 1} counters`, configuration: config(n + 1) }] } })
    setRun(null); setCmp(r)
  })
  const remove = async (id: number) => { try { await api(`/simulations/${id}`, { method: 'DELETE' }); void history.reload() } catch (e) { toast(errMsg(e), true) } }

  const input = (k: keyof Form, label: string, hint?: string) => (
    <Field label={label} error={errs[k as keyof typeof errs]} hint={hint}>
      <input className={cx('in', errs[k as keyof typeof errs] && 'bad')} inputMode="decimal" value={String(f[k])} onChange={e => set(k, e.target.value)} />
    </Field>
  )

  return (
    <div className="page">
      <PageHeader title="Queue Simulator" sub="Runs the SimPy discrete-event engine on the LineZero API. Identical seed and parameters give identical results." demo={false}>
        <button className="btn" onClick={compare} disabled={busy || invalid}><GitCompare size={16} />Compare with +1 counter</button>
        <button className="btn p" onClick={runOne} disabled={busy || invalid}>{busy ? <Spinner /> : <Play size={16} />}Run simulation</button>
      </PageHeader>
      <Card title="Configuration" sub="Time unit: minutes">
        <div className="grid g4">
          {input('arrival_rate', 'Arrival rate (/min)')}{input('mean_service_time', 'Mean service time (min)')}{input('num_counters', 'Counters')}{input('duration', 'Duration (min)')}
          {input('seed', 'Random seed')}
          <Field label="Arrival distribution"><select className="sel" value={f.arrival_distribution} onChange={e => set('arrival_distribution', e.target.value)}><option value="poisson">Poisson (random)</option><option value="deterministic">Deterministic</option><option value="uniform">Uniform</option></select></Field>
          <Field label="Service distribution"><select className="sel" value={f.service_distribution} onChange={e => set('service_distribution', e.target.value)}><option value="exponential">Exponential</option><option value="deterministic">Deterministic</option><option value="uniform">Uniform</option><option value="lognormal">Lognormal</option></select></Field>
          <Field label="Counter assignment"><select className="sel" value={f.assignment} onChange={e => set('assignment', e.target.value)}><option value="longest_idle">Longest idle first</option><option value="lowest_index">Lowest index first</option></select></Field>
          <Field label="Abandonment"><label style={{ display: 'flex', gap: 8, alignItems: 'center', height: 38 }}><input type="checkbox" checked={f.abandon} onChange={e => set('abandon', e.target.checked)} />Customers leave if kept waiting</label></Field>
          {f.abandon && input('patience', 'Mean patience (min)')}
        </div>
      </Card>

      {run?.results && <SimResultView r={run.results} title={`Run #${run.id}`} runtime={run.runtime_ms} />}
      {cmp && (
        <Card title="Comparison" sub="Same seed for both configurations">
          <div className="tw"><table className="tbl"><thead><tr><th>Configuration</th><th>Avg wait</th><th>p95 wait</th><th>Max queue</th><th>Utilization</th><th>Served</th><th>Abandoned</th></tr></thead><tbody>
            {cmp.runs.map(r => r.results && <tr key={r.id}><td>{r.name}</td><td className="mono">{n1(r.results.avg_waiting_time, 2)} min</td><td className="mono">{n1(r.results.p95_waiting_time, 2)} min</td><td className="mono">{r.results.max_queue_length}</td><td className="mono">{pctOf(r.results.avg_utilization)}</td><td className="mono">{r.results.total_served}</td><td className="mono">{r.results.abandoned}</td></tr>)}
          </tbody></table></div>
        </Card>
      )}

      <Card title="Run history" sub="Stored on the server">
        <Async loading={history.loading} error={history.error} onRetry={history.reload} hasData={!!history.data}>
          {history.data && history.data.length === 0 ? <EmptyState title="No runs yet" /> : (
            <div className="tw"><table className="tbl"><thead><tr><th>#</th><th>Name</th><th>Counters</th><th>Rate</th><th>Avg wait</th><th>Utilization</th><th>When</th><th /></tr></thead><tbody>
              {history.data?.map(r => (
                <tr key={r.id}><td className="mono">{r.id}</td><td>{r.name ?? '—'}</td><td className="mono">{r.configuration.num_counters}</td><td className="mono">{r.configuration.arrival_rate}</td>
                  <td className="mono">{r.results ? `${n1(r.results.avg_waiting_time, 2)} min` : '—'}</td><td className="mono">{r.results ? pctOf(r.results.avg_utilization) : '—'}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td><button className="btn sm g ic" aria-label={`Delete run ${r.id}`} onClick={() => remove(r.id)}><Trash2 size={14} /></button></td></tr>
              ))}
            </tbody></table></div>
          )}
        </Async>
      </Card>
    </div>
  )
}

function SimResultView({ r, title, runtime }: { r: SimResults; title: string; runtime: number | null }) {
  const t = r.theoretical
  const counters = r.counters.map(c => ({ x: `Counter ${c.counter_index + 1}`, y: c.utilization }))
  return (<>
    <div className="grid g4 kp">
      <Kpi label="Average wait" value={n1(r.avg_waiting_time, 2)} unit="min" sub={`p95 ${n1(r.p95_waiting_time, 2)} · max ${n1(r.max_waiting_time, 1)}`} />
      <Kpi label="Utilization" value={pctOf(r.avg_utilization)} bar={r.avg_utilization} tone={r.avg_utilization >= 0.92 ? 'hot' : undefined} />
      <Kpi label="Served / arrived" value={`${r.total_served} / ${r.total_arrivals}`} sub={`${r.abandoned} abandoned · ${r.customers_remaining} unfinished`} />
      <Kpi label="Queue length" value={n1(r.avg_queue_length, 2)} sub={`max ${r.max_queue_length} · throughput ${n1(r.throughput, 2)}/min`} />
    </div>
    <div className="grid g2">
      <ApiChartCard h={220} chart={{ type: 'bar', title: `${title} · counter utilization`, x: { label: 'Counter', type: 'category' }, y: { label: 'Utilization' }, series: [{ key: 'u', name: 'Utilization', data: counters }] }} />
      <Card title="Theoretical comparison" sub={t?.model ?? 'Queueing theory'} right={<Chip>{`seed ${r.seed_used}${runtime !== null ? ` · ${runtime.toFixed(0)} ms` : ''}`}</Chip>}>
        {t?.applicable ? (
          <div className="tw"><table className="tbl"><tbody>
            <tr><td>Steady-state stable</td><td className="mono">{t.stable ? 'yes' : 'no'}</td></tr>
            <tr><td>Theoretical utilization</td><td className="mono">{pctOf(t.utilization)}</td></tr>
            <tr><td>Theoretical avg wait</td><td className="mono">{t.avg_waiting_time === undefined || t.avg_waiting_time === null ? '—' : `${n1(t.avg_waiting_time, 2)} min`}</td></tr>
            <tr><td>Simulated avg wait</td><td className="mono">{n1(r.avg_waiting_time, 2)} min</td></tr>
          </tbody></table></div>
        ) : <EmptyState title="No closed-form model" text="Theory does not apply to this configuration." />}
        {t?.note && <p className="hint" style={{ marginTop: 8 }}>{t.note}</p>}
      </Card>
    </div>
  </>)
}
