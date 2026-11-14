import type { Counter, Customer, Queue, State, Notif } from './types'
import { Rng, hashStr, poisson, sampleCV } from '../lib/rng'
import { counterEstWait, demandProfile, demoHour, demoTimeLabel, queueMetrics, queueRisk, riskLevel } from '../lib/metrics'
import { mean } from '../lib/queueMath'

export const cloneState = (s: State): State => structuredClone(s)

export function uid(s: State, p: string) { return `${p}${s.nextId++}` }

export function log(s: State, kind: State['activity'][number]['kind'], text: string, source: 'demo' | 'user' = 'user') {
  s.activity.push({ id: uid(s, 'a'), t: s.clock, kind, text, source })
  if (s.activity.length > 60) s.activity.splice(0, s.activity.length - 60)
}

function startService(c: Counter, cust: Customer, clock: number, rng: Rng) {
  cust.startedAt = clock
  cust.duration = Math.max(0.4, sampleCV(rng.next, c.avgService, 0.55))
  c.serving.push(cust)
}

export function routeCustomer(s: State, q: Queue, cust: Customer, rng: Rng) {
  const act = s.counters.filter(c => c.queueId === q.id && c.status === 'active')
  if (!act.length) { q.holding.push(cust); return }
  let pick: Counter
  if (q.routing === 'shortest') {
    pick = act.reduce((a, b) => (counterEstWait(b) < counterEstWait(a) ? b : a))
  } else {
    const tot = act.reduce((a, c) => a + c.routeWeight, 0) || 1
    let r = rng.next() * tot
    pick = act[act.length - 1]
    for (const c of act) { r -= c.routeWeight; if (r <= 0) { pick = c; break } }
  }
  if (pick.serving.length < pick.servers && pick.waiting.length === 0) startService(pick, cust, s.clock, rng)
  else pick.waiting.push(cust)
}

export function fillCounters(s: State, rng: Rng) {
  for (const q of s.queues) {
    for (const c of s.counters.filter(x => x.queueId === q.id && x.status === 'active')) {
      while (c.serving.length < c.servers) {
        const nxt = c.waiting.shift() ?? q.holding.shift()
        if (!nxt) break
        startService(c, nxt, s.clock, rng)
      }
    }
  }
}

export function finishCustomer(s: State, c: Counter, cust: Customer) {
  c.serving = c.serving.filter(x => x.id !== cust.id)
  c.served++
  const service = cust.duration ?? c.avgService
  s.completed.push({ queueId: c.queueId, counterId: c.id, wait: Math.max(0, (cust.startedAt ?? s.clock) - cust.arrivedAt), service, at: s.clock })
  if (s.completed.length > 300) s.completed.splice(0, s.completed.length - 300)
}

export function reroute(s: State, c: Counter, rng: Rng, includeServing = false) {
  const q = s.queues.find(x => x.id === c.queueId)
  if (!q) return
  const moving = [...c.waiting]; c.waiting = []
  if (includeServing) { moving.push(...c.serving.map(x => ({ ...x, startedAt: undefined, duration: undefined }))); c.serving = [] }
  moving.sort((a, b) => a.arrivedAt - b.arrivedAt)
  for (const m of moving) routeCustomer(s, q, m, rng)
}

export function makeCustomer(s: State, q: Queue, label?: string): Customer {
  const n = q.nextTicket++
  return { id: uid(s, 'u'), ticket: `${q.prefix}-${n}`, label: label?.trim() || `Customer ${q.prefix}-${n}`, queueId: q.id, arrivedAt: s.clock }
}

function notify(s: State, key: string, severity: Notif['severity'], title: string, body: string, cooldown = 30) {
  const last = s.notifCool[key]
  if (last !== undefined && s.clock - last < cooldown) return
  s.notifCool[key] = s.clock
  s.notifs.unshift({ id: uid(s, 'n'), t: s.clock, severity, title, body, read: false, key })
  if (s.notifs.length > 40) s.notifs.length = 40
}

export function stepState(prev: State, quiet = false): State {
  const s = cloneState(prev)
  s.clock++
  const rng = new Rng(hashStr(`${s.seed}:${s.clock}`))
  const hour = demoHour(s.clock)
  const prof = demandProfile(hour)
  let arrivalsTotal = 0
  const arrByQueue: Record<string, number> = {}

  for (const q of s.queues) {
    const n = poisson(rng.next, q.arrivalRate * prof)
    arrByQueue[q.id] = n; arrivalsTotal += n
    for (let i = 0; i < n; i++) routeCustomer(s, q, makeCustomer(s, q), rng)
    if (n >= 4 && !quiet) log(s, 'arrival', `Arrival burst: ${n} customers joined ${q.name} in one minute`, 'demo')
  }
  for (const c of s.counters) {
    for (const cust of [...c.serving]) {
      if (cust.startedAt !== undefined && s.clock - cust.startedAt >= (cust.duration ?? c.avgService)) finishCustomer(s, c, cust)
    }
  }
  fillCounters(s, rng)
  for (const c of s.counters) c.utilEma = c.utilEma * 0.9 + 0.1 * Math.min(1, c.serving.length / c.servers)

  const recent = s.completed.slice(-25)
  const sm = s.queues.map(q => queueMetrics(q, s.counters))
  const byQueue: Record<string, number> = {}
  s.queues.forEach((q, i) => { byQueue[q.id] = sm[i].waiting })
  const act = s.counters.filter(c => c.status === 'active'), sv = act.reduce((a, c) => a + c.servers, 0)
  const risks = s.queues.map(q => queueRisk(q, s.counters, s.history, s.settings.thresholds))
  s.history.push({
    t: s.clock, waiting: sm.reduce((a, m) => a + m.waiting, 0), serving: sm.reduce((a, m) => a + m.serving, 0),
    arrivals: arrivalsTotal, avgWait: recent.length ? mean(recent.map(r => r.wait)) : 0,
    util: sv ? act.reduce((a, c) => a + c.utilEma * c.servers, 0) / sv : 0,
    risk: risks.length ? Math.max(...risks) : 0, byQueue, arrByQueue,
  })
  if (s.history.length > 180) s.history.splice(0, s.history.length - 180)

  if (!quiet) {
    const th = s.settings.thresholds, nf = s.settings.notify
    s.queues.forEach((q, i) => {
      if (nf.longWait && risks[i] >= 60) notify(s, `risk:${q.id}`, risks[i] >= 80 ? 'crit' : 'warn', `${riskLevel(risks[i])} congestion risk — ${q.name}`, `Risk score ${risks[i]}/100 at ${demoTimeLabel(s.clock)} (heuristic).`)
      if (nf.longWait && Number.isFinite(sm[i].estWait) && sm[i].estWait > th.waitSla * 1.5) notify(s, `wait:${q.id}`, 'warn', `Estimated wait above target — ${q.name}`, `~${sm[i].estWait.toFixed(0)} min vs ${th.waitSla} min target.`, 45)
    })
    if (nf.highUtil) for (const c of act) if (c.utilEma >= th.highUtil && c.serving.length) notify(s, `util:${c.id}`, 'warn', `${c.name} running hot`, `Smoothed utilization ${(c.utilEma * 100).toFixed(0)}% (limit ${(th.highUtil * 100).toFixed(0)}%).`, 60)
  }
  return s
}
