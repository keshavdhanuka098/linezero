import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Brain, Play, RotateCcw } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { CalEvaluation, CalRecord, CalRun, CalStatus, Drift } from '../../api/adaptiveTypes'
import { num, pct, sevTone, signed } from '../../lib/adaptive'
import { Card, Chip, Confirm, ErrorState, Kpi, Skeleton, Spinner, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps } from '../charts/theme'
import { Gate, KindTag, Legend as KindLegend, Note, OperatorField, ProvenanceBanner, useLoad, useOperator } from './shared'

const SIGNALS: { key: 'arrival_rate' | 'service_time' | 'waiting_time'; label: string; unit: string }[] = [
  { key: 'arrival_rate', label: 'Arrival rate', unit: '/min' }, { key: 'service_time', label: 'Service time', unit: 'min' }, { key: 'waiting_time', label: 'Waiting time', unit: 'min' }]

function DriftTable({ drift }: { drift: Drift }) {
  if (!drift.signals) return <Note>{drift.status === 'insufficient_data' ? 'Not enough data to test for drift yet.' : 'No drift result.'}</Note>
  return (
    <div className="tw"><table className="tbl">
      <thead><tr><th>Signal</th><th>Reference</th><th>Recent</th><th>Change</th><th>p-value</th><th>Verdict</th></tr></thead>
      <tbody>{SIGNALS.map(s => {
        const g = drift.signals![s.key]
        if (g.status !== 'ok') return <tr key={s.key}><td>{s.label}</td><td colSpan={4} className="twin-note">Insufficient data</td><td><Chip>Not tested</Chip></td></tr>
        const ref = g.reference_mean ?? g.reference_rate_per_min, rec = g.recent_mean ?? g.recent_rate_per_min
        return <tr key={s.key}><td>{s.label}</td><td className="mono">{num(ref)} {s.unit}</td><td className="mono">{num(rec)} {s.unit}</td>
          <td className="mono">{g.effect != null ? `${signed(g.effect * 100, 0)}%` : '—'}</td><td className="mono">{g.p_value != null ? g.p_value.toExponential(1) : '—'}</td>
          <td>{g.drifted ? <Chip tone="hot">Drift ({g.direction})</Chip> : <Chip tone="ok">Stable</Chip>}</td></tr>
      })}</tbody>
    </table></div>
  )
}

function Panel({ queueId }: { queueId: number }) {
  const status = useLoad<CalStatus>(`/calibration/${queueId}/status`)
  const versions = useLoad<{ versions: CalRecord[] }>(`/calibration/${queueId}/versions`)
  const driftQ = useLoad<Drift & { reference_basis?: string }>(`/calibration/${queueId}/drift`)
  const evaln = useLoad<CalEvaluation>(`/calibration/${queueId}/evaluation`)
  const [run, setRun] = useState<CalRun | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [op, setOp] = useOperator()
  const [rollback, setRollback] = useState<CalRecord | null>(null)

  const refresh = () => { void status.reload(); void versions.reload(); void evaln.reload(); void driftQ.reload() }
  const calibrate = async (dry: boolean) => {
    setBusy(dry ? 'dry' : 'run')
    try { const r = await api<CalRun>(`/calibration/${queueId}/run`, { method: 'POST', body: { dry_run: dry } }); setRun(r); refresh(); toast(dry ? 'Preview computed — nothing was saved' : `Calibration ${r.decision}`) }
    catch (e) { toast(errMsg(e), true) } finally { setBusy(null) }
  }
  const doRollback = async () => {
    if (!rollback) return
    if (!op.trim()) { toast('Enter an operator name first', true); setRollback(null); return }
    try { await api(`/calibration/${queueId}/rollback`, { method: 'POST', body: { version: rollback.version, reason: `Operator rollback to v${rollback.version}`, operator: op.trim() } }); toast(`Restored v${rollback.version} as a new version`); refresh() }
    catch (e) { toast(errMsg(e), true) } finally { setRollback(null) }
  }

  if (status.err && !status.data) return <ErrorState text={status.err} onRetry={status.reload} />
  const s = status.data
  if (!s) return <Skeleton h={300} />
  const ev = evaln.data
  const series = (ev?.series ?? []).map((p, i) => ({ i, actual: p.actual_min, predicted: p.predicted_min }))
  const rows = versions.data?.versions ?? []

  return (
    <div className="iq-stack">
      <ProvenanceBanner p={s.provenance} />
      <div className="grid g4 kp">
        <Kpi label="Active model" value={s.model === 'nominal_configuration' ? 'Nominal' : s.model.replace('calibration_', '')} sub={s.model === 'nominal_configuration' ? 'configured counter rates, not learned' : 'learned from observations'} icon={Brain} />
        <Kpi label="Observations" value={s.observations.served} sub={s.observations.ready ? `enough (≥ ${s.observations.needed_for_calibration})` : `need ≥ ${s.observations.needed_for_calibration} to calibrate`} tone={s.observations.ready ? undefined : 'warn'} />
        <Kpi label="Versions" value={s.versions} sub={`${s.rejected_candidates} rejected candidate${s.rejected_candidates === 1 ? '' : 's'} kept for audit`} />
        <Kpi label="Drift" value={s.drift.drift_detected ? (s.drift.severity ?? 'detected') : s.drift.status === 'insufficient_data' ? 'Unknown' : 'None'} tone={s.drift.drift_detected ? 'hot' : undefined} sub={s.drift.drifted_signals.join(', ') || 'no drifted signal'} />
      </div>

      <div className="iq-two">
        <Card title="Learn from data" sub="Chronological split: fit on earlier customers, validate on the latest. A candidate is accepted only if it predicts held-out waits better."
          right={<KindTag kind="predicted" />}>
          <div className="iq-actions">
            <button className="btn" disabled={busy !== null || !s.observations.ready} onClick={() => void calibrate(true)}>{busy === 'dry' ? <Spinner /> : <Play size={13} />}Preview (saves nothing)</button>
            <button className="btn p" disabled={busy !== null || !s.observations.ready} onClick={() => void calibrate(false)}>{busy === 'run' ? <Spinner /> : <Brain size={13} />}Run calibration</button>
          </div>
          {!s.observations.ready && <Note>Not enough served customers yet, so calibration is unavailable. No parameters are guessed.</Note>}
          {run && (
            <div className="iq-outcome" role="status">
              <div className="iq-actions"><Chip tone={run.decision === 'accepted' ? 'ok' : run.decision === 'rejected' ? 'warn' : undefined}>{run.decision.replace('_', ' ')}</Chip>{run.dry_run && <Chip>preview only</Chip>}{run.persisted && <Chip>saved</Chip>}</div>
              {run.reasons.map((r, i) => <p key={i} className="twin-note" style={{ margin: 0 }}>{r}</p>)}
              {run.result && <dl className="iq-kv">
                <dt>Validation error, {run.result.incumbent_label}</dt><dd>{num(run.result.incumbent_metrics.mae_s / 60)} min</dd>
                <dt>Validation error, candidate</dt><dd>{num(run.result.candidate_metrics.mae_s / 60)} min</dd>
                <dt>Change in error</dt><dd>{run.result.mae_improvement_pct != null ? `${signed(-run.result.mae_improvement_pct, 1)}%` : '—'}</dd>
                <dt>Held-out customers</dt><dd>{run.result.n_validation}</dd>
                <dt>Confidence</dt><dd>{pct(run.result.confidence.value)}</dd></dl>}
            </div>
          )}
        </Card>

        <Card title="Parameters" sub="Nominal = configured; active = learned" right={<KindTag kind="predicted" />}>
          <dl className="iq-kv">
            <dt>Nominal service rate (pooled)</dt><dd>{num(s.nominal_parameters.service_rate_per_min, 3)} /min</dd>
            <dt>Active service rate (pooled)</dt><dd>{s.active ? `${num(s.active.parameters.service_rate_per_min, 3)} /min` : 'not calibrated'}</dd>
            <dt>Active arrival rate</dt><dd>{s.active?.parameters.arrival_rate_per_min != null ? `${num(s.active.parameters.arrival_rate_per_min, 3)} /min` : '—'}</dd>
            <dt>Model confidence</dt><dd>{s.active ? pct(s.active.confidence) : '—'}</dd>
            <dt>Trained on</dt><dd>{s.active?.n_train_services != null ? `${s.active.n_train_services} services` : '—'}</dd>
          </dl>
          <Note>Confidence = data sufficiency × precision of the service-rate estimate. It is not an accuracy guarantee.</Note>
        </Card>
      </div>

      <Card title="Drift detection" sub={s.drift.status === 'ok' ? 'Reference window (what the model learned from) vs recent window' : 'Reference vs recent window'} right={<><KindTag kind="observed" />{s.drift.severity && s.drift.severity !== 'none' && <Chip tone={sevTone(String(s.drift.severity).toUpperCase())}>{s.drift.severity}</Chip>}</>}>
        {driftQ.data ? <DriftTable drift={driftQ.data} /> : driftQ.err ? <ErrorState text={driftQ.err} onRetry={driftQ.reload} /> : <Skeleton h={80} />}
        {driftQ.data?.reference_basis && <Note>Reference window: {driftQ.data.reference_basis}.</Note>}
        <Note>A signal drifts only if it is statistically significant (Bonferroni-corrected) and the effect is practically large.</Note>
      </Card>

      <Card title="Predicted vs actual waiting time" sub={ev ? `${ev.n} customers · ${ev.out_of_sample ? 'out-of-sample' : 'includes training data'}` : undefined} right={<><KindTag kind="observed" /><KindTag kind="predicted" /></>}>
        {evaln.err && !ev ? <ErrorState text={evaln.err} onRetry={evaln.reload} /> : !ev ? <Skeleton h={220} /> : (
          <>
            <div className="grid g4 kp">
              <Kpi label="Nominal MAE" value={ev.nominal ? num(ev.nominal.mae_s / 60) : '—'} unit="min" sub={ev.nominal ? `n = ${ev.nominal.n}` : 'no data'} />
              <Kpi label="Calibrated MAE" value={ev.calibrated ? num(ev.calibrated.mae_s / 60) : '—'} unit="min" sub={ev.calibrated ? `n = ${ev.calibrated.n}` : 'no active calibration'} />
              <Kpi label="Calibrated bias" value={ev.calibrated ? signed(ev.calibrated.mean_error_s / 60) : '—'} unit="min" sub="predicted − actual" />
              <Kpi label="MAPE" value={ev.calibrated?.mape_pct != null ? `${num(ev.calibrated.mape_pct, 0)}%` : '—'} sub="waits ≥ 30 s only" />
            </div>
            {series.length > 1 ? (
              <ChartBox h={240}><ResponsiveContainer><LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="i" {...axisProps} hide /><YAxis {...axisProps} unit=" m" />
                <Tooltip content={<ChartTooltip fmt={v => `${num(v)} min`} />} />
                <Line type="monotone" dataKey="actual" name="Actual" stroke={C.teal} dot={false} strokeWidth={1.6} isAnimationActive={false} />
                <Line type="monotone" dataKey="predicted" name="Predicted" stroke={C.violet} dot={false} strokeWidth={1.6} strokeDasharray="4 3" isAnimationActive={false} />
              </LineChart></ResponsiveContainer></ChartBox>
            ) : <Note>No customers to compare yet.</Note>}
            <Legend items={[{ label: 'Actual (observed)', color: C.teal }, { label: 'Predicted', color: C.violet, dashed: true }]} />
            {ev.notes.map((n, i) => <Note key={i}>{n}</Note>)}
          </>
        )}
      </Card>

      <Card title="Version history" sub="Append-only. A rollback restores old parameters as a new version; rejected candidates are kept for audit." right={<OperatorField name={op} setName={setOp} />}>
        {versions.err && !versions.data ? <ErrorState text={versions.err} onRetry={versions.reload} /> : rows.length === 0 ? <Note>No calibration has been run for this queue.</Note> : (
          <div className="tw"><table className="tbl">
            <thead><tr><th>Version</th><th>Status</th><th>Decision</th><th>Service rate</th><th>Validation MAE</th><th>Confidence</th><th>Created</th><th /></tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.id}>
                <td>{r.version != null ? `v${r.version}` : '—'}{r.rollback_to_version ? ` (restores v${r.rollback_to_version})` : ''}</td>
                <td><Chip tone={r.status === 'active' ? 'ok' : r.status === 'rejected' ? 'warn' : undefined}>{r.status}</Chip></td>
                <td title={r.reason}>{r.decision.replace('_', ' ')}</td>
                <td className="mono">{num(r.parameters.service_rate_per_min, 3)}</td>
                <td className="mono">{r.candidate_metrics ? `${num(r.candidate_metrics.mae_s / 60)} min` : '—'}</td>
                <td className="mono">{pct(r.confidence)}</td>
                <td className="twin-note">{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.version != null && r.status === 'superseded' && <button className="btn sm" onClick={() => setRollback(r)}><RotateCcw size={12} />Roll back</button>}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>
      <KindLegend />
      {rollback && <Confirm title={`Restore v${rollback.version}?`} text="Its parameters become a new active version. History is not rewritten." confirmLabel="Restore" onConfirm={() => void doRollback()} onClose={() => setRollback(null)} />}
    </div>
  )
}

export default function AdaptivePage() {
  return <Gate title="Adaptive Intelligence" sub="Self-learning twin: parameters learned from observed data, validated before use, versioned and reversible.">{id => <Panel queueId={id} />}</Gate>
}
