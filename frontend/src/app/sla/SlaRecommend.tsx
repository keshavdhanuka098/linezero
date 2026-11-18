import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Lightbulb, Play } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { SlaMonitor, SlaRecommendation } from '../../api/slaTypes'
import { num, signed } from '../../lib/adaptive'
import { atRiskCount } from '../../lib/sla'
import { Card, Chip, Kpi, Spinner, toast } from '../ui/kit'
import { KindTag, Note } from '../intelligence/shared'

export default function SlaRecommend({ queueId, mon }: { queueId: number; mon: SlaMonitor | null }) {
  const [res, setRes] = useState<SlaRecommendation | null>(null)
  const [busy, setBusy] = useState<'run' | 'save' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const risky = atRiskCount(mon?.counts)
  const run = async (persist: boolean) => {
    setBusy(persist ? 'save' : 'run'); setErr(null)
    try {
      const r = await api<SlaRecommendation>(`/sla/${queueId}/recommendations`, { method: 'POST', body: { persist } })
      setRes(r); if (persist) toast('Sent to Autonomous Interventions as proposals. Nothing was changed.')
    } catch (e) { setErr(errMsg(e)); toast(errMsg(e), true) } finally { setBusy(null) }
  }
  return (
    <div className="iq-stack">
      <Card title="Recommended interventions" sub="Why customers may breach their SLA and what the simulation says would help" right={<KindTag kind="simulated" />}>
        <div className="iq-actions">
          <button className="btn p" onClick={() => void run(false)} disabled={busy !== null}>{busy === 'run' ? <Spinner /> : <Play size={13} />}Analyse and simulate</button>
          <span className="twin-note">{risky ? `${risky} customer(s) at risk, critical or breached right now` : 'No customer is at risk right now'}</span>
        </div>
        {err && <div className="banner warn" role="alert">{err}</div>}
        <Note>Candidate actions are validated by the existing intervention simulation (same seeds for every option). They are proposals: people approve and carry them out, and LineZero never changes a counter or queue.</Note>
      </Card>

      {res && !res.needed && <Card title="No intervention needed"><p className="iq-pre" role="status">{res.message}</p></Card>}

      {res?.needed && (
        <>
          <Card title="Why a breach may occur" sub={`${res.queue.name} · tightest at-risk target ${res.target_min} min`} right={<KindTag kind="predicted" />}>
            <ul className="iq-list">{res.reasons?.map((r, i) => <li key={i}>{r}</li>)}</ul>
            {res.capacity_gap && res.capacity_gap.extra_capacity_per_min > 0 && (
              <p className="twin-note">Capacity gap for token {res.capacity_gap.for_token}: needs ≈ {num(res.capacity_gap.required_capacity_per_min, 2)} customers/min, has {num(res.capacity_gap.current_capacity_per_min, 2)}
                {res.capacity_gap.approx_extra_counters != null ? ` (≈ ${res.capacity_gap.approx_extra_counters} more counter${res.capacity_gap.approx_extra_counters === 1 ? '' : 's'} at the current average rate)` : ''}.</p>)}
          </Card>
          {res.baseline && (
            <div className="grid g4 kp">
              <Kpi label="If nothing changes: average wait" value={num(res.baseline.avg_wait_min, 1)} unit="min" sub={<KindTag kind="simulated" />} />
              <Kpi label="If nothing changes: P95 wait" value={num(res.baseline.p95_wait_min, 1)} unit="min" sub={`target ${res.target_min} min`} tone={res.target_min != null && res.baseline.p95_wait_min > res.target_min ? 'hot' : undefined} />
            </div>)}
          {res.candidates && res.candidates.length === 0 && <Card><Note>No feasible intervention could be simulated for the current counters.</Note></Card>}
          <div className="twin-cards">{res.candidates?.map(c => (
            <article key={c.key} className={`iq-cand${c.is_recommended ? ' best' : ''}`} aria-label={c.label}>
              <header><Chip tone={c.is_recommended ? 'ok' : undefined}>#{c.rank}{c.is_recommended ? ' recommended' : ''}</Chip><h4>{c.label}</h4><KindTag kind="simulated" /></header>
              <p className="twin-note" style={{ margin: 0 }}>{c.description}</p>
              <dl className="iq-kv">
                <dt>Expected wait reduction</dt><dd>{c.expected_wait_reduction_min.mean != null ? `${signed(c.expected_wait_reduction_min.mean)} min${c.expected_wait_reduction_min.ci95 != null ? ` ± ${num(c.expected_wait_reduction_min.ci95)}` : ''}` : '—'}</dd>
                <dt>Average wait after</dt><dd>{num(c.avg_wait_after_min, 1)} min</dd>
                <dt>P95 wait after</dt><dd>{num(c.p95_wait_after_min, 1)} min <Chip tone={c.p95_within_target ? 'ok' : 'warn'}>{c.p95_within_target ? 'within target' : 'above target'}</Chip></dd>
                <dt>Extra cost</dt><dd>{num(c.extra_cost.total)} units</dd>
                <dt>Clear beyond noise</dt><dd>{c.significant ? 'yes' : 'no'}</dd>
              </dl>
              <details><summary className="twin-note">Assumptions (not measured data)</summary><ul className="twin-note">{c.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
            </article>))}</div>
          {res.explanation && <Card title="Explanation" right={<KindTag kind="explanation" />}><p className="iq-pre">{res.explanation}</p></Card>}
          <Card title="Next step">
            <div className="iq-actions">
              {res.persisted
                ? <Link className="btn p" to="/app/interventions">Review proposals in Autonomous Interventions</Link>
                : <button className="btn p" disabled={busy !== null} onClick={() => void run(true)}>{busy === 'save' ? <Spinner /> : <Lightbulb size={13} />}Send to approval workflow</button>}
            </div>
            <Note>{res.disclaimer} {res.note}</Note>
          </Card>
        </>)}
    </div>
  )
}
