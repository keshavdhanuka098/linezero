import { useMemo, useState } from 'react'
import { Pause, Pencil, Play, Plus, Trash2, UserPlus, X, CheckCheck, Layers } from 'lucide-react'
import { useStore } from '../../store/store'
import type { Counter, Customer, Queue } from '../../store/types'
import { counterEstWait, fmtMin, pct, queueMetrics } from '../../lib/metrics'
import { hasErrors, nameValid, numberIn } from '../../lib/validate'
import { Bar, Card, Chip, Confirm, EmptyState, Field, Modal, PageHeader, Seg, cx, toast } from '../ui/kit'
import ServerMonitor from '../server/ServerMonitor'
import { useServerMode } from '../../api/serverStore'

function MonitorLocal() {
  const queues = useStore(s => s.queues), live = useStore(s => s.settings.liveFeed), setLive = useStore(s => s.setLive)
  const [creating, setCreating] = useState(false)
  const [filter, setFilter] = useState('all')
  const shown = filter === 'all' ? queues : queues.filter(q => q.id === filter)
  return (
    <div className="page">
      <PageHeader title="Live Queue Monitor" sub="Create queues, manage counters and move customers. Changes apply immediately.">
        <button className="btn" onClick={() => setLive(!live)}>{live ? <Pause size={16} /> : <Play size={16} />}{live ? 'Pause demo feed' : 'Resume demo feed'}</button>
        <button className="btn p" onClick={() => setCreating(true)}><Plus size={16} />New queue</button>
      </PageHeader>
      <div className="banner"><Layers size={16} style={{ flex: 'none', marginTop: 2 }} /><span><b>Demo simulation, not live institutional data.</b> While the demo feed is running, synthetic customers arrive and get served automatically (1 tick = 1 demo minute). Pause the feed to work on a static snapshot. Your manual actions are logged as “user” in recent activity.</span></div>
      {queues.length > 1 && <div className="toolbar"><Seg value={filter} onChange={setFilter} label="Queue filter" options={[{ v: 'all', l: 'All queues' }, ...queues.map(q => ({ v: q.id, l: q.name }))]} /></div>}
      {queues.length === 0 && <Card><EmptyState icon={Layers} title="No queues yet" text="Create a queue, add service counters, then add customers to watch the line move." action={<button className="btn p" onClick={() => setCreating(true)}><Plus size={16} />Create your first queue</button>} /></Card>}
      {shown.map(q => <QueueCard key={q.id} q={q} />)}
      {creating && <QueueModal onClose={() => setCreating(false)} />}
    </div>
  )
}

function QueueCard({ q }: { q: Queue }) {
  const counters = useStore(s => s.counters), st = useStore()
  const th = st.settings.thresholds
  const cs = useMemo(() => counters.filter(c => c.queueId === q.id), [counters, q.id])
  const m = queueMetrics(q, counters)
  const [modal, setModal] = useState<null | 'rename' | 'delete' | 'counter' | 'customer'>(null)
  const nowServing = cs.flatMap(c => c.serving).sort((a, b) => (a.startedAt ?? 0) - (b.startedAt ?? 0)).map(c => c.ticket)
  const stats: [string, string | number][] = [
    ['Queue length', m.length], ['People waiting', m.waiting], ['Now serving', nowServing.length ? nowServing[nowServing.length - 1] : '—'],
    ['Counters active', `${m.activeCounters}/${cs.length}`], ['Est. wait', fmtMin(m.estWait)], ['Avg service', fmtMin(m.avgService)],
  ]
  return (
    <Card className="qcard" hl={m.maxUtil >= th.highUtil}>
      <div className="qhead">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ fontSize: 18 }}>{q.name}</h3><Chip tone="vio">{q.prefix}-tickets</Chip>
          <Chip tone={q.routing === 'shortest' ? 'ok' : 'warn'}>{q.routing === 'shortest' ? 'Routing: shortest line' : 'Routing: weighted'}</Chip>
          {Number.isFinite(m.estWait) && m.estWait > th.waitSla && <Chip tone="hot">Wait above {th.waitSla}m target</Chip>}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button className="btn sm p" onClick={() => setModal('customer')}><UserPlus size={14} />Add customer</button>
          <button className="btn sm" onClick={() => setModal('counter')}><Plus size={14} />Add counter</button>
          <button className="btn sm g ic" aria-label={`Rename ${q.name}`} title="Rename" onClick={() => setModal('rename')}><Pencil size={14} /></button>
          <button className="btn sm g ic" aria-label={`Delete ${q.name}`} title="Delete queue" onClick={() => setModal('delete')}><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="qstats">{stats.map(([k, v]) => <div key={k}><small>{k}</small><b>{v}</b></div>)}</div>
      {q.holding.length > 0 && (
        <div className="why" style={{ borderColor: 'rgba(245,184,75,.4)' }}>
          <b>{q.holding.length} unassigned</b> — no active counter available to take them:
          <div className="pips" style={{ marginTop: 6 }}>{q.holding.slice(0, 12).map(c => <Pip key={c.id} c={c} />)}</div>
        </div>
      )}
      {cs.length === 0 ? <EmptyState title="No counters in this queue" text="Add a service counter so customers can be served." action={<button className="btn t" onClick={() => setModal('counter')}><Plus size={14} />Add counter</button>} /> : (
        <div className="cgrid">{cs.map(c => <CounterCard key={c.id} c={c} q={q} hot={c.utilEma >= th.highUtil} />)}</div>
      )}
      {modal === 'rename' && <RenameModal q={q} onClose={() => setModal(null)} />}
      {modal === 'delete' && <Confirm title={`Delete “${q.name}”?`} text={`This removes the queue, its ${cs.length} counter(s) and ${m.length} customer(s) in line. This cannot be undone.`} onClose={() => setModal(null)} onConfirm={() => { st.deleteQueue(q.id); toast('Queue deleted') }} />}
      {modal === 'counter' && <CounterModal queueId={q.id} onClose={() => setModal(null)} />}
      {modal === 'customer' && <CustomerModal q={q} onClose={() => setModal(null)} />}
    </Card>
  )
}

function Pip({ c, serving, canRemove = true }: { c: Customer; serving?: boolean; canRemove?: boolean }) {
  const rm = useStore(s => s.removeCustomer)
  return <span className={cx('pip', serving && 'srv')} title={c.label}>{c.ticket}{canRemove && <button aria-label={`Remove ${c.ticket}`} onClick={() => { rm(c.id); toast(`${c.ticket} removed`) }}><X size={12} /></button>}</span>
}

function CounterCard({ c, q, hot }: { c: Counter; q: Queue; hot: boolean }) {
  const st = useStore()
  const [all, setAll] = useState(false), [edit, setEdit] = useState(false), [del, setDel] = useState(false)
  const wait = counterEstWait(c)
  const list = all ? c.waiting : c.waiting.slice(0, 6)
  return (
    <div className={cx('cc', c.status === 'paused' && 'paused', hot && 'hot')}>
      <div className="row"><b style={{ fontWeight: 600 }}>{c.name}</b><Chip tone={c.status === 'active' ? 'ok' : 'warn'}>{c.status === 'active' ? 'Active' : 'Paused'}</Chip></div>
      <div className="row" style={{ fontSize: 12, color: 'var(--muted)' }}><span>Capacity {c.servers} parallel · avg {fmtMin(c.avgService)}</span><span>Est. wait {fmtMin(wait)}</span></div>
      <div><div className="row" style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}><span>Utilization</span><span className="mono">{pct(c.utilEma)}</span></div><Bar v={c.utilEma} tone={hot ? 'hot' : c.utilEma > 0.7 ? 'warm' : undefined} /></div>
      <div><small style={{ color: 'var(--muted)', fontSize: 11 }}>Serving ({c.serving.length}/{c.servers})</small><div className="pips">{c.serving.length ? c.serving.map(x => <Pip key={x.id} c={x} serving />) : <span style={{ color: '#58698a', fontSize: 12 }}>Idle</span>}</div></div>
      <div><small style={{ color: 'var(--muted)', fontSize: 11 }}>Waiting ({c.waiting.length})</small>
        <div className="pips">{c.waiting.length ? list.map(x => <Pip key={x.id} c={x} />) : <span style={{ color: '#58698a', fontSize: 12 }}>No one waiting</span>}
          {c.waiting.length > 6 && <button className="pip more" style={{ cursor: 'pointer' }} onClick={() => setAll(a => !a)}>{all ? 'Show less' : `+${c.waiting.length - 6} more`}</button>}</div></div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button className="btn sm t" disabled={!c.serving.length} onClick={() => { st.completeNext(c.id); toast(`Service completed at ${c.name}`) }}><CheckCheck size={14} />Complete service</button>
        <button className="btn sm" onClick={() => st.toggleCounter(c.id)}>{c.status === 'active' ? <><Pause size={14} />Pause</> : <><Play size={14} />Resume</>}</button>
        <button className="btn sm g ic" aria-label={`Edit ${c.name}`} onClick={() => setEdit(true)}><Pencil size={14} /></button>
        <button className="btn sm g ic" aria-label={`Delete ${c.name}`} onClick={() => setDel(true)}><Trash2 size={14} /></button>
      </div>
      {edit && <CounterModal queueId={q.id} counter={c} onClose={() => setEdit(false)} />}
      {del && <Confirm title={`Remove ${c.name}?`} text="Customers at this counter will be re-queued to other counters in the same queue." confirmLabel="Remove counter" onClose={() => setDel(false)} onConfirm={() => { st.deleteCounter(c.id); toast('Counter removed') }} />}
    </div>
  )
}

export function QueueModal({ onClose }: { onClose(): void }) {
  const queues = useStore(s => s.queues), create = useStore(s => s.createQueue)
  const [f, setF] = useState({ name: '', prefix: '', arrivalRate: '0.3', routing: 'shortest' as Queue['routing'], counters: '2' })
  const [show, setShow] = useState(false)
  const errors = {
    name: nameValid(f.name, queues.map(q => q.name), 'Queue name'),
    prefix: f.prefix && !/^[A-Za-z]{1,3}$/.test(f.prefix) ? 'Use 1–3 letters' : undefined,
    arrivalRate: numberIn(f.arrivalRate, 0.01, 10, 'Arrival rate'),
    counters: numberIn(f.counters, 1, 12, 'Counters', true),
  }
  const clean = Object.fromEntries(Object.entries(errors).filter(([, v]) => v))
  const e = (k: keyof typeof errors) => (show ? errors[k] : undefined)
  const submit = () => {
    setShow(true)
    if (hasErrors(clean)) return
    create({ name: f.name, prefix: f.prefix || f.name.trim()[0], arrivalRate: Number(f.arrivalRate), routing: f.routing, counters: Number(f.counters) })
    toast('Queue created'); onClose()
  }
  return (
    <Modal title="Create queue" sub="Demo arrivals use this baseline rate, shaped by the daily demand profile." onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn p" onClick={submit}>Create queue</button></>}>
      <Field label="Queue name" error={e('name')}><input className={cx('in', e('name') && 'bad')} value={f.name} maxLength={40} onChange={x => setF({ ...f, name: x.target.value })} onKeyDown={k => k.key === 'Enter' && submit()} placeholder="e.g. Passport Renewals" /></Field>
      <div className="grid g2">
        <Field label="Ticket prefix" error={e('prefix')} hint="Optional, 1–3 letters"><input className={cx('in', e('prefix') && 'bad')} value={f.prefix} maxLength={3} onChange={x => setF({ ...f, prefix: x.target.value })} /></Field>
        <Field label="Counters" error={e('counters')}><input className={cx('in', e('counters') && 'bad')} inputMode="numeric" value={f.counters} onChange={x => setF({ ...f, counters: x.target.value })} /></Field>
        <Field label="Baseline arrivals / min" error={e('arrivalRate')}><input className={cx('in', e('arrivalRate') && 'bad')} inputMode="decimal" value={f.arrivalRate} onChange={x => setF({ ...f, arrivalRate: x.target.value })} /></Field>
        <Field label="Routing"><select className="sel" value={f.routing} onChange={x => setF({ ...f, routing: x.target.value as Queue['routing'] })}><option value="shortest">Shortest line</option><option value="weighted">Weighted (preferred counters)</option></select></Field>
      </div>
    </Modal>
  )
}

function RenameModal({ q, onClose }: { q: Queue; onClose(): void }) {
  const queues = useStore(s => s.queues), rename = useStore(s => s.renameQueue)
  const [name, setName] = useState(q.name), [show, setShow] = useState(false)
  const err = nameValid(name, queues.filter(x => x.id !== q.id).map(x => x.name), 'Queue name')
  const submit = () => { setShow(true); if (err) return; rename(q.id, name); toast('Queue renamed'); onClose() }
  return (
    <Modal title="Rename queue" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn p" onClick={submit}>Save</button></>}>
      <Field label="Queue name" error={show ? err : undefined}><input className={cx('in', show && err && 'bad')} value={name} maxLength={40} onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Enter' && submit()} /></Field>
    </Modal>
  )
}

export function CounterModal({ queueId, counter, onClose }: { queueId: string; counter?: Counter; onClose(): void }) {
  const counters = useStore(s => s.counters), add = useStore(s => s.addCounter), upd = useStore(s => s.updateCounter)
  const [f, setF] = useState({ name: counter?.name ?? '', servers: String(counter?.servers ?? 1), avg: String(counter?.avgService ?? 4) })
  const [show, setShow] = useState(false)
  const errors = {
    name: nameValid(f.name, counters.filter(c => c.queueId === queueId && c.id !== counter?.id).map(c => c.name), 'Counter name'),
    servers: numberIn(f.servers, 1, 10, 'Capacity', true), avg: numberIn(f.avg, 0.5, 60, 'Average service time'),
  }
  const bad = Object.values(errors).some(Boolean)
  const submit = () => {
    setShow(true); if (bad) return
    if (counter) upd(counter.id, { name: f.name.trim(), servers: Number(f.servers), avgService: Number(f.avg) }); else add(queueId, { name: f.name, servers: Number(f.servers), avgService: Number(f.avg) })
    toast(counter ? 'Counter updated' : 'Counter added'); onClose()
  }
  return (
    <Modal title={counter ? `Edit ${counter.name}` : 'Add service counter'} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn p" onClick={submit}>{counter ? 'Save changes' : 'Add counter'}</button></>}>
      <Field label="Counter name" error={show ? errors.name : undefined}><input className={cx('in', show && errors.name && 'bad')} value={f.name} maxLength={40} onChange={e => setF({ ...f, name: e.target.value })} placeholder="e.g. Counter 6" /></Field>
      <div className="grid g2">
        <Field label="Capacity (parallel customers)" error={show ? errors.servers : undefined} hint="Staff / stations serving at once"><input className={cx('in', show && errors.servers && 'bad')} inputMode="numeric" value={f.servers} onChange={e => setF({ ...f, servers: e.target.value })} /></Field>
        <Field label="Avg service time (min)" error={show ? errors.avg : undefined}><input className={cx('in', show && errors.avg && 'bad')} inputMode="decimal" value={f.avg} onChange={e => setF({ ...f, avg: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

function CustomerModal({ q, onClose }: { q: Queue; onClose(): void }) {
  const add = useStore(s => s.addCustomer)
  const [label, setLabel] = useState(''), [n, setN] = useState('1')
  const err = numberIn(n, 1, 25, 'Number of customers', true)
  const submit = () => { if (err) return; for (let i = 0; i < Number(n); i++) add(q.id, label); toast(`${n} customer${n === '1' ? '' : 's'} added to ${q.name}`); onClose() }
  return (
    <Modal title={`Add to ${q.name}`} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn p" onClick={submit}>Add</button></>}>
      <Field label="Name or note (optional)"><input className="in" value={label} maxLength={40} onChange={e => setLabel(e.target.value)} placeholder="e.g. Walk-in" /></Field>
      <Field label="How many?" error={err}><input className={cx('in', err && 'bad')} inputMode="numeric" value={n} onChange={e => setN(e.target.value)} /></Field>
    </Modal>
  )
}

export default function Monitor() {
  return useServerMode() ? <ServerMonitor /> : <MonitorLocal />
}
