import type { ReactNode } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Card, Field, cx } from '../ui/kit'
import { nextId, type FormErrors, type TwinForm } from '../../lib/twinPlayback'

type StrKey = 'arrival_rate' | 'mean_service_time' | 'num_counters' | 'duration' | 'seed' | 'replications' | 'staff' | 'speed_pct' | 'patience'
interface P { form: TwinForm; setForm: (f: TwinForm) => void; errors: FormErrors }

export function NumField({ form, setForm, errors, k, label, hint }: P & { k: StrKey; label: string; hint?: string }) {
  return (
    <Field label={label} error={errors[k]} hint={hint}>
      <input className={cx('in', errors[k] && 'bad')} inputMode="decimal" value={form[k]} onChange={e => setForm({ ...form, [k]: e.target.value })} aria-invalid={!!errors[k]} />
    </Field>
  )
}

function CounterSelect({ n, value, onChange, all }: { n: number; value: number | 'all'; onChange(v: number | 'all'): void; all?: boolean }) {
  return (
    <select className="sel" value={String(value)} onChange={e => onChange(e.target.value === 'all' ? 'all' : Number(e.target.value))} aria-label="Counter">
      {all && <option value="all">All counters</option>}
      {Array.from({ length: Math.max(1, n) }, (_, i) => <option key={i} value={i}>Counter {i + 1}</option>)}
    </select>
  )
}
const mini = (label: string, child: ReactNode) => <label className="fld"><span>{label}</span>{child}</label>

export default function ScenarioForm({ form, setForm, errors }: P) {
  const n = Math.max(1, Math.min(40, Math.floor(Number(form.num_counters)) || 1))
  const p = { form, setForm, errors }
  const txt = (v: string, set: (s: string) => void) => <input className="in" inputMode="decimal" value={v} onChange={e => set(e.target.value)} />
  return (
    <Card title="Scenario builder" sub="Time unit: minutes">
      <div className="grid g2" style={{ gap: 10 }}>
        <NumField {...p} k="arrival_rate" label="Arrival rate (/min)" />
        <NumField {...p} k="mean_service_time" label="Service duration (min)" />
        <NumField {...p} k="num_counters" label="Counters" />
        <NumField {...p} k="staff" label="Staff available" hint="blank = all counters staffed" />
        <NumField {...p} k="speed_pct" label="Counter speed (%)" hint="100 = nominal" />
        <NumField {...p} k="duration" label="Simulation duration (min)" />
        <NumField {...p} k="seed" label="Random seed" />
        <NumField {...p} k="replications" label="Replications" hint="independent seeds" />
        <Field label="Assignment strategy">
          <select className="sel" value={form.assignment} onChange={e => setForm({ ...form, assignment: e.target.value as TwinForm['assignment'] })}>
            <option value="longest_idle">Longest idle first</option><option value="lowest_index">Lowest index first</option>
          </select>
        </Field>
        <Field label="Customer abandonment" error={errors.patience}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', height: 38 }}><input type="checkbox" checked={form.abandon} onChange={e => setForm({ ...form, abandon: e.target.checked })} />Customers leave</label>
        </Field>
        {form.abandon && <NumField {...p} k="patience" label="Mean patience (min)" />}
      </div>

      <h4 style={{ margin: '16px 0 6px' }}>Chaos events</h4>
      <p className="twin-note" style={{ margin: '0 0 8px' }}>Failures finish the customer already being served, then take the counter offline.</p>

      {form.outages.map(o => (
        <div key={o.id}>
          <div className="row-in">
            {mini('Failure / outage', <CounterSelect n={n} value={o.counter} onChange={v => setForm({ ...form, outages: form.outages.map(x => (x.id === o.id ? { ...x, counter: v === 'all' ? 0 : v } : x)) })} />)}
            {mini('From (min)', txt(o.start, s => setForm({ ...form, outages: form.outages.map(x => (x.id === o.id ? { ...x, start: s } : x)) })))}
            {mini('Repaired at', txt(o.end, s => setForm({ ...form, outages: form.outages.map(x => (x.id === o.id ? { ...x, end: s } : x)) })))}
            <button className="btn sm g ic" aria-label="Remove outage" onClick={() => setForm({ ...form, outages: form.outages.filter(x => x.id !== o.id) })}><Trash2 size={14} /></button>
          </div>
          {errors[`outage${o.id}`] && <div className="err" role="alert">{errors[`outage${o.id}`]}</div>}
        </div>
      ))}
      {form.surges.map(s => (
        <div key={s.id}>
          <div className="row-in">
            {mini('Arrival surge from', txt(s.start, v => setForm({ ...form, surges: form.surges.map(x => (x.id === s.id ? { ...x, start: v } : x)) })))}
            {mini('To (min)', txt(s.end, v => setForm({ ...form, surges: form.surges.map(x => (x.id === s.id ? { ...x, end: v } : x)) })))}
            {mini('× arrivals', txt(s.multiplier, v => setForm({ ...form, surges: form.surges.map(x => (x.id === s.id ? { ...x, multiplier: v } : x)) })))}
            <button className="btn sm g ic" aria-label="Remove surge" onClick={() => setForm({ ...form, surges: form.surges.filter(x => x.id !== s.id) })}><Trash2 size={14} /></button>
          </div>
          {errors[`surge${s.id}`] && <div className="err" role="alert">{errors[`surge${s.id}`]}</div>}
        </div>
      ))}
      {form.slowdowns.map(s => (
        <div key={s.id}>
          <div className="row-in">
            {mini('Slow service on', <CounterSelect all n={n} value={s.counter} onChange={v => setForm({ ...form, slowdowns: form.slowdowns.map(x => (x.id === s.id ? { ...x, counter: v } : x)) })} />)}
            {mini('From (min)', txt(s.start, v => setForm({ ...form, slowdowns: form.slowdowns.map(x => (x.id === s.id ? { ...x, start: v } : x)) })))}
            {mini('Until', txt(s.end, v => setForm({ ...form, slowdowns: form.slowdowns.map(x => (x.id === s.id ? { ...x, end: v } : x)) })))}
            {mini('Speed ×', txt(s.factor, v => setForm({ ...form, slowdowns: form.slowdowns.map(x => (x.id === s.id ? { ...x, factor: v } : x)) })))}
            <button className="btn sm g ic" aria-label="Remove slowdown" onClick={() => setForm({ ...form, slowdowns: form.slowdowns.filter(x => x.id !== s.id) })}><Trash2 size={14} /></button>
          </div>
          {errors[`slow${s.id}`] && <div className="err" role="alert">{errors[`slow${s.id}`]}</div>}
        </div>
      ))}
      <div className="toolbar">
        <button className="btn sm" onClick={() => setForm({ ...form, outages: [...form.outages, { id: nextId(), counter: 0, start: '20', end: '' }] })}><Plus size={13} />Counter failure</button>
        <button className="btn sm" onClick={() => setForm({ ...form, surges: [...form.surges, { id: nextId(), start: '30', end: '60', multiplier: '2' }] })}><Plus size={13} />Arrival surge</button>
        <button className="btn sm" onClick={() => setForm({ ...form, slowdowns: [...form.slowdowns, { id: nextId(), counter: 'all', start: '20', end: '', factor: '0.6' }] })}><Plus size={13} />Slow service</button>
      </div>

      <h4 style={{ margin: '16px 0 6px' }}>Reserve counters</h4>
      <p className="twin-note" style={{ margin: '0 0 6px' }}>Counters that start closed and can be opened by recovery actions.</p>
      <div className="toolbar">
        {Array.from({ length: n }, (_, i) => (
          <label key={i} className="chip" style={{ cursor: 'pointer', gap: 6 }}>
            <input type="checkbox" checked={form.standby.includes(i)} onChange={e => setForm({ ...form, standby: e.target.checked ? [...form.standby, i] : form.standby.filter(x => x !== i) })} />C{i + 1}
          </label>
        ))}
      </div>
      {errors.standby && <div className="err">{errors.standby}</div>}
    </Card>
  )
}
