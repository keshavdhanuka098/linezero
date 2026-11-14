import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Counter, Queue, Report, Settings, State } from './types'
import { seedState } from './seed'
import { cloneState, finishCustomer, fillCounters, log, makeCustomer, reroute, routeCustomer, stepState, uid } from './engine'
import { Rng, hashStr } from '../lib/rng'

export interface Actions {
  tick(): void
  setLive(on: boolean): void
  createQueue(p: { name: string; prefix: string; arrivalRate: number; routing: Queue['routing']; counters: number }): string
  renameQueue(id: string, name: string): void
  updateQueue(id: string, patch: Partial<Pick<Queue, 'arrivalRate' | 'routing' | 'prefix'>>): void
  deleteQueue(id: string): void
  addCounter(queueId: string, p: { name: string; servers: number; avgService: number }): void
  updateCounter(id: string, patch: Partial<Pick<Counter, 'name' | 'servers' | 'avgService' | 'routeWeight'>>): void
  deleteCounter(id: string): void
  toggleCounter(id: string): void
  addCustomer(queueId: string, label?: string): void
  completeNext(counterId: string): void
  removeCustomer(customerId: string): void
  addReport(r: Omit<Report, 'id' | 'createdAt'> & { createdAt?: string }): string
  updateReport(id: string, patch: Partial<Report>): void
  deleteReport(id: string): void
  updateSettings(patch: Partial<Settings>): void
  markNotifsRead(): void
  clearNotifs(): void
  resetDemo(): void
}
export type Store = State & Actions

const DATA_KEYS: (keyof State)[] = ['queues', 'counters', 'clock', 'seed', 'nextId', 'history', 'completed', 'activity', 'notifs', 'notifCool', 'reports', 'settings']
const pickData = (s: Store): State => Object.fromEntries(DATA_KEYS.map(k => [k, s[k]])) as unknown as State

function mutate(set: (p: Partial<State>) => void, get: () => Store, fn: (d: State) => void) {
  const d = cloneState(pickData(get()))
  fn(d)
  set(d)
}
const rngFor = (d: State) => new Rng(hashStr(`op:${d.seed}:${d.clock}:${d.nextId}`))

export const useStore = create<Store>()(persist((set, get) => ({
  ...seedState(),
  tick: () => set(stepState(pickData(get()))),
  setLive: on => mutate(set, get, d => { d.settings.liveFeed = on; log(d, 'system', on ? 'Demo simulation feed resumed' : 'Demo simulation feed paused') }),

  createQueue: p => {
    let id = ''
    mutate(set, get, d => {
      id = uid(d, 'q-')
      d.queues.push({ id, name: p.name.trim(), prefix: p.prefix.trim().toUpperCase() || p.name.trim()[0].toUpperCase(), arrivalRate: p.arrivalRate, routing: p.routing, nextTicket: 1, holding: [] })
      for (let i = 1; i <= p.counters; i++) d.counters.push({ id: uid(d, 'c-'), queueId: id, name: `Counter ${i}`, servers: 1, status: 'active', avgService: 4, routeWeight: 1, serving: [], waiting: [], utilEma: 0, served: 0 })
      log(d, 'queue', `Created queue “${p.name.trim()}” with ${p.counters} counter${p.counters === 1 ? '' : 's'}`)
    })
    return id
  },
  renameQueue: (id, name) => mutate(set, get, d => { const q = d.queues.find(x => x.id === id); if (q) { log(d, 'queue', `Renamed “${q.name}” to “${name.trim()}”`); q.name = name.trim() } }),
  updateQueue: (id, patch) => mutate(set, get, d => { const q = d.queues.find(x => x.id === id); if (q) Object.assign(q, patch) }),
  deleteQueue: id => mutate(set, get, d => {
    const q = d.queues.find(x => x.id === id); if (!q) return
    d.queues = d.queues.filter(x => x.id !== id); d.counters = d.counters.filter(c => c.queueId !== id)
    log(d, 'queue', `Deleted queue “${q.name}”`)
  }),

  addCounter: (queueId, p) => mutate(set, get, d => {
    const q = d.queues.find(x => x.id === queueId); if (!q) return
    d.counters.push({ id: uid(d, 'c-'), queueId, name: p.name.trim(), servers: p.servers, status: 'active', avgService: p.avgService, routeWeight: 1, serving: [], waiting: [], utilEma: 0, served: 0 })
    fillCounters(d, rngFor(d)); log(d, 'counter', `Added counter “${p.name.trim()}” to ${q.name}`)
  }),
  updateCounter: (id, patch) => mutate(set, get, d => {
    const c = d.counters.find(x => x.id === id); if (!c) return
    Object.assign(c, patch)
    if (patch.servers !== undefined) { log(d, 'counter', `${c.name} capacity set to ${c.servers} parallel server${c.servers === 1 ? '' : 's'}`); fillCounters(d, rngFor(d)) }
  }),
  deleteCounter: id => mutate(set, get, d => {
    const c = d.counters.find(x => x.id === id); if (!c) return
    d.counters = d.counters.filter(x => x.id !== id)
    const rng = rngFor(d), q = d.queues.find(x => x.id === c.queueId)
    if (q) { for (const m of [...c.waiting, ...c.serving.map(x => ({ ...x, startedAt: undefined, duration: undefined }))].sort((a, b) => a.arrivedAt - b.arrivedAt)) routeCustomer(d, q, m, rng) }
    fillCounters(d, rng); log(d, 'counter', `Removed counter “${c.name}”; its customers were re-queued`)
  }),
  toggleCounter: id => mutate(set, get, d => {
    const c = d.counters.find(x => x.id === id); if (!c) return
    const rng = rngFor(d)
    if (c.status === 'active') { c.status = 'paused'; reroute(d, c, rng); log(d, 'counter', `${c.name} paused — waiting customers redistributed`) }
    else { c.status = 'active'; fillCounters(d, rng); log(d, 'counter', `${c.name} resumed`) }
  }),

  addCustomer: (queueId, label) => mutate(set, get, d => {
    const q = d.queues.find(x => x.id === queueId); if (!q) return
    const cu = makeCustomer(d, q, label); routeCustomer(d, q, cu, rngFor(d)); log(d, 'arrival', `${cu.ticket} (${cu.label}) joined ${q.name}`)
  }),
  completeNext: counterId => mutate(set, get, d => {
    const c = d.counters.find(x => x.id === counterId); if (!c || !c.serving.length) return
    const cu = [...c.serving].sort((a, b) => (a.startedAt ?? 0) - (b.startedAt ?? 0))[0]
    finishCustomer(d, c, cu); fillCounters(d, rngFor(d)); log(d, 'served', `${cu.ticket} served at ${c.name}`)
  }),
  removeCustomer: customerId => mutate(set, get, d => {
    for (const q of d.queues) {
      const h = q.holding.findIndex(x => x.id === customerId)
      if (h >= 0) { log(d, 'queue', `${q.holding[h].ticket} removed from ${q.name}`); q.holding.splice(h, 1); return }
    }
    for (const c of d.counters) {
      const w = c.waiting.findIndex(x => x.id === customerId)
      if (w >= 0) { log(d, 'queue', `${c.waiting[w].ticket} removed from ${c.name} line`); c.waiting.splice(w, 1); return }
      const sIdx = c.serving.findIndex(x => x.id === customerId)
      if (sIdx >= 0) { log(d, 'queue', `${c.serving[sIdx].ticket} removed from service at ${c.name}`); c.serving.splice(sIdx, 1); fillCounters(d, rngFor(d)); return }
    }
  }),

  addReport: r => {
    const id = `r-${Date.now().toString(36)}`
    mutate(set, get, d => { d.reports.unshift({ ...r, id, createdAt: r.createdAt ?? new Date().toISOString() }); log(d, 'report', `Report saved: ${r.title}`) })
    return id
  },
  updateReport: (id, patch) => mutate(set, get, d => { const r = d.reports.find(x => x.id === id); if (r) Object.assign(r, patch) }),
  deleteReport: id => mutate(set, get, d => { d.reports = d.reports.filter(x => x.id !== id) }),
  updateSettings: patch => mutate(set, get, d => { d.settings = { ...d.settings, ...patch } }),
  markNotifsRead: () => mutate(set, get, d => { d.notifs.forEach(n => (n.read = true)) }),
  clearNotifs: () => mutate(set, get, d => { d.notifs = [] }),
  resetDemo: () => set(seedState()),
}), {
  name: 'linezero.app.v3',
  version: 3,
  partialize: s => pickData(s as Store),
  merge: (persisted, current) => {
    const p = persisted as Partial<State> | undefined
    if (!p || !Array.isArray(p.queues) || !Array.isArray(p.counters) || !p.settings) return current
    return { ...current, ...p, settings: { ...current.settings, ...p.settings, sim: { ...current.settings.sim, ...p.settings.sim } } }
  },
}))
