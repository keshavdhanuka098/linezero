import type { Bottleneck, CounterState, Playback, TwinAction, TwinConfigJson, TwinCustomer, TwinEvent, TwinFrame } from '../api/twinTypes'

/* ---------------------------------------------------------------- scenario form */
export interface OutageRow { id: number; counter: number; start: string; end: string } // end '' = until the end
export interface SlowRow { id: number; counter: number | 'all'; start: string; end: string; factor: string }
export interface SurgeRow { id: number; start: string; end: string; multiplier: string }
export interface ActionRow { id: number; type: TwinAction['type']; at: string; counter: number; factor: string }
export interface TwinForm {
  arrival_rate: string; mean_service_time: string; num_counters: string; duration: string; seed: string; replications: string
  staff: string // '' = every counter staffed
  speed_pct: string // global counter speed, 100 = nominal
  abandon: boolean; patience: string
  assignment: 'longest_idle' | 'lowest_index'
  standby: number[]
  outages: OutageRow[]; slowdowns: SlowRow[]; surges: SurgeRow[]; actions: ActionRow[]
  recovery: { enabled: boolean; threshold: string; activations: string; boost: string }
  speedFactors?: number[] // per-counter nominal speeds when derived from live data
}

let uid = 1
export const nextId = () => uid++

export const DEFAULT_FORM: TwinForm = {
  arrival_rate: '1.2', mean_service_time: '4', num_counters: '5', duration: '120', seed: '2026', replications: '5',
  staff: '', speed_pct: '100', abandon: false, patience: '10', assignment: 'longest_idle', standby: [],
  outages: [], slowdowns: [], surges: [], actions: [],
  recovery: { enabled: false, threshold: '8', activations: '2', boost: '1' },
}

export type FormErrors = Record<string, string>

const num = (v: string) => (v.trim() === '' ? NaN : Number(v))
function inRange(errs: FormErrors, key: string, v: string, min: number, max: number, label: string, int = false) {
  const n = num(v)
  if (!Number.isFinite(n)) errs[key] = `${label} must be a number`
  else if (int && !Number.isInteger(n)) errs[key] = `${label} must be a whole number`
  else if (n < min || n > max) errs[key] = `${label} must be between ${min} and ${max}`
}

export function validateForm(f: TwinForm): FormErrors {
  const e: FormErrors = {}
  inRange(e, 'arrival_rate', f.arrival_rate, 0.01, 100, 'Arrival rate')
  inRange(e, 'mean_service_time', f.mean_service_time, 0.1, 240, 'Service duration')
  inRange(e, 'num_counters', f.num_counters, 1, 40, 'Counters', true)
  inRange(e, 'duration', f.duration, 5, 480, 'Simulation duration')
  inRange(e, 'seed', f.seed, 0, 1_000_000_000, 'Seed', true)
  inRange(e, 'replications', f.replications, 1, 20, 'Replications', true)
  inRange(e, 'speed_pct', f.speed_pct, 10, 200, 'Counter speed')
  if (f.abandon) inRange(e, 'patience', f.patience, 0.1, 1000, 'Patience')
  const n = num(f.num_counters), d = num(f.duration)
  if (Number.isFinite(n) && f.staff.trim() !== '') inRange(e, 'staff', f.staff, 0, n, 'Staff available', true)
  if (Number.isFinite(n) && f.standby.some(i => i >= n)) e.standby = 'A standby counter is outside the counter range'
  const expected = num(f.arrival_rate) * d * Math.max(1, ...f.surges.map(s => num(s.multiplier) || 1))
  if (Number.isFinite(expected) && expected > 7500) e.arrival_rate = 'Too many customers for the twin (limit ~8,000 per run); lower the rate or duration'
  const win = (key: string, s: string, en: string, endOptional: boolean) => {
    const a = num(s), b = en.trim() === '' ? (endOptional ? Infinity : NaN) : num(en)
    if (!Number.isFinite(a) || a < 0) e[key] = 'Start must be 0 or more'
    else if (Number.isNaN(b)) e[key] = 'End is required'
    else if (b <= a) e[key] = 'End must be after start'
    else if (Number.isFinite(d) && a >= d) e[key] = 'Start is after the end of the run'
  }
  f.outages.forEach(o => { win(`outage${o.id}`, o.start, o.end, true); if (Number.isFinite(n) && o.counter >= n) e[`outage${o.id}`] = 'Counter does not exist' })
  f.slowdowns.forEach(s => { win(`slow${s.id}`, s.start, s.end, true); const x = num(s.factor); if (!(x > 0 && x <= 5)) e[`slow${s.id}`] = 'Speed factor must be above 0 and at most 5'; if (s.counter !== 'all' && Number.isFinite(n) && s.counter >= n) e[`slow${s.id}`] = 'Counter does not exist' })
  f.surges.forEach(s => { win(`surge${s.id}`, s.start, s.end, false); const x = num(s.multiplier); if (!(x >= 0 && x <= 20)) e[`surge${s.id}`] = 'Multiplier must be between 0 and 20' })
  const sorted = [...f.surges].filter(s => Number.isFinite(num(s.start)) && Number.isFinite(num(s.end))).sort((a, b) => num(a.start) - num(b.start))
  for (let i = 1; i < sorted.length; i++) if (num(sorted[i].start) < num(sorted[i - 1].end)) e[`surge${sorted[i].id}`] = 'Surges must not overlap'
  f.actions.forEach(a => {
    const at = num(a.at)
    if (!Number.isFinite(at) || at < 0) e[`action${a.id}`] = 'Time must be 0 or more'
    else if (a.type === 'boost_speed' && !(num(a.factor) > 1 && num(a.factor) <= 3)) e[`action${a.id}`] = 'Boost factor must be above 1 and at most 3'
    else if (a.type !== 'boost_speed' && Number.isFinite(n) && a.counter >= n) e[`action${a.id}`] = 'Counter does not exist'
  })
  if (f.recovery.enabled) {
    inRange(e, 'rec_threshold', f.recovery.threshold, 1, 1000, 'Queue threshold', true)
    inRange(e, 'rec_activations', f.recovery.activations, 0, 40, 'Max activations', true)
    inRange(e, 'rec_boost', f.recovery.boost, 1, 3, 'Boost factor')
  }
  return e
}

/** Translate the form into the API's TwinConfig. Call only when `validateForm` returned no errors. */
export function buildConfig(f: TwinForm, seed?: number): TwinConfigJson {
  const n = Number(f.num_counters)
  const pct = Number(f.speed_pct) / 100
  const base = f.speedFactors && f.speedFactors.length === n ? f.speedFactors : Array(n).fill(1)
  const factors = base.map(x => x * pct)
  const cfg: TwinConfigJson = {
    arrival_rate: Number(f.arrival_rate), mean_service_time: Number(f.mean_service_time), num_counters: n,
    duration: Number(f.duration), seed: seed ?? Number(f.seed), counter_assignment: f.assignment,
    abandonment_enabled: f.abandon, mean_patience: f.abandon ? Number(f.patience) : null,
  }
  if (factors.some(x => Math.abs(x - 1) > 1e-9)) cfg.counter_speed_factors = factors
  if (f.staff.trim() !== '' && Number(f.staff) < n) cfg.staff_available = Number(f.staff)
  if (f.standby.length) cfg.standby_counters = [...f.standby].sort((a, b) => a - b)
  if (f.surges.length) cfg.arrival_profile = [...f.surges].sort((a, b) => Number(a.start) - Number(b.start)).map(s => ({ start: Number(s.start), end: Number(s.end), multiplier: Number(s.multiplier) }))
  if (f.outages.length) cfg.outages = f.outages.map(o => ({ counter: o.counter, start: Number(o.start), end: o.end.trim() === '' ? null : Number(o.end), kind: 'failure' }))
  if (f.slowdowns.length) cfg.speed_changes = f.slowdowns.map(s => ({ counter: s.counter === 'all' ? null : s.counter, start: Number(s.start), end: s.end.trim() === '' ? null : Number(s.end), factor: Number(s.factor) }))
  if (f.actions.length) cfg.actions = f.actions.map(a => ({ type: a.type, at: Number(a.at), counter: a.type === 'boost_speed' ? null : a.counter, factor: a.type === 'boost_speed' ? Number(a.factor) : null }))
  if (f.recovery.enabled) cfg.recovery = { enabled: true, queue_threshold: Number(f.recovery.threshold), sustain: 2, check_interval: 1, cooldown: 2, max_activations: Number(f.recovery.activations), boost_factor: Number(f.recovery.boost) }
  return cfg
}

const s2 = (x: unknown) => (x === null || x === undefined ? '' : String(x))
/** Inverse of buildConfig for configs that come from presets, live data or recommendations. */
export function formFromConfig(c: TwinConfigJson, keep?: Partial<TwinForm>): TwinForm {
  const n = Number(c.num_counters)
  const factors = (c.counter_speed_factors as number[] | undefined) ?? undefined
  const uniform = factors && factors.every(x => Math.abs(x - factors[0]) < 1e-9)
  const f: TwinForm = {
    ...DEFAULT_FORM, ...keep,
    arrival_rate: s2(round(Number(c.arrival_rate), 4)), mean_service_time: s2(round(Number(c.mean_service_time), 4)),
    num_counters: s2(n), duration: s2(c.duration),
    staff: c.staff_available === undefined || c.staff_available === null ? '' : s2(c.staff_available),
    speed_pct: uniform ? s2(round(factors[0] * 100, 2)) : '100',
    speedFactors: factors && !uniform ? factors : undefined,
    abandon: Boolean(c.abandonment_enabled), patience: s2(c.mean_patience ?? 10),
    assignment: (c.counter_assignment as TwinForm['assignment']) ?? 'longest_idle',
    standby: [...((c.standby_counters as number[] | undefined) ?? [])],
    surges: ((c.arrival_profile as { start: number; end: number; multiplier: number }[] | undefined) ?? []).map(s => ({ id: nextId(), start: s2(s.start), end: s2(s.end), multiplier: s2(s.multiplier) })),
    outages: ((c.outages as { counter: number; start: number; end: number | null }[] | undefined) ?? []).map(o => ({ id: nextId(), counter: o.counter, start: s2(o.start), end: s2(o.end) })),
    slowdowns: ((c.speed_changes as { counter: number | null; start: number; end: number | null; factor: number }[] | undefined) ?? []).map(s => ({ id: nextId(), counter: s.counter ?? 'all', start: s2(s.start), end: s2(s.end), factor: s2(s.factor) })),
    actions: ((c.actions as TwinAction[] | undefined) ?? []).map(a => ({ id: nextId(), type: a.type, at: s2(a.at), counter: a.counter ?? 0, factor: s2(a.factor ?? 1.15) })),
  }
  return f
}
const round = (x: number, d: number) => Math.round(x * 10 ** d) / 10 ** d

/** Add a chaos event starting at time `t` (used for injection while the simulation is playing). */
export type ChaosKind = 'failure' | 'outage' | 'surge' | 'slow' | 'staff'
export function injectChaos(f: TwinForm, kind: ChaosKind, t: number, counter: number, minutes = 10): TwinForm {
  const start = String(round(t, 2)), id = nextId()
  const dur = Number(f.duration)
  switch (kind) {
    case 'failure': return { ...f, outages: [...f.outages, { id, counter, start, end: '' }] }
    case 'outage': return { ...f, outages: [...f.outages, { id, counter, start, end: String(round(Math.min(t + minutes, dur), 2)) }] }
    case 'surge': return { ...f, surges: [...f.surges, { id, start, end: String(round(Math.min(t + Math.max(minutes, 5), dur), 2)), multiplier: '2' }] }
    case 'slow': return { ...f, slowdowns: [...f.slowdowns, { id, counter: 'all', start, end: String(round(Math.min(t + Math.max(minutes, 5), dur), 2)), factor: '0.5' }] }
    case 'staff': return { ...f, actions: [...f.actions, { id, type: 'deactivate_counter', at: start, counter, factor: '1.15' }] }
  }
}

/* ------------------------------------------------------------------ playback */
export function frameAt(frames: TwinFrame[], t: number): TwinFrame {
  let lo = 0, hi = frames.length - 1
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (frames[mid].t <= t) lo = mid; else hi = mid - 1 }
  return frames[lo]
}

export type CounterView = 'idle' | 'busy' | 'failed' | 'closed'
export interface Dot { id: number; slot: number }
export interface SceneCounter { index: number; name: string; state: CounterView; servingId: number | null }
export interface Scene { dots: Dot[]; overflow: number; waiting: number; counters: SceneCounter[]; arrivals: number; served: number; abandoned: number; inService: number; longestWait: number }
const NAMES: CounterView[] = ['idle', 'busy', 'failed', 'closed']

export function sceneAt(pb: Pick<Playback, 'customers' | 'frames' | 'num_counters'>, t: number, maxDots = 36): Scene {
  const waiting: number[] = []
  const serving = new Map<number, number>()
  let served = 0, abandoned = 0, arrivals = 0
  for (const [id, arr, start, end, counter, ab] of pb.customers as TwinCustomer[]) {
    if (arr > t) break
    arrivals++
    if (ab !== null && ab <= t) { abandoned++; continue }
    if (start !== null && start <= t) {
      if (end !== null && end <= t) served++
      else if (counter !== null) serving.set(counter, id)
      continue
    }
    waiting.push(id)
  }
  const fr = frameAt(pb.frames, t)
  const counters: SceneCounter[] = []
  for (let i = 0; i < pb.num_counters; i++) {
    const sid = serving.get(i) ?? null
    const code = (fr.counters[i] ?? 0) as CounterState
    counters.push({ index: i, name: `Counter ${i + 1}`, servingId: sid, state: sid !== null ? 'busy' : code === 1 ? 'idle' : NAMES[code] })
  }
  return {
    dots: waiting.slice(0, maxDots).map((id, slot) => ({ id, slot })), overflow: Math.max(0, waiting.length - maxDots), waiting: waiting.length,
    counters, arrivals, served, abandoned, inService: serving.size, longestWait: fr.longest_wait,
  }
}

/* ------------------------------------------------------------------ timeline */
export type TimelineKind = 'arrival' | 'queue_formation' | 'service_start' | 'service_complete' | 'abandon' | 'counter_failure' | 'counter_repaired' | 'bottleneck' | 'bottleneck_cleared' | 'recovery'
export interface TimelineItem { t: number; kind: TimelineKind; label: string; tone: 'info' | 'ok' | 'warn' | 'crit' }
export const SYSTEM_KINDS: TimelineKind[] = ['queue_formation', 'counter_failure', 'counter_repaired', 'bottleneck', 'bottleneck_cleared', 'recovery']
const cn = (i: number | undefined) => `Counter ${(i ?? 0) + 1}`

export function systemTimeline(pb: Pick<Playback, 'events' | 'episodes'>): TimelineItem[] {
  const out: TimelineItem[] = []
  for (const e of pb.events as TwinEvent[]) {
    if (e.type === 'counter_failure' || e.type === 'counter_outage') out.push({ t: e.t, kind: 'counter_failure', tone: 'crit', label: `${cn(e.counter)} ${e.type === 'counter_outage' ? 'outage' : 'failed'}` })
    else if (e.type === 'counter_repaired') out.push({ t: e.t, kind: 'counter_repaired', tone: 'ok', label: `${cn(e.counter)} back in service` })
    else if (e.type === 'recovery_action') {
      const what = e.action === 'activate_counter' ? `${cn(e.counter)} activated` : e.action === 'deactivate_counter' ? `${cn(e.counter)} closed` : e.action === 'boost_speed' ? `Staff assist: service ×${e.factor}` : 'Staff assist ended'
      out.push({ t: e.t, kind: 'recovery', tone: 'ok', label: `Recovery (${e.source ?? 'manual'}): ${what}${e.applied === false && e.note ? ` – ${e.note}` : ''}` })
    }
  }
  for (const f of pb.episodes.formation) out.push({ t: f.start, kind: 'queue_formation', tone: 'warn', label: `Queue forming (reached ${pb.episodes.formation_threshold}+, peak ${f.peak_queue})` })
  for (const b of pb.episodes.bottlenecks as Bottleneck[]) {
    out.push({ t: b.start, kind: 'bottleneck', tone: 'crit', label: `Bottleneck detected: queue ≥ ${b.threshold}; ${cn(b.most_loaded_counter)} busiest (${Math.round(b.most_loaded_utilization * 100)}%)` })
    out.push({ t: b.end, kind: 'bottleneck_cleared', tone: 'ok', label: `Bottleneck cleared (peak ${b.peak_queue})` })
  }
  return out.sort((a, b) => a.t - b.t)
}

export function customerTimeline(pb: Pick<Playback, 'customers'>): TimelineItem[] {
  const out: TimelineItem[] = []
  for (const [id, arr, start, end, counter, ab] of pb.customers) {
    out.push({ t: arr, kind: 'arrival', tone: 'info', label: `Customer #${id} arrives` })
    if (start !== null) out.push({ t: start, kind: 'service_start', tone: 'info', label: `Customer #${id} starts service at ${cn(counter ?? 0)}` })
    if (end !== null) out.push({ t: end, kind: 'service_complete', tone: 'info', label: `Customer #${id} served` })
    if (ab !== null) out.push({ t: ab, kind: 'abandon', tone: 'warn', label: `Customer #${id} leaves the queue` })
  }
  return out.sort((a, b) => a.t - b.t)
}

export const fmtClock = (t: number) => { const m = Math.floor(t), s = Math.floor((t - m) * 60); return `${m}:${String(s).padStart(2, '0')}` }
