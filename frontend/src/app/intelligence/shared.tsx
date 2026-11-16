import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Info, Server } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import { useServer, useServerMode } from '../../api/serverStore'
import type { DataKind, Provenance } from '../../api/adaptiveTypes'
import { KIND } from '../../lib/adaptive'
import { Card, Chip, EmptyState, PageHeader } from '../ui/kit'
import '../../styles/twin.css'
import '../../styles/intelligence.css'

/** GET `path` for the selected queue; re-runs when `deps` change. Out-of-order responses are ignored. */
export function useLoad<T>(path: string | null, params?: Record<string, string | number | boolean>, auto = true) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const key = path === null ? '' : path + JSON.stringify(params ?? {})
  const reload = useCallback(async () => {
    if (path === null) return
    const my = ++seq.current
    setBusy(true)
    try { const d = await api<T>(path, { params }); if (my === seq.current) { setData(d); setErr(null) } }
    catch (e) { if (my === seq.current) setErr(errMsg(e)) }
    finally { if (my === seq.current) setBusy(false) }
    // `key` captures path + params
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  useEffect(() => { setData(null); setErr(null); if (auto) void reload() }, [reload, auto])
  return { data, err, busy, reload, setData }
}

export function Gate({ title, sub, children }: { title: string; sub: string; children: (queueId: number) => ReactNode }) {
  const online = useServerMode()
  const queueId = useServer(s => s.queueId)
  const status = useServer(s => s.status)
  const setMode = useServer(s => s.setMode)
  if (!online) {
    return (
      <div className="page">
        <PageHeader title={title} sub={sub} demo={false} />
        <Card><EmptyState icon={Server} title={`${title} needs the LineZero backend`}
          text="Calibration, risk scoring, simulation and the approval history are computed and stored by the API, so this section is not available in browser-only demo mode. Start the backend with ./scripts/start-backend.sh, then switch to the server data source."
          action={status === 'online' ? <button className="btn p" onClick={() => setMode('server')}>Use server data</button> : <Link className="btn" to="/app/settings">Open settings</Link>} /></Card>
      </div>
    )
  }
  if (queueId === null) {
    return <div className="page"><PageHeader title={title} sub={sub} demo={false} /><Card><EmptyState title="No queue selected" text="Create a queue or seed demo data: python -m app.seed.generate_demo_data --scenario all --reset" /></Card></div>
  }
  return <div className="page"><PageHeader title={title} sub={sub} demo={false} /><QueueBar />{children(queueId)}</div>
}

export function QueueBar() {
  const queueId = useServer(s => s.queueId), queues = useServer(s => s.queues), setQueueId = useServer(s => s.setQueueId)
  return (
    <div className="iq-bar">
      <label className="iq-sel">Queue
        <select className="sel" value={queueId ?? ''} onChange={e => setQueueId(Number(e.target.value))} aria-label="Queue">
          {queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}
        </select>
      </label>
    </div>
  )
}

export function KindTag({ kind }: { kind: DataKind }) {
  const k = KIND[kind]
  return <Chip tone={k.tone}>{k.label}</Chip>
}

/** Always shown: says whether the numbers come from real or synthetic data. */
export function ProvenanceBanner({ p }: { p: Provenance | null | undefined }) {
  if (!p) return null
  return p.is_synthetic
    ? <div className="iq-banner synth" role="note"><Chip tone="demo">Synthetic data</Chip><span>{p.notice}</span></div>
    : <div className="iq-banner real" role="note"><Chip tone="ok">Real observations</Chip><span>Observed figures come from this queue’s database. Anything marked Simulated or Predicted is model output, not a measurement.</span></div>
}

export function Legend() {
  return (
    <div className="iq-legend" aria-label="Data kinds">
      {(Object.keys(KIND) as DataKind[]).map(k => <span key={k}><KindTag kind={k} /></span>)}
    </div>
  )
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="twin-note iq-note"><Info size={12} aria-hidden /> {children}</p>
}

const OP_KEY = 'lz.operator'
export function useOperator() {
  const [name, setName] = useState(() => { try { return localStorage.getItem(OP_KEY) ?? '' } catch { return '' } })
  const set = (v: string) => { setName(v); try { localStorage.setItem(OP_KEY, v) } catch { /* storage unavailable */ } }
  return [name, set] as const
}

export function OperatorField({ name, setName }: { name: string; setName(v: string): void }) {
  return (
    <label className="iq-sel">Operator name
      <input className="in" value={name} maxLength={120} placeholder="Required for decisions" onChange={e => setName(e.target.value)} aria-label="Operator name" />
    </label>
  )
}
