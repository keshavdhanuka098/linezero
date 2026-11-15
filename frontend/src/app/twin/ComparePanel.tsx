import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { GitCompare, Plus, Trash2 } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import type { CompareResponse, Preset } from '../../api/twinTypes'
import { Card, Chip, EmptyState, Spinner, cx, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps } from '../charts/theme'
import { buildConfig, formFromConfig, nextId, validateForm, type TwinForm } from '../../lib/twinPlayback'
import { ImprovementTable, METRICS, f1, tone } from './common'

export interface SavedScenario { id: number; name: string; form: TwinForm }
const MAX = 5

interface Props { form: TwinForm; presets: Preset[]; scenarios: SavedScenario[]; setScenarios(s: SavedScenario[]): void }

export default function ComparePanel({ form, presets, scenarios, setScenarios }: Props) {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<CompareResponse | null>(null)
  const [name, setName] = useState('')
  const full = scenarios.length >= MAX
  const add = (s: Omit<SavedScenario, 'id'>) => { if (!full) setScenarios([...scenarios, { ...s, id: nextId() }]) }
  const errorsFor = scenarios.map(s => Object.keys(validateForm(s.form)).length)

  const run = async () => {
    setBusy(true)
    try {
      const r = await api<CompareResponse>('/twin/compare', { method: 'POST', body: {
        scenarios: scenarios.map(s => ({ name: s.name, configuration: buildConfig(s.form) })),
        replications: Math.max(1, Math.min(20, Number(form.replications) || 8)), seed: Number(form.seed) } })
      setRes(r)
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }

  const chartData = res ? res.labels.map((l, i) => ({ name: l, avg: res.metrics.avg_waiting_time.values[i], p95: res.metrics.p95_waiting_time.values[i] })) : []

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Card title="Scenarios to compare" sub={`Up to ${MAX}. The first is the baseline. All scenarios run on the same random seeds.`}
        right={<Chip>{scenarios.length} / {MAX}</Chip>}>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <input className="in" style={{ width: 200 }} placeholder="Name for the current builder scenario" value={name} onChange={e => setName(e.target.value)} aria-label="Scenario name" maxLength={60} />
          <button className="btn sm" disabled={full} onClick={() => { add({ name: name.trim() || `Builder scenario ${scenarios.length + 1}`, form: structuredClone(form) }); setName('') }}><Plus size={13} />Add current builder scenario</button>
          <select className="sel" style={{ width: 220 }} disabled={full} value="" aria-label="Add predefined scenario" onChange={e => { const p = presets.find(x => x.id === e.target.value); if (p) add({ name: p.name, form: formFromConfig(p.configuration, { seed: form.seed, replications: form.replications }) }) }}>
            <option value="">Add predefined scenario…</option>{presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        {scenarios.length === 0 ? <EmptyState icon={GitCompare} title="No scenarios yet" text="Add the current builder scenario or a predefined one. Include a 'Normal operations' scenario first to use it as the baseline." /> : (
          <div className="tw"><table className="tbl"><thead><tr><th>#</th><th>Name</th><th>Counters</th><th>Arrivals/min</th><th>Chaos</th><th /></tr></thead><tbody>
            {scenarios.map((s, i) => (
              <tr key={s.id}>
                <td>{i === 0 ? <Chip tone="vio">baseline</Chip> : i + 1}</td>
                <td><input className="in" style={{ height: 30 }} value={s.name} maxLength={60} aria-label={`Name of scenario ${i + 1}`} onChange={e => setScenarios(scenarios.map(x => (x.id === s.id ? { ...x, name: e.target.value } : x)))} /></td>
                <td className="mono">{s.form.num_counters}</td><td className="mono">{s.form.arrival_rate}</td>
                <td className="twin-note">{[s.form.outages.length && `${s.form.outages.length} failure`, s.form.surges.length && `${s.form.surges.length} surge`, s.form.slowdowns.length && 'slow', s.form.staff && `${s.form.staff} staff`].filter(Boolean).join(', ') || 'none'}{errorsFor[i] > 0 && <span className="err"> · invalid</span>}</td>
                <td><button className="btn sm g ic" aria-label={`Remove ${s.name}`} onClick={() => setScenarios(scenarios.filter(x => x.id !== s.id))}><Trash2 size={14} /></button></td>
              </tr>
            ))}
          </tbody></table></div>
        )}
        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="btn p" disabled={busy || scenarios.length < 2 || errorsFor.some(Boolean) || scenarios.some(s => !s.name.trim())} onClick={run}>{busy ? <Spinner /> : <GitCompare size={16} />}Compare {scenarios.length || ''} scenarios</button>
          {scenarios.length < 2 && <span className="twin-note">Add at least two scenarios.</span>}
        </div>
      </Card>

      {res && (<>
        <Card title="Comparison" sub={`${res.replications} replications per scenario · baseline: ${res.labels[0]}`}>
          <div className="tw"><table className="tbl">
            <thead><tr><th>Metric</th>{res.labels.map((l, i) => <th key={l + i}>{l}</th>)}</tr></thead>
            <tbody>
              {METRICS.map(m => {
                const b = res.metrics[m.key]
                return (
                  <tr key={m.key}>
                    <td>{m.label}</td>
                    {b.values.map((v, i) => (
                      <td key={i} className="mono">
                        <span style={{ fontWeight: b.best_index === i ? 700 : 400 }}>{m.fmt(v)}</span>
                        {b.ci95[i] != null && <small className="twin-note"> ±{f1(m.key === 'avg_utilization_available' ? (b.ci95[i] as number) * 100 : (b.ci95[i] as number), m.key === 'avg_utilization_available' ? 0 : 2)}</small>}
                        {i > 0 && <div className={cx('twin-note', tone(b.better, b.delta[i]))}>{b.delta[i] > 0 ? '+' : ''}{f1(b.delta[i], 2)}{b.pct[i] !== null ? ` (${(b.pct[i] as number) > 0 ? '+' : ''}${f1(b.pct[i], 0)}%)` : ''}{b.paired[i] && !b.paired[i]!.significant ? ' · noise' : ''}</div>}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table></div>
          <p className="twin-note">Bold = best of the compared scenarios. Differences are paired across replications; "noise" means the 95% interval includes zero. {res.method}</p>
        </Card>
        <Card title="Wait times by scenario" sub="Mean across replications (minutes)">
          <ChartBox h={240}><ResponsiveContainer>
            <BarChart data={chartData} margin={{ left: -14, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} interval={0} tick={{ fill: C.axis, fontSize: 10 }} /><YAxis {...axisProps} />
              <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={v => `${f1(v)} min`} />} />
              <Bar dataKey="avg" name="Average wait" fill={C.violet} radius={[4, 4, 0, 0]} maxBarSize={36} />
              <Bar dataKey="p95" name="P95 wait" fill={C.warn} radius={[4, 4, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer></ChartBox>
          <Legend items={[{ label: 'Average wait', color: C.violet }, { label: 'P95 wait', color: C.warn }]} />
        </Card>
        {res.improvements.map(im => (
          <Card key={im.scenario} title={`Before and after: ${im.vs} → ${im.scenario}`} sub="Measured from simulation runs on the same seeds">
            <ImprovementTable imp={im.metrics} before={im.vs} after={im.scenario} />
          </Card>
        ))}
      </>)}
    </div>
  )
}
