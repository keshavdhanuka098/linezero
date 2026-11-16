import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Play, X } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { Candidate, CostModel, Evaluation, Intervention } from '../../api/adaptiveTypes'
import { STATUS_LABEL, STATUS_TONE, nextActions, num, pct, signed, typeLabel } from '../../lib/adaptive'
import { Card, Chip, Confirm, ErrorState, Kpi, Skeleton, Spinner, toast } from '../ui/kit'
import { Gate, KindTag, Legend as KindLegend, Note, OperatorField, ProvenanceBanner, useLoad, useOperator } from './shared'

const DEFAULT_COST: CostModel = { counter_hour_cost: 1, assist_staff_hour_cost: 0.5, diversion_cost_per_customer: 0.25, max_extra_cost: null, max_assist_staff: 2, cost_weight: 0.25 }

function CostField({ label, value, onChange, step = 0.05 }: { label: string; value: number | null; onChange(v: number | null): void; step?: number }) {
  return (
    <label className="iq-sel">{label}
      <input className="in" type="number" min={0} step={step} value={value ?? ''} placeholder={value === null ? 'no cap' : undefined}
        onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} aria-label={label} />
    </label>
  )
}

function Decision({ iv, op, note, onChanged }: { iv: Intervention; op: string; note: string; onChanged(): void }) {
  const [confirmApplied, setConfirmApplied] = useState(false)
  const [busy, setBusy] = useState(false)
  const actions = nextActions(iv.status)
  const call = async (path: 'approve' | 'reject' | 'applied') => {
    if (!op.trim()) { toast('Enter your operator name first', true); return }
    setBusy(true)
    try {
      const r = await api<{ message: string }>(`/interventions/item/${iv.id}/${path}`, { method: 'POST', body: { operator: op.trim(), note: note.trim() || null } })
      toast(r.message); onChanged()
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false); setConfirmApplied(false) }
  }
  if (actions.length === 0 || (actions.length === 1 && actions[0] === 'outcome')) return null
  return (
    <div className="iq-actions">
      {actions.includes('approve') && <button className="btn p sm" disabled={busy} onClick={() => void call('approve')}><Check size={12} />Approve</button>}
      {actions.includes('applied') && <button className="btn p sm" disabled={busy} onClick={() => setConfirmApplied(true)}>I carried this out</button>}
      {actions.includes('reject') && <button className="btn sm" disabled={busy} onClick={() => void call('reject')}><X size={12} />Reject</button>}
      {confirmApplied && <Confirm title="Confirm it was carried out" confirmLabel="Yes, it was applied" onConfirm={() => void call('applied')} onClose={() => setConfirmApplied(false)}
        text="LineZero never changes counters or queues. Confirm only if you or your team actually made this change in the real world; the outcome will be measured against the time you confirm." />}
    </div>
  )
}

function CandidateCard({ c, iv, op, note, onChanged }: { c: Candidate; iv?: Intervention; op: string; note: string; onChanged(): void }) {
  const w = c.wait_reduction_min
  return (
    <article className={`iq-cand${c.is_recommended ? ' best' : ''}`} aria-label={c.label}>
      <header>
        {c.rank && <Chip tone={c.is_recommended ? 'ok' : undefined}>#{c.rank}{c.is_recommended ? ' recommended' : ''}</Chip>}
        <h4>{c.label}</h4><KindTag kind="simulated" />
        {iv && <Chip tone={STATUS_TONE[iv.status]}>{STATUS_LABEL[iv.status]}</Chip>}
      </header>
      <p className="twin-note" style={{ margin: 0 }}>{c.description}</p>
      <dl className="iq-kv">
        <dt>Wait reduction (simulated)</dt><dd>{w.mean != null ? `${signed(w.mean)} min${w.ci95 != null ? ` ± ${num(w.ci95)}` : ''}` : '—'}</dd>
        <dt>Average wait after</dt><dd>{num(c.summary.avg_waiting_time)} min</dd>
        <dt>P95 wait reduction</dt><dd>{num(c.p95_wait_reduction_min)} min</dd>
        <dt>Extra cost</dt><dd>{num(c.extra_cost.total)} units</dd>
        <dt>Net value</dt><dd>{signed(c.net_value)}</dd>
        <dt>Clear beyond noise</dt><dd>{c.significant ? 'yes' : 'no'}</dd>
        <dt>Confidence</dt><dd>{pct(c.confidence.value)}</dd>
      </dl>
      <details><summary className="twin-note">Assumptions (not measured data)</summary><ul className="twin-note">{c.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
      {iv && <Decision iv={iv} op={op} note={note} onChanged={onChanged} />}
    </article>
  )
}

function Panel({ queueId }: { queueId: number }) {
  const [params] = useSearchParams()
  const riskId = Number(params.get('risk')) || null
  const hist = useLoad<{ provenance: Evaluation['provenance']; interventions: Intervention[] }>(`/interventions/${queueId}/history`)
  const [cost, setCost] = useState<CostModel>(DEFAULT_COST)
  const [horizon, setHorizon] = useState(60)
  const [reps, setReps] = useState(10)
  const [seed, setSeed] = useState(2026)
  const [res, setRes] = useState<Evaluation | null>(null)
  const [busy, setBusy] = useState(false)
  const [op, setOp] = useOperator()
  const [note, setNote] = useState('')
  const set = <K extends keyof CostModel>(k: K, v: CostModel[K] | null) => setCost(c => ({ ...c, [k]: v === null && k !== 'max_extra_cost' ? DEFAULT_COST[k] : v }))

  const evaluate = async () => {
    setBusy(true)
    try {
      const r = await api<Evaluation>(`/interventions/${queueId}/evaluate`, { method: 'POST', body: { horizon_min: horizon, replications: reps, seed, cost_model: cost, risk_event_id: riskId } })
      setRes(r); void hist.reload(); toast('Simulated. Nothing has been changed.')
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const ivById = new Map((hist.data?.interventions ?? []).map(i => [i.id, i]))
  const rows = hist.data?.interventions ?? []

  return (
    <div className="iq-stack">
      <ProvenanceBanner p={res?.provenance ?? hist.data?.provenance} />
      <div className="iq-banner real" role="note"><Chip tone="vio">Simulation only</Chip><span>LineZero proposes; people decide and act. Approving records your decision. It does not change any counter or queue, and an intervention counts as applied only when you confirm you carried it out.</span></div>

      <Card title="Simulate recovery options" sub={riskId ? `Linked to risk event #${riskId}` : 'From the queue’s current state: customers waiting, counters open, service rates'} right={<KindTag kind="simulated" />}>
        <div className="iq-bar">
          <label className="iq-sel">Horizon (min)<input className="in" type="number" min={10} max={240} value={horizon} onChange={e => setHorizon(Number(e.target.value))} aria-label="Horizon in minutes" /></label>
          <label className="iq-sel">Replications<input className="in" type="number" min={3} max={20} value={reps} onChange={e => setReps(Number(e.target.value))} aria-label="Replications" /></label>
          <label className="iq-sel">Seed<input className="in" type="number" min={0} value={seed} onChange={e => setSeed(Number(e.target.value))} aria-label="Seed" /></label>
        </div>
        <div className="iq-bar">
          <CostField label="Counter-hour cost" value={cost.counter_hour_cost} onChange={v => set('counter_hour_cost', v)} />
          <CostField label="Assisting staff / hour" value={cost.assist_staff_hour_cost} onChange={v => set('assist_staff_hour_cost', v)} />
          <CostField label="Cost per diverted customer" value={cost.diversion_cost_per_customer} onChange={v => set('diversion_cost_per_customer', v)} />
          <CostField label="Max extra cost (budget)" value={cost.max_extra_cost} onChange={v => set('max_extra_cost', v)} />
          <CostField label="Assisting staff available" value={cost.max_assist_staff} step={1} onChange={v => set('max_assist_staff', v === null ? 0 : Math.round(v))} />
          <CostField label="Cost weight" value={cost.cost_weight} onChange={v => set('cost_weight', v)} />
        </div>
        <div className="iq-actions"><button className="btn p" onClick={() => void evaluate()} disabled={busy}>{busy ? <Spinner /> : <Play size={13} />}Simulate interventions</button></div>
        <Note>Cost figures are your inputs, not measured data. Candidates are ranked by net value = score improvement − cost weight × extra cost.</Note>
      </Card>

      {res && (
        <Card title="Result" sub={`Baseline vs candidates · ${res.horizon_min} simulated minutes · ${res.reproducibility.replications} runs with identical random seeds`} right={<KindTag kind="simulated" />}>
          <div className="grid g4 kp">
            <Kpi label="Baseline average wait" value={num(res.baseline.summary.avg_waiting_time)} unit="min" sub="no change, simulated" />
            <Kpi label="Baseline P95 wait" value={num(res.baseline.summary.p95_waiting_time)} unit="min" />
            <Kpi label="Waiting now" value={res.baseline.starting_state.queue_length} sub="observed starting state" />
            <Kpi label="Rates used" value={res.inputs.calibration_version ? `v${res.inputs.calibration_version}` : 'Nominal'} sub={res.inputs.service_rate_source.replace(/_/g, ' ')} />
          </div>
          <div className="rec" style={{ marginTop: 10 }}><div className="twin-note" style={{ display: 'flex', gap: 6 }}><KindTag kind="explanation" /></div><p className="iq-pre" data-testid="explanation">{res.explanation}</p></div>
          <div className="twin-cards" style={{ marginTop: 10 }}>{res.candidates.filter(c => c.feasible).map(c => <CandidateCard key={c.key} c={c} iv={c.record_id ? ivById.get(c.record_id) : undefined} op={op} note={note} onChanged={() => void hist.reload()} />)}</div>
          {res.not_evaluated.length > 0 && <details style={{ marginTop: 8 }}><summary className="twin-note">Not evaluated ({res.not_evaluated.length})</summary><ul className="twin-note">{res.not_evaluated.map((n, i) => <li key={i}>{n.label ?? n.key}: {n.reason}</li>)}</ul></details>}
          <details style={{ marginTop: 8 }}><summary className="twin-note">Assumptions and reproducibility</summary>
            <ul className="twin-note">{res.global_assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
            <p className="twin-note">Config hash {res.reproducibility.config_hash} · base seed {res.reproducibility.base_seed}. {res.ranking_rule}.</p></details>
        </Card>
      )}

      <Card title="Proposals and decisions" sub="Every simulated candidate that was stored, and what the operator decided" right={<OperatorField name={op} setName={setOp} />}>
        <label className="iq-sel" style={{ marginBottom: 8 }}>Decision note (optional)<input className="in" value={note} maxLength={1000} onChange={e => setNote(e.target.value)} aria-label="Decision note" /></label>
        {hist.err && !hist.data ? <ErrorState text={hist.err} onRetry={hist.reload} /> : !hist.data ? <Skeleton h={80} /> : rows.length === 0 ? <Note>No interventions have been proposed for this queue yet.</Note> : (
          <div className="iq-hist">{rows.slice(0, 30).map(i => (
            <div className="iq-row" key={i.id}>
              <header><span><b>{i.label}</b> <span className="twin-note">· {typeLabel(i.intervention_type)} · {new Date(i.created_at).toLocaleString()}</span></span>
                <span className="iq-actions"><Chip tone={STATUS_TONE[i.status]}>{STATUS_LABEL[i.status]}</Chip>{i.is_recommended && <Chip tone="ok">recommended</Chip>}{i.is_synthetic && <Chip tone="demo">synthetic</Chip>}</span></header>
              <span className="twin-note">Expected wait reduction (simulated): {i.expected?.wait_reduction_min?.mean != null ? `${num(i.expected.wait_reduction_min.mean)} min` : '—'}{i.decided_by ? ` · decided by ${i.decided_by}` : ''}{i.applied_by ? ` · applied by ${i.applied_by}` : ''} · executed by LineZero: no</span>
              <Decision iv={i} op={op} note={note} onChanged={() => void hist.reload()} />
              {i.status === 'applied' && <Note>Record its outcome in Outcome Learning once the measurement window has passed.</Note>}
            </div>))}</div>
        )}
      </Card>
      <KindLegend />
    </div>
  )
}

export default function InterventionsPage() {
  return <Gate title="Autonomous Interventions" sub="Candidate recoveries are simulated, costed and ranked. A human approves and carries out every change.">{id => <Panel queueId={id} />}</Gate>
}
