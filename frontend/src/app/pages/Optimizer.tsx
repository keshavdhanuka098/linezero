import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Minus, Plus, RotateCcw, Save, Sparkles, SlidersHorizontal } from 'lucide-react'
import { useStore } from '../../store/store'
import { buildInputs, compositionCount, minServersFor, searchBest, summarize } from '../../lib/optimizer'
import { demandProfile, demoHour, fmtMin, pct } from '../../lib/metrics'
import { numberIn } from '../../lib/validate'
import { Card, Chip, DemoBadge, EmptyState, Field, Kpi, PageHeader, Seg, cx, toast } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'
import ServerOptimizer from '../server/ServerOptimizer'
import { useServerMode } from '../../api/serverStore'

type Scn = 'avg' | 'now' | 'peak'
const CAP_WAIT = 45

function OptimizerLocal() {
  const queues = useStore(s => s.queues), counters = useStore(s => s.counters), clock = useStore(s => s.clock), sla = useStore(s => s.settings.thresholds.waitSla), addReport = useStore(s => s.addReport)
  const animate = useAnimate()
  const [scn, setScn] = useState<Scn>('peak')
  const [extra, setExtra] = useState('0')
  const peak = useMemo(() => Math.max(...Array.from({ length: 10 }, (_, h) => demandProfile(8 + h))), [])
  const factor = scn === 'avg' ? 1 : scn === 'now' ? demandProfile(demoHour(clock)) : peak
  const inputs = useMemo(() => buildInputs(queues, counters, factor), [queues, counters, factor])
  const extraErr = numberIn(extra, 0, 12, 'Additional counters', true)
  const total = inputs.reduce((a, i) => a + i.current, 0) + (extraErr ? 0 : Number(extra))
  const current = inputs.map(i => i.current)
  const best = useMemo(() => (extraErr ? null : searchBest(inputs, total)), [inputs, total, extraErr])
  const [proposed, setProposed] = useState<number[] | null>(null)
  const [searched, setSearched] = useState(true)
  const key = inputs.map(i => i.id).join(',') + '|' + scn + '|' + total
  useEffect(() => { setProposed(null); setSearched(true) }, [key])
  const alloc = proposed ?? best?.alloc ?? current
  const used = alloc.reduce((a, b) => a + b, 0)
  const before = useMemo(() => summarize(inputs, current), [inputs])
  const after = useMemo(() => summarize(inputs, alloc), [inputs, alloc])
  const space = compositionCount(total, inputs.length)
  const isBest = best && alloc.every((v, k) => v === best.alloc[k])
  const improve = Number.isFinite(before.avgWait) && Number.isFinite(after.avgWait) && before.avgWait > 0 ? (before.avgWait - after.avgWait) / before.avgWait : null

  const step = (k: number, d: number) => { const n = alloc.slice(); n[k] = Math.max(1, n[k] + d); setProposed(n); setSearched(false) }
  const chart = inputs.map((i, k) => ({ name: i.name.length > 16 ? i.name.slice(0, 15) + '…' : i.name, full: i.name, Current: Math.min(CAP_WAIT, before.res[k].wq), Proposed: Math.min(CAP_WAIT, after.res[k].wq), cu: !before.res[k].stable, pu: !after.res[k].stable }))
  const show = (v: number) => (Number.isFinite(v) ? fmtMin(v) : 'Unstable')

  const save = () => addReport({ type: 'optimization', title: `Allocation comparison · ${scn === 'peak' ? 'peak' : scn === 'now' ? 'current-hour' : 'average'} demand`, status: 'Completed', synthetic: true,
    summary: { 'Total counters': used, 'Demand scenario': scn, 'Predicted wait before (min)': Number.isFinite(before.avgWait) ? +before.avgWait.toFixed(2) : 'unstable', 'Predicted wait after (min)': Number.isFinite(after.avgWait) ? +after.avgWait.toFixed(2) : 'unstable', Method: isBest && best?.exhaustive ? `Exhaustive search of ${best.evaluated} allocations (Allen–Cunneen model)` : 'Manual / non-verified allocation', Assumptions: 'Arrival CV 1.0, service CV 0.6, identical servers per queue' },
    rows: inputs.map((i, k) => ({ Queue: i.name, 'Servers before': current[k], 'Servers after': alloc[k], 'Util before': pct(before.res[k].util), 'Util after': pct(after.res[k].util), 'Wait before (min)': Number.isFinite(before.res[k].wq) ? +before.res[k].wq.toFixed(2) : 'unstable', 'Wait after (min)': Number.isFinite(after.res[k].wq) ? +after.res[k].wq.toFixed(2) : 'unstable' })) }) && toast('Comparison saved to Reports')

  return (
    <div className="page">
      <PageHeader title="Resource Optimizer" sub="Compare how the current counter allocation performs against a proposed one under a queueing-theory model.">
        <button className="btn" onClick={() => { setProposed(null); setSearched(true) }} disabled={proposed === null}><RotateCcw size={16} />Reset to suggested</button>
        <button className="btn t" onClick={save} disabled={!queues.length}><Save size={16} />Save comparison</button>
      </PageHeader>
      {!queues.length ? <Card><EmptyState icon={SlidersHorizontal} title="No queues to optimize" text="Create queues and counters first." action={<Link className="btn p" to="/app/monitor">Open Live Monitor</Link>} /></Card> : (<>
        <div className="banner"><Sparkles size={16} style={{ flex: 'none', marginTop: 2 }} /><span><b>How to read this.</b> Predictions use an Allen–Cunneen G/G/c approximation (arrival CV 1.0, service CV 0.6) on demo arrival rates. {best?.exhaustive ? <>The suggested split is the lowest predicted total wait among all <b>{best.evaluated.toLocaleString()}</b> ways to share {total} counters (exhaustive search), so it is optimal <u>within this model only</u> — not a guarantee for real operations.</> : <>The suggested split comes from a greedy heuristic and is <b>not verified optimal</b>.</>}</span></div>

        <Card>
          <div className="toolbar" style={{ alignItems: 'flex-end', gap: 18 }}>
            <Field label="Demand scenario"><Seg<Scn> value={scn} onChange={setScn} label="Demand scenario" options={[{ v: 'now', l: 'Current hour' }, { v: 'avg', l: 'Daily average' }, { v: 'peak', l: 'Peak hour' }]} /></Field>
            <Field label="Additional counters available" error={extraErr} hint="Added to the current pool"><input className={cx('in', extraErr && 'bad')} style={{ width: 120 }} inputMode="numeric" value={extra} onChange={e => setExtra(e.target.value)} /></Field>
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>Demand factor ×{factor.toFixed(2)} · pool {total} counters · {space.toLocaleString()} possible allocations</div>
          </div>
        </Card>

        <div className="grid g4 kp">
          <Kpi label="Predicted wait (current → proposed)" value={<>{show(before.avgWait)} <small>→</small> {show(after.avgWait)}</>} tone={after.stable ? undefined : 'crit'} sub={`target ${sla}m`} />
          <Kpi label="Estimated improvement" value={improve === null ? (after.stable && !before.stable ? 'Stabilises' : '—') : `${improve >= 0 ? '' : '+'}${Math.abs(improve * 100).toFixed(0)}%`} tone={improve !== null && improve < 0 ? 'hot' : undefined} sub={improve === null ? 'before-state unstable or unchanged' : improve >= 0 ? 'lower weighted wait' : 'higher weighted wait'} />
          <Kpi label="Expected queue length" value={<>{Number.isFinite(before.lq) ? before.lq.toFixed(1) : '∞'} <small>→</small> {Number.isFinite(after.lq) ? after.lq.toFixed(1) : '∞'}</>} sub="people waiting, all queues" />
          <Kpi label="Utilization (current → proposed)" value={<>{pct(before.util)} <small>→</small> {pct(after.util)}</>} sub="capacity-weighted" />
        </div>

        <div className="grid g21">
          <Card title="Before-and-after comparison" sub="Set the proposed number of counters per queue (parallel servers)" right={<div className="toolbar">{isBest && searched ? <Chip tone="ok">Suggested · lowest predicted wait in model</Chip> : <Chip tone="warn">Manual allocation</Chip>}<DemoBadge label="MODEL" /></div>}>
            <div className="tw"><table className="tbl"><thead><tr><th>Queue</th><th>Counters</th><th>Utilization</th><th>Predicted wait</th><th>Exp. queue length</th><th>Need for target</th></tr></thead><tbody>
              {inputs.map((i, k) => {
                const b = before.res[k], a = after.res[k], need = minServersFor(i, sla)
                return (<tr key={i.id}>
                  <td><b style={{ fontWeight: 500 }}>{i.name}</b><div className="hint">λ {i.lambda.toFixed(2)}/min · service {fmtMin(i.svc)}</div></td>
                  <td><div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="mono" style={{ color: 'var(--muted)' }}>{current[k]}</span>→
                    <button className="btn sm ic" aria-label={`Fewer counters for ${i.name}`} onClick={() => step(k, -1)} disabled={alloc[k] <= 1}><Minus size={13} /></button><b className="mono" style={{ minWidth: 18, textAlign: 'center' }}>{alloc[k]}</b><button className="btn sm ic" aria-label={`More counters for ${i.name}`} onClick={() => step(k, 1)}><Plus size={13} /></button></div></td>
                  <td className="mono">{pct(b.util)} → <b style={{ color: a.util >= 0.9 ? 'var(--warn)' : undefined }}>{pct(a.util)}</b></td>
                  <td className="mono">{show(b.wq)} → <b style={{ color: !a.stable || a.wq > sla ? 'var(--warn)' : 'var(--teal)' }}>{show(a.wq)}</b></td>
                  <td className="mono">{Number.isFinite(b.lq) ? b.lq.toFixed(1) : '∞'} → <b>{Number.isFinite(a.lq) ? a.lq.toFixed(1) : '∞'}</b></td>
                  <td>{need === null ? <Chip tone="crit">&gt; 40</Chip> : <Chip tone={alloc[k] >= need ? 'ok' : 'hot'}>{need} counters</Chip>}</td>
                </tr>)
              })}
            </tbody></table></div>
            <div className="toolbar" style={{ marginTop: 12, justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>Resource requirement: <b className="mono" style={{ color: 'var(--text)' }}>{used}</b> counters {used === total ? '(uses full pool)' : used > total ? <b style={{ color: 'var(--warn)' }}>(exceeds pool by {used - total})</b> : `(${total - used} unallocated)`} · currently {before.servers}</span>
              {best && <button className="btn t" onClick={() => { setProposed(best.alloc); setSearched(true) }}><Sparkles size={15} />Use suggested split</button>}
            </div>
          </Card>
          <Card title="Predicted wait by queue" sub={`Minutes · unstable queues capped at ${CAP_WAIT}`} right={<DemoBadge label="MODEL" />}>
            <ChartBox h={260}><ResponsiveContainer><BarChart data={chart} margin={{ left: -14, right: 6, top: 6 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} interval={0} /><YAxis {...axisProps} unit="m" />
              <Tooltip cursor={{ fill: 'rgba(107,101,255,.08)' }} content={<ChartTooltip fmt={(v, n) => ((n === 'Current' ? chart.some(c => c.cu && c.Current === v) : chart.some(c => c.pu && c.Proposed === v)) && v >= CAP_WAIT ? 'Unstable' : `${v.toFixed(1)} min`)} labelFmt={l => chart.find(c => c.name === l)?.full ?? String(l)} />} />
              <Bar dataKey="Current" fill={C.violet} radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={animate}>{chart.map((c, i) => <Cell key={i} fill={c.cu ? C.crit : C.violet} />)}</Bar>
              <Bar dataKey="Proposed" fill={C.teal} radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={animate}>{chart.map((c, i) => <Cell key={i} fill={c.pu ? C.crit : C.teal} />)}</Bar>
            </BarChart></ResponsiveContainer></ChartBox>
            <Legend items={[{ label: 'Current', color: C.violet }, { label: 'Proposed', color: C.teal }, { label: 'Unstable (demand > capacity)', color: C.crit }]} />
          </Card>
        </div>
      </>)}
    </div>
  )
}

export default function Optimizer() {
  return useServerMode() ? <ServerOptimizer /> : <OptimizerLocal />
}
