import { useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { PolicyList, SlaPolicy } from '../../api/slaTypes'
import { CLASS_PATTERN, validatePolicy } from '../../lib/sla'
import { Card, Chip, Confirm, EmptyState, Skeleton, toast } from '../ui/kit'
import { Note, OperatorField } from '../intelligence/shared'

interface Draft { service_class: string; label: string; max_wait_min: string; at_risk: string; critical: string; isNew: boolean }
const blank = (cls: string, isNew: boolean): Draft => ({ service_class: cls, label: '', max_wait_min: '10', at_risk: '25', critical: '60', isNew })

export default function SlaTargets({ queueId, data, op, setOp, onChanged }: { queueId: number; data: PolicyList | null; op: string; setOp(v: string): void; onChanged(): void }) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [del, setDel] = useState<SlaPolicy | null>(null)
  const [busy, setBusy] = useState(false)
  if (!data) return <Skeleton h={200} />
  const hasStandard = data.configured

  const edit = (p: SlaPolicy) => setDraft({ service_class: p.service_class, label: p.label ?? '', max_wait_min: String(p.max_wait_min), at_risk: String(Math.round(p.at_risk_probability * 100)), critical: String(Math.round(p.critical_probability * 100)), isNew: false })
  const save = async () => {
    if (!draft) return
    const maxWait = Number(draft.max_wait_min), ar = Number(draft.at_risk) / 100, cr = Number(draft.critical) / 100
    if (!op.trim()) { toast('Enter your operator name first', true); return }
    if (draft.isNew && !CLASS_PATTERN.test(draft.service_class)) { toast('Class name: lowercase letters, digits, - or _ (max 40)', true); return }
    const problem = validatePolicy(maxWait, ar, cr)
    if (problem) { toast(problem, true); return }
    setBusy(true)
    try {
      await api(`/sla/${queueId}/policies/${draft.service_class}`, { method: 'PUT', body: { max_wait_min: maxWait, at_risk_probability: ar, critical_probability: cr, label: draft.label.trim() || null, operator: op.trim() } })
      toast(`Saved the “${draft.service_class}” target`); setDraft(null); onChanged()
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!del) return
    if (!op.trim()) { toast('Enter your operator name first', true); setDel(null); return }
    try { await api(`/sla/${queueId}/policies/${del.service_class}`, { method: 'DELETE', params: { operator: op.trim() } }); toast('Target removed'); onChanged() }
    catch (e) { toast(errMsg(e), true) } finally { setDel(null) }
  }
  return (
    <div className="iq-stack">
      {!hasStandard && <div className="banner warn" role="status"><span><b>No SLA target yet.</b> LineZero does not assume one. Set the maximum acceptable waiting time for this queue to start predicting breaches and measuring compliance.</span></div>}
      <Card title="SLA targets" sub={data.note} right={<OperatorField name={op} setName={setOp} />}>
        {data.policies.length === 0 ? (
          <EmptyState title="No targets defined" text="Define the standard target first; it applies to every customer without a service class."
            action={<button className="btn p" onClick={() => setDraft(blank('standard', true))}><Plus size={14} />Set standard target</button>} />
        ) : (
          <>
            <div className="tw"><table className="tbl"><thead><tr><th>Class</th><th>Max wait</th><th>At risk from</th><th>Critical from</th><th>Updated</th><th /></tr></thead>
              <tbody>{data.policies.map(p => (
                <tr key={p.id}><td><b>{p.service_class}</b>{p.label ? <div className="twin-note">{p.label}</div> : null}</td><td className="mono">{p.max_wait_min} min</td>
                  <td className="mono">{Math.round(p.at_risk_probability * 100)}%</td><td className="mono">{Math.round(p.critical_probability * 100)}%</td>
                  <td className="twin-note">{p.updated_by} · {new Date(p.updated_at).toLocaleString()}</td>
                  <td><div className="iq-actions"><button className="btn sm" onClick={() => edit(p)} aria-label={`Edit ${p.service_class}`}><Pencil size={12} />Edit</button>
                    <button className="btn sm" onClick={() => setDel(p)} aria-label={`Delete ${p.service_class}`}><Trash2 size={12} /></button></div></td></tr>))}</tbody></table></div>
            <div className="iq-actions" style={{ marginTop: 10 }}><button className="btn" onClick={() => setDraft(blank('', true))}><Plus size={14} />Add service class</button></div>
          </>)}
        <Note>A customer is “at risk” when the chance of exceeding the target reaches the first percentage, and “critical” at the second. A service class changes the target only, not the order of service.</Note>
      </Card>

      {draft && (
        <Card title={draft.isNew ? 'New SLA target' : `Edit “${draft.service_class}”`} sub="Saved in the database and applied immediately to every figure on this page">
          <form className="iq-bar" onSubmit={e => { e.preventDefault(); void save() }}>
            <label className="iq-sel">Service class<input className="in" value={draft.service_class} disabled={!draft.isNew || (!hasStandard)} maxLength={40} placeholder="e.g. priority" aria-label="Service class" onChange={e => setDraft({ ...draft, service_class: e.target.value.toLowerCase() })} /></label>
            <label className="iq-sel">Label (optional)<input className="in" value={draft.label} maxLength={120} aria-label="Label" onChange={e => setDraft({ ...draft, label: e.target.value })} /></label>
            <label className="iq-sel">Maximum wait (minutes)<input className="in" type="number" min={0.5} max={1440} step={0.5} value={draft.max_wait_min} aria-label="Maximum wait in minutes" onChange={e => setDraft({ ...draft, max_wait_min: e.target.value })} /></label>
            <label className="iq-sel">At risk from (% probability)<input className="in" type="number" min={1} max={98} value={draft.at_risk} aria-label="At risk probability percent" onChange={e => setDraft({ ...draft, at_risk: e.target.value })} /></label>
            <label className="iq-sel">Critical from (% probability)<input className="in" type="number" min={2} max={99} value={draft.critical} aria-label="Critical probability percent" onChange={e => setDraft({ ...draft, critical: e.target.value })} /></label>
            <div className="iq-actions"><button className="btn p" type="submit" disabled={busy}>Save target</button><button className="btn" type="button" onClick={() => setDraft(null)}>Cancel</button></div>
          </form>
          {draft.isNew && !hasStandard && draft.service_class !== 'standard' && <Note>Define the “standard” class first.</Note>}
        </Card>)}
      {del && <Confirm title={`Remove “${del.service_class}” target?`} confirmLabel="Remove" onConfirm={() => void remove()} onClose={() => setDel(null)}
        text={del.service_class === 'standard' ? 'Customers without a class will have no SLA target until you set a new standard target.' : 'Customers in this class fall back to the standard target.'} />}
      {data.policies.some(p => p.service_class === 'standard') || null}
      <Chip>{data.queue.name}</Chip>
    </div>
  )
}
