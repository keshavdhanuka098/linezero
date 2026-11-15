import { useState } from 'react'
import { HeartPulse, Plus, Trash2 } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { CompareResponse, ImprovementSet, RecommendResponse, Recommendation, RecoverResponse, TwinAction } from '../../api/twinTypes'
import { Card, Chip, EmptyState, Field, Seg, Spinner, cx, toast } from '../ui/kit'
import { buildConfig, nextId, type ActionRow, type FormErrors, type TwinForm } from '../../lib/twinPlayback'
import { ImprovementTable, f1 } from './common'
import type { RunView } from './TwinPage'

type Mode = 'manual' | 'assisted' | 'automatic'
interface Props { form: TwinForm; setForm(f: TwinForm): void; errors: FormErrors; onShowRun(r: RunView): void; onOpenLab(): void; onRunForm(f: TwinForm): void }

const toRow = (a: TwinAction): ActionRow => ({ id: nextId(), type: a.type, at: String(a.at), counter: a.counter ?? 0, factor: String(a.factor ?? 1.15) })
const ACTION_LABEL: Record<TwinAction['type'], string> = { activate_counter: 'Activate counter', deactivate_counter: 'Close counter', boost_speed: 'Staff assist (speed ×)' }

export default function HealPanel({ form, setForm, errors, onShowRun, onOpenLab, onRunForm }: Props) {
  const [mode, setMode] = useState<Mode>('assisted')
  const [busy, setBusy] = useState(false)
  const [rec, setRec] = useState<RecommendResponse | null>(null)
  const [auto, setAuto] = useState<RecoverResponse | null>(null)
  const [manual, setManual] = useState<{ imp: ImprovementSet; labels: string[] } | null>(null)
  const [maxCost, setMaxCost] = useState('')
  const invalid = Object.keys(errors).length > 0
  const n = Math.max(1, Number(form.num_counters) || 1)
  const budget = maxCost.trim() === '' ? null : Number(maxCost)
  const body = () => ({ configuration: buildConfig({ ...form, actions: mode === 'manual' ? form.actions : [] }), replications: Math.max(2, Math.min(20, Number(form.replications) || 6)), seed: Number(form.seed), ...(budget !== null && Number.isFinite(budget) ? { max_extra_cost: budget } : {}) })
  const guard = (fn: () => Promise<void>) => async () => { setBusy(true); try { await fn() } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) } }

  const setAction = (id: number, patch: Partial<ActionRow>) => setForm({ ...form, actions: form.actions.map(a => (a.id === id ? { ...a, ...patch } : a)) })

  const runManual = guard(async () => {
    const withActions = buildConfig(form)
    const without = buildConfig({ ...form, actions: [], recovery: { ...form.recovery, enabled: false } })
    const r = await api<CompareResponse>('/twin/compare', { method: 'POST', body: { scenarios: [{ name: 'Unmanaged', configuration: without }, { name: 'With my actions', configuration: withActions }], replications: Math.max(2, Number(form.replications) || 6), seed: Number(form.seed) } })
    setManual({ imp: r.improvements[0].metrics, labels: r.labels })
  })
  const analyse = guard(async () => { setRec(await api<RecommendResponse>('/twin/recommend', { method: 'POST', body: body() })) })
  const search = guard(async () => { setAuto(await api<RecoverResponse>('/twin/recover', { method: 'POST', body: body() })) })

  const apply = (r: Recommendation) => {
    const patch = r.patch as { counter_assignment?: TwinForm['assignment'] }
    const next: TwinForm = { ...form, actions: [...form.actions, ...r.actions.map(toRow)], assignment: patch.counter_assignment ?? form.assignment }
    setForm(next); onOpenLab(); onRunForm(next)
  }

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Card title="Self-healing optimization" sub="Recovery plans are evaluated by simulation only. LineZero never changes real queues, counters or customers."
        right={<Seg<Mode> value={mode} onChange={setMode} label="Recovery mode" options={[{ v: 'manual', l: 'Manual' }, { v: 'assisted', l: 'AI-assisted' }, { v: 'automatic', l: 'Automatic (simulation)' }]} />}>
        <p className="twin-note" style={{ marginTop: 0 }}>
          {mode === 'manual' && 'You schedule recovery actions on the scenario below; the twin shows what they would have changed compared with doing nothing.'}
          {mode === 'assisted' && 'The twin diagnoses the scenario you built in the What-if lab, simulates each candidate intervention on the same random seeds and ranks them. Ranking is computed by simulation; Gemini (if enabled) only explains it in the Explain tab.'}
          {mode === 'automatic' && 'The twin searches reactive recovery policies (open a closed counter, then add assisting staff when the queue stays long) and plays back the best one inside the simulation.'}
        </p>
        <div className="toolbar" style={{ alignItems: 'flex-end' }}>
          {mode !== 'manual' && <Field label="Max extra cost (optional)" hint="counter-hours × cost/hour"><input className="in" style={{ width: 150 }} inputMode="decimal" value={maxCost} onChange={e => setMaxCost(e.target.value)} placeholder="no limit" /></Field>}
          {mode === 'manual' && <button className="btn sm" onClick={() => setForm({ ...form, actions: [...form.actions, { id: nextId(), type: 'activate_counter', at: '30', counter: Math.min(n - 1, form.actions.length), factor: '1.15' }] })}><Plus size={13} />Add action</button>}
          {mode === 'manual' && <button className="btn p" disabled={busy || invalid || form.actions.length === 0} onClick={runManual}>{busy ? <Spinner /> : <HeartPulse size={16} />}Simulate my actions</button>}
          {mode === 'assisted' && <button className="btn p" disabled={busy || invalid} onClick={analyse}>{busy ? <Spinner /> : <HeartPulse size={16} />}Diagnose and recommend</button>}
          {mode === 'automatic' && <button className="btn p" disabled={busy || invalid} onClick={search}>{busy ? <Spinner /> : <HeartPulse size={16} />}Find best recovery policy</button>}
        </div>
        {invalid && <div className="err" role="alert" style={{ marginTop: 6 }}>The scenario has errors. Fix them in the What-if lab first.</div>}
        <p className="twin-note" style={{ marginBottom: 0 }}>Scenario under analysis: {form.num_counters} counters, {form.arrival_rate}/min arrivals, {form.duration} min, {form.outages.length} failure(s), {form.surges.length} surge(s), {form.standby.length} reserve counter(s){form.staff ? `, ${form.staff} staffed` : ''}. Edit it in the What-if lab.</p>
      </Card>

      {mode === 'manual' && (
        <Card title="Manual recovery actions" sub="Applied at the given simulation time">
          {form.actions.length === 0 && <EmptyState title="No actions yet" text="Add an action such as activating a reserve counter at minute 30." />}
          {form.actions.map(a => (
            <div key={a.id}>
              <div className="row-in">
                <label className="fld"><span>Action</span><select className="sel" value={a.type} onChange={e => setAction(a.id, { type: e.target.value as TwinAction['type'] })}>{(Object.keys(ACTION_LABEL) as TwinAction['type'][]).map(t => <option key={t} value={t}>{ACTION_LABEL[t]}</option>)}</select></label>
                <label className="fld"><span>At (min)</span><input className="in" inputMode="decimal" value={a.at} onChange={e => setAction(a.id, { at: e.target.value })} /></label>
                {a.type === 'boost_speed'
                  ? <label className="fld"><span>Speed ×</span><input className="in" inputMode="decimal" value={a.factor} onChange={e => setAction(a.id, { factor: e.target.value })} /></label>
                  : <label className="fld"><span>Counter</span><select className="sel" value={a.counter} onChange={e => setAction(a.id, { counter: Number(e.target.value) })}>{Array.from({ length: n }, (_, i) => <option key={i} value={i}>Counter {i + 1}</option>)}</select></label>}
                <button className="btn sm g ic" aria-label="Remove action" onClick={() => setForm({ ...form, actions: form.actions.filter(x => x.id !== a.id) })}><Trash2 size={14} /></button>
              </div>
              {errors[`action${a.id}`] && <div className="err" role="alert">{errors[`action${a.id}`]}</div>}
            </div>
          ))}
          <p className="twin-note">Opening a counter only helps if it was closed (reserve or unstaffed). The speed multiplier is your assumption, not measured data.</p>
          {manual && <><h4 style={{ margin: '12px 0 6px' }}>{manual.labels[0]} → {manual.labels[1]}</h4><ImprovementTable imp={manual.imp} before="Unmanaged" after="With actions" /></>}
        </Card>
      )}

      {mode === 'assisted' && rec && (
        <Card title="Diagnosis" sub={`${rec.replications} replications · ${rec.score_formula}`}>
          <div className="kv">
            <div><small>First congestion</small><b>{rec.diagnosis.first_congestion_at === null ? 'none' : `${f1(rec.diagnosis.first_congestion_at, 1)} min`}</b></div>
            <div><small>Avg wait / P95</small><b>{f1(rec.diagnosis.avg_wait_min)} / {f1(rec.diagnosis.p95_wait_min)} min</b></div>
            <div><small>Max queue</small><b>{f1(rec.diagnosis.max_queue, 1)}</b></div>
            <div><small>Most loaded</small><b>{rec.diagnosis.most_loaded_counter ? `${rec.diagnosis.most_loaded_counter.name} (${f1(rec.diagnosis.most_loaded_counter.utilization_while_open * 100, 0)}%)` : '—'}</b></div>
            <div><small>Closed / reserve</small><b>{rec.diagnosis.closed_counters.join(', ') || 'none'}</b></div>
            <div><small>Failed</small><b>{rec.diagnosis.failed_counters.join(', ') || 'none'}</b></div>
          </div>
          {rec.notes.map(t => <p key={t} className="twin-note">{t}</p>)}
        </Card>
      )}
      {mode === 'assisted' && rec && (
        <div className="twin-cards">
          {rec.recommendations.map(r => (
            <div key={r.id} className={cx('rec', r.id === rec.recommended_id && 'best')}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b>#{r.rank} {r.label}</b>{r.id === rec.recommended_id && <Chip tone="ok">recommended</Chip>}</div>
              <span className="twin-note">{r.description}</span>
              <div className="kv">
                <div><small>Avg wait</small><b>{f1(r.improvement.avg_waiting_time.before)} → {f1(r.improvement.avg_waiting_time.after)} min</b></div>
                <div><small>P95 wait</small><b>{f1(r.improvement.p95_waiting_time.before)} → {f1(r.improvement.p95_waiting_time.after)}</b></div>
                <div><small>Max queue</small><b>{f1(r.improvement.max_queue_length.before, 1)} → {f1(r.improvement.max_queue_length.after, 1)}</b></div>
                <div><small>Extra cost</small><b>{f1(r.extra_cost)}</b></div>
              </div>
              <div className="toolbar"><Chip tone={r.significant && r.improves ? 'ok' : undefined}>{r.significant ? (r.improves ? 'clear improvement' : 'clearly worse') : 'within noise'}</Chip>{!r.within_budget && <Chip tone="warn">over budget</Chip>}</div>
              {r.assumptions.map(x => <span key={x} className="twin-note">Assumption: {x}</span>)}
              {(r.actions.length > 0 || Object.keys(r.patch).length > 0) && <button className="btn sm t" disabled={busy} onClick={() => apply(r)}>Apply to scenario and simulate</button>}
            </div>
          ))}
        </div>
      )}
      {mode === 'assisted' && rec && <p className="twin-note">{rec.disclaimer}</p>}

      {mode === 'automatic' && auto && (
        <Card title="Automatic recovery result" sub={`${auto.policies_evaluated} policies simulated · ${auto.replications} replications each`} right={<Chip tone="vio">simulation only</Chip>}>
          {auto.chosen && auto.before_after && auto.recovered ? (<>
            <p style={{ marginTop: 0 }}>Chosen policy: when the queue stays at {auto.chosen.policy.queue_threshold}+ for {auto.chosen.policy.sustain} min, open up to <b>{auto.chosen.policy.max_activations}</b> closed counter(s){auto.chosen.policy.boost_factor > 1 ? `, then add assisting staff (service ×${auto.chosen.policy.boost_factor})` : ''}.</p>
            <ImprovementTable imp={auto.before_after} before="Unmanaged" after="Auto-recovered" />
            <div className="toolbar" style={{ marginTop: 10 }}>
              <button className="btn sm t" onClick={() => { onShowRun({ label: 'Unmanaged (before)', playback: auto.baseline.primary, summary: auto.baseline.summary, stats: undefined, counters: [], replications: auto.replications }); onOpenLab() }}>Play before</button>
              <button className="btn sm t" onClick={() => { onShowRun({ label: 'Auto-recovered (after)', playback: auto.recovered!.primary, summary: auto.recovered!.summary, stats: auto.recovered!.stats, counters: [], replications: auto.replications }); onOpenLab() }}>Play recovered run</button>
            </div>
          </>) : <p style={{ marginTop: 0 }}>{auto.notes.join(' ')}</p>}
          <details style={{ marginTop: 10 }}><summary>Top policies evaluated</summary>
            <div className="tw"><table className="tbl"><thead><tr><th>Threshold</th><th>Max activations</th><th>Boost</th><th>Score</th><th>Extra cost</th><th>Evidence</th></tr></thead><tbody>
              {auto.candidates.map((c, i) => <tr key={i}><td className="mono">{c.policy.queue_threshold}</td><td className="mono">{c.policy.max_activations}</td><td className="mono">×{c.policy.boost_factor}</td><td className="mono">{f1(c.score)}</td><td className="mono">{f1(c.extra_cost)}</td><td className="twin-note">{c.significant ? 'clear' : 'within noise'}</td></tr>)}
            </tbody></table></div>
            <p className="twin-note">{auto.score_formula}. {auto.disclaimer}</p>
          </details>
        </Card>
      )}
    </div>
  )
}
