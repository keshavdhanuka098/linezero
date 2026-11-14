import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cpu, Server } from 'lucide-react'
import { api, errMsg } from '../../api/client'
import { useServer, useServerMode } from '../../api/serverStore'
import type { CounterAgg, LiveResponse, Playback, Preset, SimulateResponse, Stat, Summary } from '../../api/twinTypes'
import { Card, EmptyState, PageHeader, Seg, toast } from '../ui/kit'
import { DEFAULT_FORM, buildConfig, formFromConfig, validateForm, type TwinForm } from '../../lib/twinPlayback'
import '../../styles/twin.css'
import ComparePanel, { type SavedScenario } from './ComparePanel'
import ExplainPanel from './ExplainPanel'
import HealPanel from './HealPanel'
import LabPanel from './LabPanel'
import LivePanel from './LivePanel'
import { usePlayback } from './usePlayback'

export interface RunView { label: string; playback: Playback; summary: Summary; stats?: Record<string, Stat>; counters: CounterAgg[]; replications: number }
type Tab = 'live' | 'lab' | 'heal' | 'compare' | 'explain'
const SAVED_KEY = 'lz.twin.scenarios'

function loadSaved(): SavedScenario[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SAVED_KEY) ?? '[]') as SavedScenario[]
    return Array.isArray(raw) ? raw.filter(s => s && typeof s.name === 'string' && s.form).slice(0, 5) : []
  } catch { return [] }
}

function NeedsBackend() {
  const status = useServer(s => s.status), setMode = useServer(s => s.setMode)
  return (
    <div className="page">
      <PageHeader title="Digital Twin" sub="Predict. Simulate. Optimize. Recover." demo={false} />
      <Card>
        <EmptyState icon={Server} title="The Digital Twin needs the LineZero backend"
          text="Its simulation, forecasting and recovery engines (SimPy, scikit-learn) run on the API, so it is not available in browser-only demo mode. Start the backend with ./scripts/start-backend.sh, then switch to the server data source."
          action={status === 'online' ? <button className="btn p" onClick={() => setMode('server')}>Use server data</button> : <Link className="btn" to="/app/settings">Open settings</Link>} />
      </Card>
    </div>
  )
}

export default function TwinPage() {
  const online = useServerMode()
  const [tab, setTab] = useState<Tab>('live')
  const [form, setForm] = useState<TwinForm>(DEFAULT_FORM)
  const [run, setRun] = useState<RunView | null>(null)
  const [busy, setBusy] = useState(false)
  const [presets, setPresets] = useState<Preset[]>([])
  const [scenarios, setScenarios] = useState<SavedScenario[]>(loadSaved)
  const pb = usePlayback(run?.playback.duration ?? 0)
  const errors = useMemo(() => validateForm(form), [form])

  useEffect(() => { try { localStorage.setItem(SAVED_KEY, JSON.stringify(scenarios)) } catch { /* storage unavailable */ } }, [scenarios])
  useEffect(() => {
    if (!online) return
    const p = { arrival_rate: Number(form.arrival_rate) || 1.2, mean_service_time: Number(form.mean_service_time) || 4, num_counters: Math.max(1, Math.min(40, Math.floor(Number(form.num_counters)) || 5)), duration: Number(form.duration) || 120 }
    let live = true
    api<Preset[]>('/twin/presets', { params: p }).then(d => { if (live) setPresets(d) }).catch(() => { if (live) setPresets([]) })
    return () => { live = false }
    // presets depend on the base parameters only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, form.arrival_rate, form.mean_service_time, form.num_counters, form.duration])

  const showRun = useCallback((r: RunView) => { setRun(r); pb.reset() }, [pb])

  const execRun = useCallback(async (f: TwinForm = form, opts?: { resumeAt: number; autoplay: boolean }) => {
    const errs = validateForm(f)
    if (Object.keys(errs).length) { toast('Fix the highlighted fields first', true); return }
    setBusy(true)
    try {
      const reps = Number(f.replications)
      const r = await api<SimulateResponse>('/twin/simulate', { method: 'POST', body: { configuration: buildConfig(f), replications: reps, seed: Number(f.seed) } })
      setForm(f)
      setRun({ label: 'What-if simulation', playback: r.playback, summary: r.summary, stats: r.stats, counters: r.counters, replications: r.replications })
      if (opts) { pb.seek(opts.resumeAt); if (opts.autoplay) pb.play() } else { pb.reset(); pb.play() }
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }, [form, pb])

  const loadPreset = (p: Preset) => { const f = formFromConfig(p.configuration, { seed: form.seed, replications: form.replications }); setForm(f); void execRun(f) }
  const useLiveAsBase = (live: LiveResponse) => {
    const s = live.suggested_configuration
    if (!s) return
    const { arrival_rate_is_estimated_from_data: _est, ...cfg } = s
    void _est
    setForm(formFromConfig(cfg as typeof s, { seed: form.seed, replications: form.replications }))
    setTab('lab')
    toast(`Builder loaded from “${live.queue.name}”${s.arrival_rate_is_estimated_from_data ? '' : ' (no recent arrivals: default rate used)'}`)
  }

  if (!online) return <NeedsBackend />
  return (
    <div className="page">
      <PageHeader title="Digital Twin" sub="Predict. Simulate. Optimize. Recover. — a simulation twin of your queue: real state in, SimPy projections out. It never changes real queues." demo={false}>
        <Cpu size={18} color="var(--teal)" aria-hidden />
      </PageHeader>
      <div className="twin-tabs">
        <Seg<Tab> value={tab} onChange={setTab} label="Digital Twin sections" options={[
          { v: 'live', l: 'Live twin & forecast' }, { v: 'lab', l: 'What-if & chaos' }, { v: 'heal', l: 'Self-healing' }, { v: 'compare', l: 'Compare' }, { v: 'explain', l: 'Explain' }]} />
      </div>
      {tab === 'live' && <LivePanel onUseAsBase={useLiveAsBase} />}
      {tab === 'lab' && <LabPanel form={form} setForm={setForm} errors={errors} run={run} busy={busy} presets={presets} onPreset={loadPreset} onRun={execRun} pb={pb} />}
      {tab === 'heal' && <HealPanel form={form} setForm={setForm} errors={errors} onShowRun={showRun} onOpenLab={() => setTab('lab')} onRunForm={f => void execRun(f)} />}
      {tab === 'compare' && <ComparePanel form={form} presets={presets} scenarios={scenarios} setScenarios={setScenarios} />}
      {tab === 'explain' && <ExplainPanel form={form} errors={errors} scenarios={scenarios} />}
    </div>
  )
}
