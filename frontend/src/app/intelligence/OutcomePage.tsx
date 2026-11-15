import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { RefreshCcw, Target } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { CycleResult, Intervention, Learning, LearningStats, Outcome, Overview } from '../../api/adaptiveTypes'
import { VERDICT, VERIFICATION, num, pct, signed, typeLabel } from '../../lib/adaptive'
import { Card, Chip, ErrorState, Kpi, Seg, Skeleton, Spinner, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, axisProps, gridProps } from '../charts/theme'
import { Gate, KindTag, Legend as KindLegend, Note, OperatorField, ProvenanceBanner, useLoad, useOperator } from './shared'

function Stats({ title, s, kind }: { title: string; s: LearningStats; kind: keyof typeof VERIFICATION }) {
  const v = VERIFICATION[kind]
  return (
    <div className="fc"><h4>{title}</h4>
      {s.n === 0 ? <p className="twin-note" style={{ margin: 0 }}>No outcomes yet.</p> : (
        <dl><dt>Outcomes compared</dt><dd>{s.n}</dd><dt>Mean error (observed − expected)</dt><dd>{signed(s.mean_error_min)} min</dd><dt>Mean absolute error</dt><dd>{num(s.mean_abs_error_min)} min</dd>
          <dt>Simulation too optimistic</dt><dd>{s.over_optimistic}</dd><dt>Too pessimistic</dt><dd>{s.under_optimistic}</dd><dt>About as expected</dt><dd>{s.as_expected}</dd></dl>)}
      <p className="twin-note" style={{ margin: '6px 0 0' }}><Chip tone={v.tone}>{v.label}</Chip> {v.text}</p>
    </div>
  )
}

function OutcomeView({ o }: { o: Outcome }) {
  const v = VERIFICATION[o.verification]
  const c = o.comparison
  return (
    <div className="iq-outcome">
      <div className="iq-actions"><Chip tone={v.tone}>{v.label}</Chip>{o.calibration_eligible && <Chip tone="ok">clean for calibration</Chip>}<span className="twin-note">recorded by {o.recorded_by}</span></div>
      {o.mode === 'observe' && o.pre && o.post && (
        <div className="tw"><table className="tbl"><thead><tr><th>Measured</th><th>Before</th><th>After</th></tr></thead><tbody>
          <tr><td>Customers served</td><td className="mono">{o.pre.customers_served}</td><td className="mono">{o.post.customers_served}</td></tr>
          <tr><td>Average wait</td><td className="mono">{num(o.pre.avg_wait_min)} min</td><td className="mono">{num(o.post.avg_wait_min)} min</td></tr>
          <tr><td>P95 wait</td><td className="mono">{num(o.pre.p95_wait_min)} min</td><td className="mono">{num(o.post.p95_wait_min)} min</td></tr>
          <tr><td>Arrivals per minute</td><td className="mono">{num(o.pre.arrival_rate_per_min, 3)}</td><td className="mono">{num(o.post.arrival_rate_per_min, 3)}</td></tr>
        </tbody></table></div>)}
      {o.mode === 'manual' && o.reported && <p className="twin-note" style={{ margin: 0 }}>Operator-reported average wait: {num(o.reported.avg_wait_min)} min (not measured by LineZero).</p>}
      {o.observed_wait_reduction_min != null && <dl className="iq-kv">
        <dt>{o.mode === 'observe' ? 'Observed' : 'Reported'} wait reduction</dt><dd>{signed(o.observed_wait_reduction_min)} min{o.reduction_interval95 ? ` (95%: ${signed(o.reduction_interval95.low)} to ${signed(o.reduction_interval95.high)})` : ''}</dd>
        <dt>Simulated expectation</dt><dd>{c?.expected_wait_reduction_min != null ? `${signed(c.expected_wait_reduction_min)} min` : '—'}</dd>
        <dt>Error (observed − expected)</dt><dd>{c?.error_min != null ? `${signed(c.error_min)} min` : '—'}</dd>
        <dt>Reading</dt><dd>{c ? VERDICT[c.verdict] ?? c.verdict : '—'}</dd></dl>}
      {o.confounders?.map((x, i) => <Note key={i}>{x}</Note>)}
      <details><summary className="twin-note">Limits of this comparison</summary><ul className="twin-note">{o.caveats.map((x, i) => <li key={i}>{x}</li>)}</ul></details>
    </div>
  )
}

function Pending({ iv, op, onDone }: { iv: Intervention; op: string; onDone(): void }) {
  const [mode, setMode] = useState<'observe' | 'manual'>('observe')
  const [win, setWin] = useState(60)
  const [avg, setAvg] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!op.trim()) { toast('Enter your operator name first', true); return }
    if (mode === 'manual' && !(Number(avg) >= 0 && avg !== '')) { toast('Enter the reported average wait in minutes', true); return }
    setBusy(true)
    try {
      const body = mode === 'observe' ? { mode, window_minutes: win, operator: op.trim() } : { mode, operator: op.trim(), observed: { avg_wait_min: Number(avg) } }
      const r = await api<{ message: string }>(`/interventions/item/${iv.id}/outcome`, { method: 'POST', body })
      toast(r.message); onDone()
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  return (
    <div className="iq-row">
      <header><span><b>{iv.label}</b> <span className="twin-note">· applied {iv.applied_at ? new Date(iv.applied_at).toLocaleString() : ''} by {iv.applied_by}</span></span>{iv.is_synthetic && <Chip tone="demo">synthetic queue</Chip>}</header>
      <Seg<'observe' | 'manual'> value={mode} onChange={setMode} label="Outcome source" options={[{ v: 'observe', l: 'Measure from queue data' }, { v: 'manual', l: 'Operator-reported figure' }]} />
      <div className="iq-bar">
        {mode === 'observe'
          ? <label className="iq-sel">Window before/after (min)<input className="in" type="number" min={10} max={1440} value={win} onChange={e => setWin(Number(e.target.value))} aria-label="Window in minutes" /></label>
          : <label className="iq-sel">Reported average wait (min)<input className="in" type="number" min={0} step={0.1} value={avg} onChange={e => setAvg(e.target.value)} aria-label="Reported average wait" /></label>}
        <button className="btn p" disabled={busy} onClick={() => void submit()}>{busy ? <Spinner /> : <Target size={13} />}Record outcome</button>
      </div>
      <Note>{mode === 'observe' ? 'Compares customers served in the window before the confirmed time with the window after it. The window after must have finished.' : 'Stored as reported. It is never counted as a verified observation.'}</Note>
    </div>
  )
}

function Panel({ queueId }: { queueId: number }) {
  const learn = useLoad<Learning>(`/interventions/${queueId}/learning`)
  const over = useLoad<Overview>(`/operations/${queueId}/overview`)
  const hist = useLoad<{ interventions: Intervention[] }>(`/interventions/${queueId}/history`, { status: 'applied' })
  const [op, setOp] = useOperator()
  const [cycle, setCycle] = useState<CycleResult | null>(null)
  const [busy, setBusy] = useState(false)
  const refresh = () => { void learn.reload(); void over.reload(); void hist.reload() }
  const runCycle = async () => {
    setBusy(true)
    try { const r = await api<CycleResult>(`/operations/${queueId}/cycle`, { method: 'POST', body: {} }); setCycle(r); over.setData(r.overview); refresh(); toast('Automatic stages ran. Nothing was approved or applied.') }
    catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  if (learn.err && !learn.data) return <ErrorState text={learn.err} onRetry={learn.reload} />
  const l = learn.data
  if (!l) return <Skeleton h={300} />
  const sm = l.summary
  const bars = Object.entries(sm.by_type).filter(([, s]) => s.n > 0).map(([t, s]) => ({ type: typeLabel(t), error: Number((s.mean_error_min ?? 0).toFixed(2)) }))
  const pending = hist.data?.interventions ?? []

  return (
    <div className="iq-stack">
      <ProvenanceBanner p={l.provenance} />
      <Card title="The closed loop" sub="Where this queue stands in observe → calibrate → detect → propose → approve → evaluate → recalibrate"
        right={<button className="btn" onClick={() => void runCycle()} disabled={busy}>{busy ? <Spinner /> : <RefreshCcw size={13} />}Run automatic stages</button>}>
        {over.data ? <div className="iq-loop">{over.data.stages.map(s => (
          <div key={s.stage} className={`iq-stage${s.attention ? ' att' : ''}`}><span>{s.label}</span><b>{s.metric ?? '—'}</b><span>{s.unit}</span></div>))}</div> : <Skeleton h={80} />}
        <Note>{over.data?.automation ?? 'LineZero never executes an intervention.'}</Note>
        {cycle && <div className="iq-outcome" role="status"><b className="twin-note">Last run</b>{cycle.steps.map((s, i) => <p key={i} className="twin-note" style={{ margin: 0 }}>{typeLabel(s.step)}: {s.skipped ? `skipped — ${s.reason}` : Object.entries(s).filter(([k, v]) => k !== 'step' && (typeof v === 'string' || typeof v === 'number')).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}</p>)}
          {cycle.steps.some(s => s.step === 'propose_interventions' && !s.skipped) && <Link className="btn sm" to="/app/interventions">Review proposals</Link>}</div>}
      </Card>

      <Card title="How well does the twin predict interventions?" sub="Simulated expected wait reduction vs what was observed afterwards. Kept apart by how trustworthy the outcome is." right={<KindTag kind="observed" />}>
        <div className="grid g4 kp">
          <Kpi label="Verified real outcomes" value={sm.counts.verified_real_observation} sub="measured from real queue data" />
          <Kpi label="Synthetic outcomes" value={sm.counts.synthetic_observation} sub="demo data, not real-world" />
          <Kpi label="Operator-reported" value={sm.counts.operator_reported} sub="not measured by LineZero" />
          <Kpi label="Clean for calibration" value={l.calibration_eligible_outcomes} sub="real, no confounders" />
        </div>
        <div className="fc-grid" style={{ marginTop: 10 }}>
          <Stats title="Verified real" s={sm.verified_real} kind="verified_real_observation" />
          <Stats title="Synthetic" s={sm.synthetic} kind="synthetic_observation" />
          <Stats title="Operator-reported" s={sm.operator_reported} kind="operator_reported" />
        </div>
        {bars.length > 0 && (<><p className="twin-note" style={{ marginTop: 10 }}>Mean error by intervention type, verified real outcomes only (negative = the simulation was too optimistic)</p>
          <ChartBox h={200}><ResponsiveContainer><BarChart data={bars} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}><CartesianGrid {...gridProps} /><XAxis dataKey="type" {...axisProps} /><YAxis {...axisProps} unit=" m" />
            <Tooltip content={<ChartTooltip fmt={v => `${signed(v)} min`} />} /><Bar dataKey="error" name="Mean error" fill={C.violet} isAnimationActive={false} /></BarChart></ResponsiveContainer></ChartBox></>)}
        <div className="rec" style={{ marginTop: 10 }}><div className="iq-actions"><Chip tone={l.advice.recalibrate ? 'warn' : undefined}>{l.advice.recalibrate ? 'Recalibration suggested' : 'No recalibration signal'}</Chip></div><p className="iq-pre">{l.advice.reason}</p></div>
        <Note>{l.note}</Note>
      </Card>

      <Card title={`Awaiting an outcome (${pending.length})`} sub="Interventions an operator confirmed as applied" right={<OperatorField name={op} setName={setOp} />}>
        {pending.length === 0 ? <Note>Nothing is waiting. Approve a proposal, carry it out, and confirm it under Autonomous Interventions.</Note> : <div className="iq-hist">{pending.map(i => <Pending key={i.id} iv={i} op={op} onDone={refresh} />)}</div>}
      </Card>

      <Card title={`Recorded outcomes (${l.outcomes.length})`} sub="Newest first">
        {l.outcomes.length === 0 ? <Note>No outcomes recorded yet.</Note> : <div className="iq-hist">{l.outcomes.map(i => (
          <div className="iq-row" key={i.id}><header><b>{i.label}</b><span className="twin-note">{i.outcome_recorded_at ? new Date(i.outcome_recorded_at).toLocaleString() : ''}</span></header>
            {i.outcome && <OutcomeView o={i.outcome} />}</div>))}</div>}
      </Card>
      <p className="twin-note">Expected values are simulated. Observed values are measured only where marked “Verified real observation”. Confidence in a result: {pct(0.95)} intervals describe measurement noise, not causation.</p>
      <KindLegend />
    </div>
  )
}

export default function OutcomePage() {
  return <Gate title="Outcome Learning" sub="Compare what the twin expected with what happened, and learn from it, without calling simulated or reported results verified.">{id => <Panel queueId={id} />}</Gate>
}
