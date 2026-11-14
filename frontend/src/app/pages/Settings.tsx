import { useState } from 'react'
import { Plus, Trash2, Pencil, Pause, Play, RotateCcw } from 'lucide-react'
import { useStore } from '../../store/store'
import type { Counter, Queue, Settings as S } from '../../store/types'
import { hasErrors, nameValid, numberIn } from '../../lib/validate'
import { Card, Chip, Confirm, DemoBadge, EmptyState, Field, PageHeader, Seg, cx, toast } from '../ui/kit'
import { CounterModal, QueueModal } from './Monitor'

type Tab = 'queues' | 'counters' | 'sim' | 'display' | 'notify' | 'data'

export default function Settings() {
  const [tab, setTab] = useState<Tab>('queues')
  return (
    <div className="page">
      <PageHeader title="Settings" sub="Configure queues, counters, simulation defaults and how LineZero looks and alerts." demo={false} />
      <div className="toolbar" style={{ overflowX: 'auto' }}><Seg<Tab> value={tab} onChange={setTab} label="Settings section" options={[{ v: 'queues', l: 'Queue configuration' }, { v: 'counters', l: 'Service counters' }, { v: 'sim', l: 'Simulation defaults' }, { v: 'display', l: 'Display' }, { v: 'notify', l: 'Notifications' }, { v: 'data', l: 'Data' }]} /></div>
      {tab === 'queues' && <QueuesTab />}{tab === 'counters' && <CountersTab />}{tab === 'sim' && <SimTab />}{tab === 'display' && <DisplayTab />}{tab === 'notify' && <NotifyTab />}{tab === 'data' && <DataTab />}
    </div>
  )
}

function QueueRow({ q }: { q: Queue }) {
  const queues = useStore(s => s.queues), rename = useStore(s => s.renameQueue), upd = useStore(s => s.updateQueue), del = useStore(s => s.deleteQueue)
  const [name, setName] = useState(q.name), [rate, setRate] = useState(String(q.arrivalRate)), [pre, setPre] = useState(q.prefix), [confirm, setConfirm] = useState(false)
  const nErr = nameValid(name, queues.filter(x => x.id !== q.id).map(x => x.name), 'Name'), rErr = numberIn(rate, 0.01, 10, 'Rate'), pErr = /^[A-Za-z]{1,3}$/.test(pre) ? undefined : '1–3 letters'
  return (
    <tr>
      <td><input className={cx('in', nErr && 'bad')} aria-label="Queue name" value={name} maxLength={40} onChange={e => setName(e.target.value)} onBlur={() => { if (!nErr && name.trim() !== q.name) { rename(q.id, name); toast('Queue renamed') } else if (nErr) setName(q.name) }} />{nErr && <div className="err">{nErr}</div>}</td>
      <td style={{ width: 90 }}><input className={cx('in', pErr && 'bad')} aria-label="Ticket prefix" value={pre} maxLength={3} onChange={e => setPre(e.target.value)} onBlur={() => { if (!pErr) upd(q.id, { prefix: pre.toUpperCase() }); else setPre(q.prefix) }} /></td>
      <td style={{ width: 130 }}><input className={cx('in', rErr && 'bad')} aria-label="Arrivals per minute" inputMode="decimal" value={rate} onChange={e => setRate(e.target.value)} onBlur={() => { if (!rErr) upd(q.id, { arrivalRate: Number(rate) }); else setRate(String(q.arrivalRate)) }} />{rErr && <div className="err">{rErr}</div>}</td>
      <td style={{ width: 170 }}><select className="sel" aria-label="Routing" value={q.routing} onChange={e => upd(q.id, { routing: e.target.value as Queue['routing'] })}><option value="shortest">Shortest line</option><option value="weighted">Weighted</option></select></td>
      <td style={{ width: 50 }}><button className="btn sm g ic" aria-label={`Delete ${q.name}`} onClick={() => setConfirm(true)}><Trash2 size={15} /></button>
        {confirm && <Confirm title={`Delete “${q.name}”?`} text="Its counters and waiting customers are removed too." onClose={() => setConfirm(false)} onConfirm={() => { del(q.id); toast('Queue deleted') }} />}</td>
    </tr>
  )
}
function QueuesTab() {
  const queues = useStore(s => s.queues), [create, setCreate] = useState(false)
  return (
    <Card title="Queue configuration" sub="Changes save when you leave a field. Arrival rate is the baseline for demo arrivals." right={<><DemoBadge /><button className="btn p sm" onClick={() => setCreate(true)}><Plus size={14} />New queue</button></>}>
      {!queues.length ? <EmptyState title="No queues" text="Create a queue to configure it." action={<button className="btn p" onClick={() => setCreate(true)}>New queue</button>} />
        : <div className="tw"><table className="tbl"><thead><tr><th>Name</th><th>Prefix</th><th>Arrivals / min</th><th>Routing</th><th /></tr></thead><tbody>{queues.map(q => <QueueRow key={q.id} q={q} />)}</tbody></table></div>}
      {create && <QueueModal onClose={() => setCreate(false)} />}
    </Card>
  )
}

function CountersTab() {
  const queues = useStore(s => s.queues), counters = useStore(s => s.counters), toggle = useStore(s => s.toggleCounter), del = useStore(s => s.deleteCounter)
  const [modal, setModal] = useState<null | { queueId: string; counter?: Counter }>(null), [rm, setRm] = useState<Counter | null>(null)
  if (!queues.length) return <Card><EmptyState title="No queues" text="Create a queue first, then add its service counters." /></Card>
  return (<>
    {queues.map(q => (
      <Card key={q.id} title={q.name} right={<button className="btn sm" onClick={() => setModal({ queueId: q.id })}><Plus size={14} />Add counter</button>}>
        {counters.filter(c => c.queueId === q.id).length === 0 ? <EmptyState title="No counters" text="Add a counter so this queue can serve customers." />
          : <div className="tw"><table className="tbl"><thead><tr><th>Counter</th><th>Capacity</th><th>Avg service</th><th>Status</th><th /></tr></thead><tbody>
            {counters.filter(c => c.queueId === q.id).map(c => <tr key={c.id}><td>{c.name}</td><td className="mono">{c.servers} parallel</td><td className="mono">{c.avgService} min</td><td><Chip tone={c.status === 'active' ? 'ok' : 'warn'}>{c.status}</Chip></td>
              <td><div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}><button className="btn sm g ic" aria-label={`${c.status === 'active' ? 'Pause' : 'Resume'} ${c.name}`} onClick={() => toggle(c.id)}>{c.status === 'active' ? <Pause size={15} /> : <Play size={15} />}</button><button className="btn sm g ic" aria-label={`Edit ${c.name}`} onClick={() => setModal({ queueId: q.id, counter: c })}><Pencil size={15} /></button><button className="btn sm g ic" aria-label={`Remove ${c.name}`} onClick={() => setRm(c)}><Trash2 size={15} /></button></div></td></tr>)}
          </tbody></table></div>}
      </Card>
    ))}
    {modal && <CounterModal queueId={modal.queueId} counter={modal.counter} onClose={() => setModal(null)} />}
    {rm && <Confirm title={`Remove ${rm.name}?`} text="Its customers are re-queued to other counters." confirmLabel="Remove" onClose={() => setRm(null)} onConfirm={() => { del(rm.id); toast('Counter removed') }} />}
  </>)
}

type SimKey = keyof S['sim']
const SIMF: { k: SimKey; label: string; min: number; max: number; int?: boolean }[] = [
  { k: 'arrivalRate', label: 'Arrival rate (/min)', min: 0.1, max: 8 }, { k: 'avgService', label: 'Average service time (min)', min: 0.5, max: 30 }, { k: 'counters', label: 'Counters', min: 1, max: 20, int: true },
  { k: 'duration', label: 'Duration (min)', min: 10, max: 480, int: true }, { k: 'arrivalCV', label: 'Arrival variability (CV)', min: 0, max: 2 }, { k: 'serviceCV', label: 'Service variability (CV)', min: 0, max: 2 }, { k: 'seed', label: 'Seed', min: 1, max: 999999, int: true },
]
function SimTab() {
  const sim = useStore(s => s.settings.sim), upd = useStore(s => s.updateSettings)
  const [f, setF] = useState(Object.fromEntries(SIMF.map(x => [x.k, String(sim[x.k])])) as Record<SimKey, string>)
  const errs = Object.fromEntries(SIMF.map(x => [x.k, numberIn(f[x.k], x.min, x.max, x.label, x.int)]).filter(([, v]) => v))
  return (
    <Card title="Simulation defaults" sub="Used to pre-fill the Queue Simulator.">
      <div className="grid g3">{SIMF.map(x => <Field key={x.k} label={x.label} error={errs[x.k]}><input className={cx('in', errs[x.k] && 'bad')} inputMode="decimal" value={f[x.k]} onChange={e => setF({ ...f, [x.k]: e.target.value })} /></Field>)}</div>
      <div className="toolbar" style={{ marginTop: 16 }}>
        <button className="btn p" disabled={hasErrors(errs)} onClick={() => { upd({ sim: Object.fromEntries(SIMF.map(x => [x.k, Number(f[x.k])])) as unknown as S['sim'] }); toast('Simulation defaults saved') }}>Save defaults</button>
        <span className="hint">Open the simulator after saving to use them.</span>
      </div>
    </Card>
  )
}

function Toggle({ label, hint, on, set }: { label: string; hint?: string; on: boolean; set(v: boolean): void }) {
  return <label className="chk" style={{ alignItems: 'flex-start', padding: '10px 0', borderBottom: '1px solid #131e35' }}><input type="checkbox" checked={on} onChange={e => set(e.target.checked)} /><span><b style={{ fontWeight: 500 }}>{label}</b>{hint && <div className="hint">{hint}</div>}</span></label>
}
function DisplayTab() {
  const st = useStore(s => s.settings), upd = useStore(s => s.updateSettings)
  const [t, setT] = useState({ highUtil: String(st.thresholds.highUtil * 100), lowUtil: String(st.thresholds.lowUtil * 100), waitSla: String(st.thresholds.waitSla) })
  const e = { highUtil: numberIn(t.highUtil, 50, 100, 'High-utilization limit'), lowUtil: numberIn(t.lowUtil, 0, 60, 'Low-utilization floor'), waitSla: numberIn(t.waitSla, 1, 120, 'Target wait') }
  const cross = !e.highUtil && !e.lowUtil && Number(t.lowUtil) >= Number(t.highUtil) ? 'Floor must be below the limit' : undefined
  return (<div className="grid g2">
    <Card title="Display preferences">
      <Field label="Density"><Seg<S['density']> value={st.density} onChange={v => upd({ density: v })} label="Density" options={[{ v: 'comfortable', l: 'Comfortable' }, { v: 'compact', l: 'Compact' }]} /></Field>
      <div style={{ height: 14 }} /><Field label="Time format"><Seg<S['timeFormat']> value={st.timeFormat} onChange={v => upd({ timeFormat: v })} label="Time format" options={[{ v: '24h', l: '24-hour' }, { v: '12h', l: '12-hour' }]} /></Field>
      <div style={{ height: 14 }} /><Field label="Demo feed speed" hint="Real time per demo minute"><select className="sel" value={st.tickMs} onChange={ev => upd({ tickMs: Number(ev.target.value) })}><option value={3000}>Slow · 3 s</option><option value={1500}>Normal · 1.5 s</option><option value={700}>Fast · 0.7 s</option><option value={300}>Very fast · 0.3 s</option></select></Field>
      <Toggle label="Animate charts" hint="Turn off for a calmer, faster dashboard" on={st.animateCharts} set={v => upd({ animateCharts: v })} />
    </Card>
    <Card title="Alert thresholds" sub="Used by alerts, risk scores and the Bottleneck Investigator">
      <div style={{ display: 'grid', gap: 14 }}>
        <Field label="High-utilization limit (%)" error={e.highUtil}><input className={cx('in', e.highUtil && 'bad')} inputMode="numeric" value={t.highUtil} onChange={x => setT({ ...t, highUtil: x.target.value })} /></Field>
        <Field label="Low-utilization floor (%)" error={e.lowUtil ?? cross}><input className={cx('in', (e.lowUtil || cross) && 'bad')} inputMode="numeric" value={t.lowUtil} onChange={x => setT({ ...t, lowUtil: x.target.value })} /></Field>
        <Field label="Target wait (min)" error={e.waitSla}><input className={cx('in', e.waitSla && 'bad')} inputMode="decimal" value={t.waitSla} onChange={x => setT({ ...t, waitSla: x.target.value })} /></Field>
        <div><button className="btn p" disabled={!!(e.highUtil || e.lowUtil || e.waitSla || cross)} onClick={() => { upd({ thresholds: { highUtil: Number(t.highUtil) / 100, lowUtil: Number(t.lowUtil) / 100, waitSla: Number(t.waitSla) } }); toast('Thresholds saved') }}>Save thresholds</button></div>
      </div>
    </Card>
  </div>)
}
function NotifyTab() {
  const n = useStore(s => s.settings.notify), upd = useStore(s => s.updateSettings)
  const set = (k: keyof S['notify'], v: boolean) => upd({ notify: { ...n, [k]: v } })
  return (
    <Card title="Notification preferences" sub="Which demo events raise notifications in the bell menu">
      <Toggle label="Congestion and long-wait alerts" hint="When a queue's risk score is High or its estimated wait is well above target" on={n.longWait} set={v => set('longWait', v)} />
      <Toggle label="High counter utilization" hint="When a counter exceeds the high-utilization limit" on={n.highUtil} set={v => set('highUtil', v)} />
      <Toggle label="Arrival spikes" hint="Surges compared with the expected demand profile" on={n.spike} set={v => set('spike', v)} />
      <Toggle label="System messages" on={n.system} set={v => set('system', v)} />
    </Card>
  )
}
function DataTab() {
  const reset = useStore(s => s.resetDemo), [c, setC] = useState(false)
  return (
    <Card title="Data" right={<DemoBadge />}>
      <p style={{ color: 'var(--muted)', marginTop: 0 }}>LineZero is running in <b style={{ color: 'var(--text)' }}>demo mode</b>: all queues, customers and history are synthetic and stored only in this browser. No backend or live institutional feed is connected in this phase.</p>
      <button className="btn d" onClick={() => setC(true)}><RotateCcw size={16} />Reset demo data</button>
      {c && <Confirm title="Reset demo data?" text="Queues, counters, reports and settings return to the original synthetic workspace." confirmLabel="Reset" onClose={() => setC(false)} onConfirm={() => { reset(); toast('Demo data reset') }} />}
    </Card>
  )
}
