import { describe, expect, it } from 'vitest'
import { runSimulation, type SimParams } from '../simEngine'
import { erlangC } from '../queueMath'
import { Rng, hashStr, poisson } from '../rng'

const base: SimParams = { arrivalRate: 1.2, avgService: 4, counters: 6, duration: 4000, arrivalCV: 1, serviceCV: 1, seed: 7 }

describe('rng', () => {
  it('is deterministic per seed', () => {
    const a = new Rng(hashStr('x')), b = new Rng(hashStr('x'))
    expect([a.next(), a.next()]).toEqual([b.next(), b.next()])
  })
  it('poisson has roughly the requested mean', () => {
    const r = new Rng(1)
    let s = 0
    for (let i = 0; i < 5000; i++) s += poisson(r.next, 3)
    expect(s / 5000).toBeGreaterThan(2.85)
    expect(s / 5000).toBeLessThan(3.15)
  })
})

describe('simulation', () => {
  it('same seed and parameters give identical results', () => {
    expect(runSimulation(base)).toEqual(runSimulation(base))
  })
  it('conserves customers', () => {
    const m = runSimulation({ ...base, duration: 300 }).metrics
    expect(m.served + m.remaining).toBe(m.arrived)
  })
  it('average wait approaches the M/M/c value for a long run', () => {
    const theory = erlangC(base.arrivalRate, 1 / base.avgService, base.counters).wq
    const m = runSimulation(base).metrics
    expect(Math.abs(m.avgWait - theory)).toBeLessThan(Math.max(0.6, theory * 0.35))
  })
  it('adding counters does not increase the wait', () => {
    const a = runSimulation({ ...base, counters: 5, duration: 1500 }).metrics.avgWait
    const b = runSimulation({ ...base, counters: 8, duration: 1500 }).metrics.avgWait
    expect(b).toBeLessThanOrEqual(a)
  })
})
