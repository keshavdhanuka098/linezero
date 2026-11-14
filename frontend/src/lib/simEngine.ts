import { Rng, sampleCV } from './rng'

export interface SimParams {
  arrivalRate: number
  avgService: number
  counters: number
  duration: number
  arrivalCV: number
  serviceCV: number
  seed: number
}

export interface SimPoint { t: number; queue: number; inService: number; avgWait: number }
interface Cust { id: number; arrivedAt: number }
interface SimCounter { cust: Cust | null; startedAt: number; busyDone: number; served: number }
export interface Departure { counter: number; t: number }

export interface SimMetrics {
  t: number
  done: boolean
  queueLength: number
  inService: number
  avgWait: number
  maxWait: number
  served: number
  arrived: number
  remaining: number
  utilization: number
  counterUtil: number[]
}

export class Simulation {
  p: SimParams
  t = 0
  private rng: Rng
  private line: Cust[] = []
  private counters: SimCounter[]
  private nextArrival: number
  private nextId = 1
  arrived = 0
  served = 0
  private waitSum = 0
  private maxWaitServed = 0
  series: SimPoint[] = []
  private nextSample = 0
  private sampleStep: number
  departures: Departure[] = []

  constructor(p: SimParams) {
    this.p = p
    this.rng = new Rng(p.seed)
    this.counters = Array.from({ length: p.counters }, () => ({ cust: null, startedAt: 0, busyDone: 0, served: 0 }))
    this.sampleStep = Math.max(0.5, p.duration / 240)
    this.nextArrival = this.interArrival()
  }

  private interArrival() { return sampleCV(this.rng.next, 1 / this.p.arrivalRate, this.p.arrivalCV) }
  private svc() { return Math.max(0.05, sampleCV(this.rng.next, this.p.avgService, this.p.serviceCV)) }

  private finishAt: number[] = []
  private ensureFinish() { if (this.finishAt.length !== this.counters.length) this.finishAt = this.counters.map(() => Infinity) }

  private start(i: number, c: Cust, at: number) {
    this.ensureFinish()
    const k = this.counters[i]
    k.cust = c; k.startedAt = at
    this.finishAt[i] = at + this.svc()
    const w = at - c.arrivedAt
    this.waitSum += w
    if (w > this.maxWaitServed) this.maxWaitServed = w
  }

  private sampleUntil(tt: number) {
    while (this.nextSample <= tt && this.nextSample <= this.p.duration) {
      const s = this.nextSample
      this.series.push({
        t: Math.round(s * 100) / 100,
        queue: this.line.length,
        inService: this.counters.filter(c => c.cust).length,
        avgWait: this.startedCount() ? this.waitSum / this.startedCount() : 0,
      })
      this.nextSample += this.sampleStep
    }
  }
  private startedCount() { return this.served + this.counters.filter(c => c.cust).length }

  get done() { return this.t >= this.p.duration }

  advanceTo(target: number) {
    this.ensureFinish()
    const end = Math.min(target, this.p.duration)
    for (;;) {
      let nextT = this.nextArrival < this.p.duration ? this.nextArrival : Infinity
      let kind: 'arr' | number = 'arr'
      for (let i = 0; i < this.finishAt.length; i++) {
        if (this.counters[i].cust && this.finishAt[i] < nextT) { nextT = this.finishAt[i]; kind = i }
      }
      if (nextT > end) break
      this.sampleUntil(nextT)
      this.t = nextT
      if (kind === 'arr') {
        const c: Cust = { id: this.nextId++, arrivedAt: nextT }
        this.arrived++
        const free = this.counters.findIndex(k => !k.cust)
        if (free >= 0) this.start(free, c, nextT); else this.line.push(c)
        this.nextArrival = nextT + this.interArrival()
      } else {
        const k = this.counters[kind]
        k.busyDone += nextT - k.startedAt
        k.cust = null; k.served++; this.served++
        this.finishAt[kind] = Infinity
        this.departures.push({ counter: kind, t: nextT })
        if (this.departures.length > 40) this.departures.shift()
        const nxt = this.line.shift()
        if (nxt) this.start(kind, nxt, nextT)
      }
    }
    this.sampleUntil(end)
    this.t = end
  }

  runAll(): SimMetrics { this.advanceTo(this.p.duration); return this.metrics() }

  metrics(): SimMetrics {
    const t = this.t
    const counterUtil = this.counters.map(k => (t > 0 ? Math.min(1, (k.busyDone + (k.cust ? t - k.startedAt : 0)) / t) : 0))
    const started = this.startedCount()
    const headWait = this.line.length ? t - this.line[0].arrivedAt : 0
    const inService = this.counters.filter(c => c.cust).length
    return {
      t, done: this.done,
      queueLength: this.line.length, inService,
      avgWait: started ? this.waitSum / started : 0,
      maxWait: Math.max(this.maxWaitServed, headWait),
      served: this.served, arrived: this.arrived,
      remaining: this.line.length + inService,
      utilization: counterUtil.length ? counterUtil.reduce((a, b) => a + b, 0) / counterUtil.length : 0,
      counterUtil,
    }
  }

  view() {
    return {
      line: this.line.map(c => this.t - c.arrivedAt),
      counters: this.counters.map(k => ({ busy: !!k.cust, progress: k.cust ? (this.t - k.startedAt) / Math.max(0.01, this.finishAt[this.counters.indexOf(k)] - k.startedAt) : 0 })),
    }
  }
}

export function runSimulation(p: SimParams) {
  const s = new Simulation(p)
  const m = s.runAll()
  return { metrics: m, series: s.series }
}
