import { useState } from 'react'
import { CheckCircle2, Lightbulb, Search } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { BottleneckResult, Detection } from '../../api/types'
import { useServer } from '../../api/serverStore'
import { Card, Chip, EmptyState, Field, PageHeader, Seg, Spinner, toast } from '../ui/kit'
import { NoQueues, QueuePicker } from './shared'

const TONE = { CRITICAL: 'crit', HIGH: 'hot', MEDIUM: 'warn', LOW: 'ok' } as const
const TITLE: Record<string, string> = { counter_overload: 'Counter overload', uneven_utilization: 'Uneven utilization', arrival_spike: 'Arrival spike', slow_service: 'Slow service', capacity_demand_imbalance: 'Capacity / demand imbalance' }

export default function ServerBottlenecks() {
  const queueId = useServer(s => s.queueId), queues = useServer(s => s.queues)
  const [win, setWin] = useState<'120' | '240' | '480'>('240')
  const [res, setRes] = useState<{ queueId: number; data: BottleneckResult } | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    if (queueId === null) return
    setBusy(true)
    try { setRes({ queueId, data: await api<BottleneckResult>('/bottlenecks/analyze', { method: 'POST', body: { queue_id: queueId, window_minutes: Number(win), lookback_minutes: 1440 } }) }) }
    catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const shown = res && res.queueId === queueId ? res.data : null
  const counts = (['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(k => [k, shown?.detections.filter(d => d.severity === k).length ?? 0] as const)
  const qName = queues.find(q => q.id === queueId)?.name

  return (
    <div className="page">
      <PageHeader title="Bottleneck Investigator" sub="Statistical rules evaluated on the server. Each finding shows the evidence behind it." demo={false}>
        <button className="btn p" onClick={run} disabled={busy || queueId === null}>{busy ? <Spinner /> : <Search size={16} />}Analyze queue</button>
      </PageHeader>
      {queueId === null ? <NoQueues /> : (<>
        <QueuePicker>
          <Field label="Analysis window"><Seg<'120' | '240' | '480'> value={win} onChange={setWin} label="Analysis window" options={[{ v: '120', l: '2 h' }, { v: '240', l: '4 h' }, { v: '480', l: '8 h' }]} /></Field>
        </QueuePicker>
        {!shown ? <Card><EmptyState icon={Search} title="Run an analysis" text={`Analyze ${qName ?? 'the selected queue'} to see overload, uneven load, arrival spikes, slow counters and capacity gaps.`} action={<button className="btn p" onClick={run} disabled={busy}>Analyze queue</button>} /></Card> : (<>
          <div className="grid g4 kp">
            {counts.map(([k, n]) => <div className="card kpi" key={k}><div className="l" style={{ textTransform: 'capitalize' }}>{k.toLowerCase()}</div><div className="v">{n}</div></div>)}
          </div>
          {shown.by_queue.flatMap(b => b.notes).length > 0 && <div className="banner"><span>{shown.by_queue.flatMap(b => b.notes).join(' ')}</span></div>}
          {shown.detections.length === 0 ? <Card><EmptyState icon={CheckCircle2} title="No bottlenecks detected" text="No rule crossed its threshold in this window. A longer window increases statistical power." /></Card>
            : <div style={{ display: 'grid', gap: 12 }}>{shown.detections.map(d => <DetectionCard key={d.detection_id} d={d} />)}</div>}
        </>)}
      </>)}
    </div>
  )
}

function DetectionCard({ d }: { d: Detection }) {
  return (
    <Card title={TITLE[d.bottleneck_type] ?? d.bottleneck_type} sub={d.counter_id !== null ? `Counter #${d.counter_id}` : 'Queue-level finding'} right={<Chip tone={TONE[d.severity]}>{d.severity}</Chip>}>
      <p style={{ margin: '0 0 8px' }}>{d.explanation}</p>
      <p className="hint" style={{ margin: '0 0 10px' }}>{d.operational_impact}</p>
      <div className="banner" style={{ margin: 0 }}><Lightbulb size={16} style={{ flex: 'none', marginTop: 2 }} /><span>{d.recommendation}</span></div>
    </Card>
  )
}
