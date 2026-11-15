import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from 'recharts'
import { RefreshCw, ScanSearch } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { RiskAssessment, RiskEventRow, RiskResult } from '../../api/adaptiveTypes'
import { num, pct, radarRows, sevTone, typeLabel } from '../../lib/adaptive'
import { Card, Chip, ErrorState, Kpi, Skeleton, Spinner, toast } from '../ui/kit'
import { C, ChartBox } from '../charts/theme'
import { Gate, KindTag, Legend as KindLegend, Note, OperatorField, ProvenanceBanner, useLoad, useOperator } from './shared'

const KIND_OF: Record<string, 'observed' | 'simulated' | 'predicted'> = { observed: 'observed', simulated: 'simulated', predicted: 'predicted' }

function RiskCard({ a, eventId, queueId }: { a: RiskAssessment; eventId?: number; queueId: number }) {
  const [open, setOpen] = useState(false)
  const dk = (a.supporting_metrics.data_kind ?? {}) as Record<string, string>
  const kinds = Array.from(new Set(Object.values(dk))).filter(k => k in KIND_OF)
  return (
    <article className="iq-risk" aria-label={`${a.label} ${a.resource_name}`}>
      <header>
        <h4>{a.label}</h4><span className="twin-note">{a.resource_name}</span>
        <Chip tone={sevTone(a.severity)}>{a.severity ?? 'None'}</Chip><span className="mono">{pct(a.score)}</span>
        {a.time_to_impact_min != null && <Chip>impact in ≈ {num(a.time_to_impact_min, 0)} min</Chip>}
        {kinds.map(k => <KindTag key={k} kind={KIND_OF[k]} />)}
      </header>
      <p className="iq-pre">{a.explanation}</p>
      {a.recommended_intervention?.text && <p className="twin-note" style={{ margin: 0 }}>Suggested response: {a.recommended_intervention.text}</p>}
      <div className="iq-actions">
        <button className="btn sm" onClick={() => setOpen(o => !o)} aria-expanded={open}>{open ? 'Hide' : 'Show'} how this score is computed</button>
        <Link className="btn sm" to={`/app/interventions${eventId ? `?risk=${eventId}` : ''}`} state={{ queueId }}>Evaluate interventions</Link>
      </div>
      {open && (
        <div className="iq-outcome">
          <div className="iq-formula">score = {a.score_formula}</div>
          <div className="iq-comp">{Object.entries(a.components).map(([k, v]) => <Chip key={k}>{k.replace(/_/g, ' ')}: {num(v)}</Chip>)}</div>
          <dl className="iq-kv">{Object.entries(a.supporting_metrics).filter(([k, v]) => k !== 'data_kind' && (typeof v === 'number' || typeof v === 'string')).map(([k, v]) => (
            <Fragment key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{typeof v === 'number' ? num(v) : String(v)}</dd></Fragment>))}</dl>
          <Note>Confidence {pct(a.confidence)} reflects how much data supports this score.</Note>
        </div>
      )}
    </article>
  )
}

function Panel({ queueId }: { queueId: number }) {
  const r = useLoad<RiskResult>(`/risk/${queueId}/assess`)
  const ev = useLoad<{ events: RiskEventRow[] }>(`/risk/${queueId}/events`, { status: 'all' })
  const [busy, setBusy] = useState(false)
  const [op, setOp] = useOperator()

  const scan = async () => {
    setBusy(true)
    try {
      const d = await api<RiskResult>(`/risk/${queueId}/scan`, { method: 'POST', body: {} })
      r.setData(d); void ev.reload(); toast(`Scan stored: ${d.persisted_events.length} open risk event(s)`)
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const resolve = async (id: number) => {
    if (!op.trim()) { toast('Enter an operator name first', true); return }
    try { await api(`/risk/events/${id}/resolve`, { method: 'POST', body: { operator: op.trim() } }); void ev.reload(); toast('Marked resolved') } catch (e) { toast(errMsg(e), true) }
  }

  if (r.err && !r.data) return <ErrorState text={r.err} onRetry={r.reload} />
  const d = r.data
  if (!d) return <Skeleton h={320} />
  const rows = radarRows(d.radar)
  const active = d.assessments.filter(a => a.severity)
  const eventIdOf = (a: RiskAssessment) => (ev.data?.events ?? []).find(e => e.status === 'open' && e.category === a.category && e.resource_id === a.resource_id)?.id
  const s = d.snapshot

  return (
    <div className="iq-stack">
      <ProvenanceBanner p={d.provenance} />
      <div className="iq-actions">
        <button className="btn" onClick={() => void r.reload()} disabled={r.busy}>{r.busy ? <Spinner /> : <RefreshCw size={13} />}Re-assess (saves nothing)</button>
        <button className="btn p" onClick={() => void scan()} disabled={busy}>{busy ? <Spinner /> : <ScanSearch size={13} />}Scan and store risk events</button>
      </div>
      <div className="grid g4 kp">
        <Kpi label="Overall risk" value={pct(d.overall_score)} tone={d.overall_severity === 'CRITICAL' ? 'crit' : d.overall_severity === 'HIGH' ? 'hot' : d.overall_severity === 'MEDIUM' ? 'warn' : undefined} sub={d.overall_severity ?? 'no risk detected'} />
        <Kpi label="Queue now" value={s.queue_length} sub={`longest wait ${num(s.longest_wait_min, 1)} min`} />
        <Kpi label="Counters" value={`${s.active_counters} active`} sub={`${s.reserve_counters} in reserve`} />
        <Kpi label="Load" value={pct(s.load_ratio)} sub={`service rates: ${d.service_rate_source.replace('_', ' ')}`} />
      </div>
      <div className="iq-two">
        <Card title="Operational risk radar" sub="Score of each category, 0–100" right={<KindTag kind="predicted" />}>
          <ChartBox h={300}><ResponsiveContainer><RadarChart data={rows} outerRadius="72%">
            <PolarGrid stroke={C.grid} /><PolarAngleAxis dataKey="label" tick={{ fill: C.axis, fontSize: 11 }} /><PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            <Radar dataKey="value" name="Risk score" stroke={C.violet} fill={C.violet} fillOpacity={0.3} isAnimationActive={false} />
          </RadarChart></ResponsiveContainer></ChartBox>
          <Note>Severity bands: Low ≥ {pct(d.bands.LOW)}, Medium ≥ {pct(d.bands.MEDIUM)}, High ≥ {pct(d.bands.HIGH)}, Critical ≥ {pct(d.bands.CRITICAL)}. Scores come from documented formulas, not from random numbers or a language model.</Note>
        </Card>
        <Card title="Categories" sub="Every category is always scored">
          <div className="tw"><table className="tbl">
            <thead><tr><th>Category</th><th>Resource</th><th>Score</th><th>Severity</th></tr></thead>
            <tbody>{rows.map(x => <tr key={x.key}><td>{x.label}</td><td className="twin-note">{x.resource}</td><td className="mono">{x.value}</td><td>{x.status === 'insufficient_data' ? <Chip>Insufficient data</Chip> : <Chip tone={sevTone(x.severity)}>{x.severity ?? 'None'}</Chip>}</td></tr>)}</tbody>
          </table></div>
          {d.utilization_caveat && <Note>{d.utilization_caveat}</Note>}
        </Card>
      </div>

      <Card title={`Detected risks (${active.length})`} sub="Predictive and explainable: each score shows its inputs and formula">
        {active.length === 0 ? <Note>No category is above the lowest severity band right now.</Note> : <div className="iq-radar-list">{active.map((a, i) => <RiskCard key={`${a.category}-${a.resource_id}-${i}`} a={a} queueId={queueId} eventId={eventIdOf(a)} />)}</div>}
      </Card>

      <Card title="Stored risk events" sub="Open events refresh on each stored scan; events no longer detected are marked resolved" right={<OperatorField name={op} setName={setOp} />}>
        {ev.err && !ev.data ? <ErrorState text={ev.err} onRetry={ev.reload} /> : !ev.data ? <Skeleton h={80} /> : ev.data.events.length === 0 ? <Note>No stored events yet. Use “Scan and store risk events”.</Note> : (
          <div className="tw"><table className="tbl">
            <thead><tr><th>Detected</th><th>Category</th><th>Resource</th><th>Severity</th><th>Status</th><th /></tr></thead>
            <tbody>{ev.data.events.slice(0, 25).map(e => (
              <tr key={e.id}><td className="twin-note">{new Date(e.detected_at).toLocaleString()}</td><td>{typeLabel(e.category)}</td><td>{e.resource_name}</td>
                <td><Chip tone={sevTone(e.severity)}>{e.severity}</Chip></td><td><Chip tone={e.status === 'open' ? 'warn' : undefined}>{e.status}</Chip></td>
                <td>{e.status === 'open' && <><Link className="btn sm" to={`/app/interventions?risk=${e.id}`}>Interventions</Link> <button className="btn sm" onClick={() => void resolve(e.id)}>Resolve</button></>}</td></tr>))}</tbody>
          </table></div>
        )}
      </Card>
      <KindLegend />
    </div>
  )
}

export default function RiskRadarPage() {
  return <Gate title="Operational Risk Radar" sub="Predict problems before they happen: seven risk categories scored from observed data and the twin’s forecast.">{id => <Panel queueId={id} />}</Gate>
}
