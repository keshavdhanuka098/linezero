import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Gauge } from 'lucide-react'
import type { PolicyList, SlaMonitor, SlaPerformance } from '../../api/slaTypes'
import { atRiskCount } from '../../lib/sla'
import { Card, Chip, EmptyState, ErrorState, Seg } from '../ui/kit'
import { Gate, Legend, Note, ProvenanceBanner, useAutoRefresh, useLoad, useOperator } from '../intelligence/shared'
import SlaLive from './SlaLive'
import SlaOverview from './SlaOverview'
import SlaRecommend from './SlaRecommend'
import SlaTargets from './SlaTargets'

type Tab = 'overview' | 'live' | 'recommend' | 'targets'
const REFRESH_MS = 15000

function Panel({ queueId }: { queueId: number }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [auto, setAuto] = useState(true)
  const [op, setOp] = useOperator()
  const mon = useLoad<SlaMonitor>(`/sla/${queueId}/monitor`)
  const perf = useLoad<SlaPerformance>(`/sla/${queueId}/performance`)
  const pol = useLoad<PolicyList>(`/sla/${queueId}/policies`)
  const refresh = () => { void mon.reload(); void perf.reload(); void pol.reload() }
  useAutoRefresh(() => { void mon.reload(); void perf.reload() }, REFRESH_MS, auto)

  const err = pol.err ?? mon.err ?? perf.err
  if (err && !pol.data) return <ErrorState text={err} onRetry={refresh} />
  const configured = pol.data?.configured ?? mon.data?.configured ?? false
  const needsSetup = pol.data !== null && !configured
  const risky = atRiskCount(mon.data?.counts)

  return (
    <div className="iq-stack">
      <ProvenanceBanner p={mon.data?.provenance ?? perf.data?.provenance} />
      <div className="iq-actions" style={{ justifyContent: 'space-between' }}>
        <Seg<Tab> value={tab} onChange={setTab} label="SLA sections" options={[
          { v: 'overview', l: 'Performance' }, { v: 'live', l: `Live customers${risky ? ` (${risky})` : ''}` },
          { v: 'recommend', l: 'Recommendations' }, { v: 'targets', l: 'Targets' }]} />
        <label className="twin-note" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} aria-label="Auto-refresh" /> Auto-refresh every {REFRESH_MS / 1000}s
        </label>
      </div>
      {err && <div className="banner warn" role="alert">Could not refresh: {err}</div>}

      {tab === 'targets' && <SlaTargets queueId={queueId} data={pol.data} op={op} setOp={setOp} onChanged={refresh} />}
      {tab !== 'targets' && needsSetup && (
        <Card><EmptyState icon={Gauge} title="Set an SLA target to begin" text="No maximum waiting time is configured for this queue, so there is nothing to predict or measure yet. LineZero does not assume a target."
          action={<button className="btn p" onClick={() => setTab('targets')}>Configure targets</button>} /></Card>)}
      {tab === 'overview' && configured && <SlaOverview perf={perf.data} mon={mon.data} busy={perf.busy} />}
      {tab === 'live' && configured && <SlaLive mon={mon.data} policies={pol.data} queueId={queueId} onChanged={refresh} />}
      {tab === 'recommend' && configured && <SlaRecommend queueId={queueId} mon={mon.data} />}
      <Legend />
      <Note>Observed figures come from the queue database; predictions and simulations are labelled. <Link to="/app/interventions">Autonomous Interventions</Link> holds the approval workflow.</Note>
      {mon.data && <Chip>{mon.data.queue.name}{mon.data.as_of_basis === 'latest_activity_of_synthetic_queue' ? ' · evaluated at its latest activity (synthetic)' : ''}</Chip>}
    </div>
  )
}

export default function SlaPage() {
  return <Gate title="SLA Intelligence" sub="Predict service-level breaches, spot customers at risk, measure compliance and act on evidence.">{id => <Panel queueId={id} />}</Gate>
}
