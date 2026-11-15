import { useState } from 'react'
import { Bot, ShieldCheck } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { ExplainResponse, TwinStatus } from '../../api/twinTypes'
import { Card, Chip, Field, Spinner, toast } from '../ui/kit'
import { buildConfig, type TwinForm } from '../../lib/twinPlayback'
import { useAsync } from '../server/shared'
import type { SavedScenario } from './ComparePanel'

type Kind = 'congestion' | 'counter' | 'intervention' | 'scenarios'
const KINDS: { k: Kind; label: string }[] = [
  { k: 'congestion', label: 'Why did congestion occur?' }, { k: 'counter', label: 'Which counter is overloaded?' },
  { k: 'intervention', label: 'Which intervention works best?' }, { k: 'scenarios', label: 'How do my scenarios differ?' },
]

export default function ExplainPanel({ form, errors, scenarios }: { form: TwinForm; errors: Record<string, string>; scenarios: SavedScenario[] }) {
  const status = useAsync(() => api<TwinStatus>('/twin/status'), [])
  const [busy, setBusy] = useState<Kind | null>(null)
  const [out, setOut] = useState<ExplainResponse | null>(null)
  const [question, setQuestion] = useState('')
  const invalid = Object.keys(errors).length > 0

  const ask = async (kind: Kind) => {
    setBusy(kind)
    try {
      const body = kind === 'scenarios'
        ? { kind, scenarios: scenarios.map(s => ({ name: s.name, configuration: buildConfig(s.form) })), replications: 5, seed: Number(form.seed), question: question.trim() || null }
        : { kind, configuration: buildConfig({ ...form, actions: kind === 'intervention' ? [] : form.actions }), replications: Math.max(2, Math.min(10, Number(form.replications) || 5)), seed: Number(form.seed), question: question.trim() || null }
      setOut(await api<ExplainResponse>('/twin/explain', { method: 'POST', body }))
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(null) }
  }
  const g = status.data?.gemini

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Card title="Explain the simulation" sub="Explanations are built from metrics the simulator just computed"
        right={<Chip tone={g?.configured ? 'ok' : undefined}>{g ? (g.configured ? `Gemini enabled (${g.model})` : 'Gemini not configured — built-in explainer') : 'checking…'}</Chip>}>
        <p className="twin-note" style={{ marginTop: 0 }}><ShieldCheck size={13} style={{ verticalAlign: -2 }} /> The backend re-runs the simulation to get the facts. Gemini, when configured, only receives those aggregated facts (never customer rows) and its answer is discarded if it contains any number that is not in them. Without a key everything still works.</p>
        <Field label="Optional question about this scenario"><input className="in" maxLength={300} value={question} onChange={e => setQuestion(e.target.value)} placeholder="e.g. What drives the queue after the failure?" /></Field>
        <div className="toolbar" style={{ marginTop: 10 }}>
          {KINDS.map(x => <button key={x.k} className="btn sm" disabled={busy !== null || (x.k === 'scenarios' ? scenarios.length < 2 : invalid)} onClick={() => ask(x.k)}>{busy === x.k ? <Spinner size={13} /> : <Bot size={13} />}{x.label}</button>)}
        </div>
        {invalid && <div className="err" style={{ marginTop: 6 }}>Fix the scenario errors in the What-if lab first.</div>}
        {scenarios.length < 2 && <p className="twin-note">Scenario differences need at least two scenarios in the Compare tab.</p>}
      </Card>
      {out && (
        <Card title="Explanation" right={<Chip tone={out.source === 'gemini' ? 'vio' : undefined}>{out.source === 'gemini' ? 'Gemini (numbers verified)' : 'Built-in explainer'}</Chip>}>
          <p style={{ marginTop: 0, lineHeight: 1.6 }}>{out.text}</p>
          {out.gemini.rejected_reason && <p className="twin-note" role="status">{out.gemini.rejected_reason} The built-in explanation is shown instead.</p>}
          {out.gemini.error && <p className="twin-note" role="status">Gemini unavailable ({out.gemini.error}). The built-in explanation is shown instead.</p>}
          <details><summary>Facts used</summary><pre className="twin-note" style={{ whiteSpace: 'pre-wrap', maxHeight: 280, overflow: 'auto' }}>{JSON.stringify(out.facts, null, 2)}</pre></details>
        </Card>
      )}
    </div>
  )
}
