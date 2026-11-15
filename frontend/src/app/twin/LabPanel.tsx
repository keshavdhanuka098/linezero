import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Flame, Pause, Play, RotateCcw, SkipForward, Zap } from 'lucide-react'
import type { Preset } from '../../api/twinTypes'
import { Card, Chip, EmptyState, Kpi, Spinner, cx } from '../ui/kit'
import { C, ChartBox, ChartTooltip, axisProps, gridProps } from '../charts/theme'
import { customerTimeline, fmtClock, frameAt, injectChaos, sceneAt, systemTimeline, type ChaosKind, type FormErrors, type TimelineItem, type TwinForm } from '../../lib/twinPlayback'
import FloorView from './FloorView'
import ScenarioForm from './ScenarioForm'
import { METRICS, f1 } from './common'
import { SPEEDS, type Playback as PB } from './usePlayback'
import type { RunView } from './TwinPage'

interface Props {
  form: TwinForm; setForm(f: TwinForm): void; errors: FormErrors; run: RunView | null; busy: boolean
  presets: Preset[]; onPreset(p: Preset): void; onRun(f?: TwinForm, opts?: { resumeAt: number; autoplay: boolean }): void; pb: PB
}

export default function LabPanel({ form, setForm, errors, run, busy, presets, onPreset, onRun, pb }: Props) {
  const [showCustomers, setShowCustomers] = useState(false)
  const [counter, setCounter] = useState(0)
  const [minutes, setMinutes] = useState('10')
  const playback = run?.playback ?? null
  const n = Number(form.num_counters) || 1
  const scene = useMemo(() => (playback ? sceneAt(playback, pb.t) : null), [playback, pb.t])
  const frame = playback ? frameAt(playback.frames, pb.t) : null
  const system = useMemo(() => (playback ? systemTimeline(playback) : []), [playback])
  const customers = useMemo(() => (playback && showCustomers ? customerTimeline(playback) : []), [playback, showCustomers])
  const log = useMemo(() => {
    const all: TimelineItem[] = showCustomers ? [...system, ...customers].sort((a, b) => a.t - b.t) : system
    let hi = all.length
    while (hi > 0 && all[hi - 1].t > pb.t) hi--
    return all.slice(Math.max(0, hi - 80), hi).reverse()
  }, [system, customers, showCustomers, pb.t])
  const series = useMemo(() => (playback ? playback.frames.map(f => ({ t: f.t, queue: f.queue, serving: f.in_service })) : []), [playback])

  const inject = (kind: ChaosKind) => {
    if (!playback) return
    const mins = Number(minutes) > 0 ? Number(minutes) : 10
    const wasPlaying = pb.playing
    pb.pause()
    onRun(injectChaos(form, kind, pb.t, Math.min(counter, n - 1), mins), { resumeAt: pb.t, autoplay: wasPlaying })
  }

  return (
    <div className="twin-split">
      <div style={{ display: 'grid', gap: 14 }}>
        <Card title="Predefined scenarios" sub="Loads the scenario and runs it">
          <div className="toolbar">
            {presets.length === 0 && <span className="twin-note">Loading presets…</span>}
            {presets.map(p => <button key={p.id} className="btn sm" title={`${p.description} ${p.assumptions.join(' ')}`} disabled={busy} onClick={() => onPreset(p)}>{p.name}</button>)}
          </div>
          <p className="twin-note" style={{ marginBottom: 0 }}>Surge, shortage, failure and slow-down sizes are illustrative assumptions, not measured data. Hover a scenario to read them.</p>
        </Card>
        <ScenarioForm form={form} setForm={setForm} errors={errors} />
        <button className="btn p" disabled={busy || Object.keys(errors).length > 0} onClick={() => onRun()}>{busy ? <Spinner /> : <Play size={16} />}Run simulation</button>
        {Object.keys(errors).length > 0 && <div className="err" role="alert">Fix the highlighted fields to run.</div>}
      </div>

      <div style={{ display: 'grid', gap: 14, minWidth: 0 }}>
        {!playback || !scene || !frame ? (
          <Card><EmptyState icon={Zap} title="Run a scenario to see the twin move" text="Pick a predefined scenario or set parameters and press Run simulation. Results come from the backend SimPy engine." /></Card>
        ) : (<>
          <Card title={run?.label ?? 'Simulation'} sub={`seed ${playback.seed_used} · ${run?.replications ?? 1} replication(s) · playback shows the first seed`}
            right={<Chip tone="vio">simulation</Chip>}>
            <div className="pbar" role="group" aria-label="Playback controls">
              {pb.playing
                ? <button className="btn sm" onClick={pb.pause}><Pause size={14} />Pause</button>
                : pb.status === 'paused'
                  ? <button className="btn sm p" onClick={pb.resume}><SkipForward size={14} />Resume</button>
                  : <button className="btn sm p" onClick={pb.play}><Play size={14} />Play</button>}
              <button className="btn sm" onClick={pb.reset}><RotateCcw size={14} />Reset</button>
              <label className="twin-note" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>Speed
                <select className="sel" style={{ height: 30, width: 90 }} value={pb.speed} onChange={e => pb.setSpeed(Number(e.target.value))} aria-label="Playback speed">
                  {SPEEDS.map(s => <option key={s} value={s}>{s}× </option>)}
                </select>
              </label>
              <input type="range" min={0} max={playback.duration} step={0.1} value={pb.t} onChange={e => pb.seek(Number(e.target.value))} aria-label="Simulation time" />
              <b className="mono" style={{ minWidth: 92, textAlign: 'right' }}>{fmtClock(pb.t)} / {fmtClock(playback.duration)}</b>
            </div>
            <div style={{ marginTop: 10 }}>
              <FloorView counters={scene.counters} dots={scene.dots} overflow={scene.overflow} waiting={scene.waiting} label={c => `#${c.servingId}`} transitionMs={pb.playing ? Math.min(250, 900 / pb.speed) : 150} />
            </div>
            <div className="grid g4 kp" style={{ marginTop: 10 }}>
              <Kpi label="Queue length" value={scene.waiting} tone={scene.waiting >= playback.episodes.congestion_threshold ? 'crit' : undefined} sub={`congestion at ≥ ${playback.episodes.congestion_threshold}`} />
              <Kpi label="Longest wait now" value={f1(scene.longestWait, 1)} unit="min" />
              <Kpi label="Arrived · served" value={`${scene.arrivals} · ${scene.served}`} sub={`${scene.abandoned} abandoned`} />
              <Kpi label="Counters serving" value={`${scene.inService} / ${scene.counters.filter(c => c.state !== 'closed' && c.state !== 'failed').length}`} sub={`${scene.counters.filter(c => c.state === 'failed').length} failed · ${scene.counters.filter(c => c.state === 'closed').length} closed`} />
            </div>
          </Card>

          <Card title="Chaos injection" sub="Applies at the current playhead, then the scenario is re-simulated with the same seed" right={<Flame size={16} color={C.warn} />}>
            <div className="toolbar" style={{ alignItems: 'flex-end' }}>
              <label className="fld" style={{ width: 130 }}><span>Counter</span>
                <select className="sel" value={counter} onChange={e => setCounter(Number(e.target.value))}>{Array.from({ length: n }, (_, i) => <option key={i} value={i}>Counter {i + 1}</option>)}</select></label>
              <label className="fld" style={{ width: 100 }}><span>Duration (min)</span><input className="in" inputMode="decimal" value={minutes} onChange={e => setMinutes(e.target.value)} /></label>
              <button className="btn sm d" disabled={busy} onClick={() => inject('failure')}>Fail counter</button>
              <button className="btn sm d" disabled={busy} onClick={() => inject('outage')}>Temporary outage</button>
              <button className="btn sm d" disabled={busy} onClick={() => inject('surge')}>Customer surge ×2</button>
              <button className="btn sm d" disabled={busy} onClick={() => inject('slow')}>Slow service −50%</button>
              <button className="btn sm d" disabled={busy} onClick={() => inject('staff')}>Staff shortage (close counter)</button>
            </div>
            <p className="twin-note" style={{ marginBottom: 0 }}>Because the whole run is re-simulated, customer arrivals before the playhead can differ slightly after a surge (the arrival generator changes), but the seed stays fixed.</p>
          </Card>

          <Card title="Results" sub={`${run?.replications ?? 1} replication(s); ± is the 95% confidence half-width`}>
            <div className="kv">
              {METRICS.map(m => {
                const st = run?.stats?.[m.key]
                const v = run?.summary[m.key]
                return <div key={m.key}><small>{m.label}</small><b>{v === undefined ? '—' : m.fmt(v)}</b>{st?.ci95 != null && <small>± {m.fmt(st.ci95).replace(/ min$/, '')}</small>}</div>
              })}
            </div>
            <div className="tw" style={{ marginTop: 10 }}><table className="tbl"><thead><tr><th>Counter</th><th>Utilization (while open)</th><th>Served</th><th>Closed (min)</th><th>Failed (min)</th></tr></thead><tbody>
              {run?.counters.map(c => <tr key={c.counter_index}><td>{c.name}</td><td className="mono">{f1(c.utilization_available * 100, 0)}%</td><td className="mono">{f1(c.served, 1)}</td><td className="mono">{f1(c.closed_time, 1)}</td><td className="mono">{f1(c.failed_time, 1)}</td></tr>)}
            </tbody></table></div>
          </Card>

          <Card title="Simulation timeline" sub="Click the chart or an event to jump there">
            <ChartBox h={200}><ResponsiveContainer>
              <AreaChart data={series} margin={{ left: -14, right: 6, top: 6 }} onClick={s => { if (s && s.activeLabel !== undefined) pb.seek(Number(s.activeLabel)) }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="t" type="number" domain={[0, playback.duration]} {...axisProps} tickFormatter={v => `${Math.round(v)}m`} />
                <YAxis {...axisProps} allowDecimals={false} />
                <Tooltip content={<ChartTooltip labelFmt={l => `t = ${fmtClock(Number(l))}`} />} />
                {playback.episodes.bottlenecks.map((b, i) => <ReferenceArea key={i} x1={b.start} x2={b.end} fill={C.crit} fillOpacity={0.08} />)}
                {system.filter(s => s.kind === 'counter_failure').map((s, i) => <ReferenceLine key={`f${i}`} x={s.t} stroke={C.crit} strokeDasharray="4 3" />)}
                {system.filter(s => s.kind === 'recovery').map((s, i) => <ReferenceLine key={`r${i}`} x={s.t} stroke={C.teal} strokeDasharray="4 3" />)}
                <Area dataKey="queue" name="Queue length" stroke={C.violet} fill={C.violet} fillOpacity={0.2} dot={false} isAnimationActive={false} />
                <Area dataKey="serving" name="Being served" stroke={C.teal} fill={C.teal} fillOpacity={0.08} dot={false} isAnimationActive={false} />
                <ReferenceLine x={pb.t} stroke={C.amber} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer></ChartBox>
            <div className="toolbar" style={{ margin: '8px 0' }}>
              <span className="chip crit">red band: bottleneck</span><span className="chip crit">red line: failure</span><span className="chip ok">teal line: recovery action</span>
              <label className="chip" style={{ cursor: 'pointer' }}><input type="checkbox" checked={showCustomers} onChange={e => setShowCustomers(e.target.checked)} />Include customer events</label>
            </div>
            <div className="tlog" role="log" aria-label="Simulation events up to the playhead">
              {log.length === 0 && <div style={{ cursor: 'default' }}>No events yet at this point in the run.</div>}
              {log.map((it, i) => <div key={`${it.t}-${i}`} className={it.tone === 'info' ? undefined : it.tone} onClick={() => pb.seek(it.t)}><time>{fmtClock(it.t)}</time><span className={cx(it.tone !== 'info' && it.tone)}>{it.label}</span></div>)}
            </div>
          </Card>
        </>)}
      </div>
    </div>
  )
}
