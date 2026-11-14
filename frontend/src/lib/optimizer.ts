import type { Counter, Queue } from '../store/types'
import { allenCunneenWq } from './queueMath'

export interface QInput { id: string; name: string; lambda: number; svc: number; current: number; ca: number; cs: number }
export interface QResult { id: string; name: string; servers: number; rho: number; util: number; wq: number; lq: number; stable: boolean }

export function buildInputs(queues: Queue[], counters: Counter[], factor: number, ca = 1, cs = 0.6): QInput[] {
  return queues.map(q => {
    const act = counters.filter(c => c.queueId === q.id && c.status === 'active')
    const sv = act.reduce((a, c) => a + c.servers, 0)
    const svc = sv ? act.reduce((a, c) => a + c.avgService * c.servers, 0) / sv : (counters.filter(c => c.queueId === q.id)[0]?.avgService ?? 4)
    return { id: q.id, name: q.name, lambda: q.arrivalRate * factor, svc, current: sv, ca, cs }
  })
}

export function evaluate(i: QInput, servers: number): QResult {
  if (servers <= 0) return { id: i.id, name: i.name, servers, rho: Infinity, util: 1, wq: Infinity, lq: Infinity, stable: false }
  const rho = (i.lambda * i.svc) / servers
  const wq = allenCunneenWq(i.lambda, i.svc, servers, i.ca, i.cs)
  return { id: i.id, name: i.name, servers, rho, util: Math.min(1, rho), wq, lq: Number.isFinite(wq) ? i.lambda * wq : Infinity, stable: rho < 1 }
}

export function cost(inputs: QInput[], alloc: number[]): number {
  return inputs.reduce((a, i, k) => {
    const r = evaluate(i, alloc[k])
    return a + (r.stable ? i.lambda * r.wq : i.lambda * (1000 + 1000 * (Number.isFinite(r.rho) ? r.rho : 50)))
  }, 0)
}

export function compositionCount(total: number, parts: number): number {
  if (parts <= 0 || total < parts) return 0
  let r = 1; const n = total - 1, k = parts - 1
  for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i
  return Math.round(r)
}

export interface SearchResult { alloc: number[]; cost: number; evaluated: number; exhaustive: boolean }
export function searchBest(inputs: QInput[], total: number): SearchResult | null {
  const Q = inputs.length
  if (!Q || total < Q) return null
  const space = compositionCount(total, Q)
  if (space <= 250_000) {
    let best: number[] = [], bestC = Infinity, n = 0
    const cur = new Array(Q).fill(1)
    const rec = (k: number, left: number) => {
      if (k === Q - 1) { cur[k] = left; n++; const c = cost(inputs, cur); if (c < bestC - 1e-12) { bestC = c; best = cur.slice() } return }
      for (let v = 1; v <= left - (Q - 1 - k); v++) { cur[k] = v; rec(k + 1, left - v) }
    }
    rec(0, total)
    return { alloc: best, cost: bestC, evaluated: n, exhaustive: true }
  }
  const alloc = new Array(Q).fill(1)
  for (let s = Q; s < total; s++) {
    let bi = 0, bc = Infinity
    for (let k = 0; k < Q; k++) { alloc[k]++; const c = cost(inputs, alloc); alloc[k]--; if (c < bc) { bc = c; bi = k } }
    alloc[bi]++
  }
  return { alloc, cost: cost(inputs, alloc), evaluated: Q * total, exhaustive: false }
}

export function minServersFor(i: QInput, target: number, cap = 40): number | null {
  for (let n = 1; n <= cap; n++) { const r = evaluate(i, n); if (r.stable && r.wq <= target) return n }
  return null
}

export function summarize(inputs: QInput[], alloc: number[]) {
  const res = inputs.map((i, k) => evaluate(i, alloc[k]))
  const lam = inputs.reduce((a, i) => a + i.lambda, 0) || 1
  const stable = res.every(r => r.stable)
  return {
    res, stable,
    avgWait: stable ? res.reduce((a, r, k) => a + r.wq * inputs[k].lambda, 0) / lam : Infinity,
    lq: stable ? res.reduce((a, r) => a + r.lq, 0) : Infinity,
    util: res.reduce((a, r) => a + r.util * r.servers, 0) / Math.max(1, res.reduce((a, r) => a + r.servers, 0)),
    servers: alloc.reduce((a, b) => a + b, 0),
  }
}
