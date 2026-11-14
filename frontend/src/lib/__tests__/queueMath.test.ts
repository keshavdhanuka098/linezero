import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { allenCunneenWq, erlangC, median } from '../queueMath'

const fixtures = JSON.parse(readFileSync(resolve(__dirname, '../../../../shared/queueing_fixtures.json'), 'utf8')).cases as {
  lambda: number; mu: number; servers: number; p_wait?: number; wq?: number; lq?: number; stable?: boolean
}[]

describe('erlangC matches the backend reference values', () => {
  for (const c of fixtures) {
    it(`λ=${c.lambda} μ=${c.mu} c=${c.servers}`, () => {
      const r = erlangC(c.lambda, c.mu, c.servers)
      if (c.stable === false) { expect(r.stable).toBe(false); return }
      expect(r.pWait).toBeCloseTo(c.p_wait!, 9)
      expect(r.wq).toBeCloseTo(c.wq!, 9)
      expect(r.lq).toBeCloseTo(c.lq!, 9)
    })
  }
})

describe('queueMath', () => {
  it('Allen–Cunneen reduces to M/M/c when both CVs are 1', () => {
    expect(allenCunneenWq(1.5, 1, 2, 1, 1)).toBeCloseTo(erlangC(1.5, 1, 2).wq, 12)
  })
  it('Allen–Cunneen scales with variability', () => {
    expect(allenCunneenWq(1.5, 1, 2, 1, 0)).toBeCloseTo(erlangC(1.5, 1, 2).wq / 2, 12)
  })
  it('is infinite when demand exceeds capacity', () => {
    expect(allenCunneenWq(3, 1, 2, 1, 1)).toBe(Infinity)
  })
  it('median handles odd, even and empty input', () => {
    expect([median([3, 1, 2]), median([4, 1, 3, 2]), median([])]).toEqual([2, 2.5, 0])
  })
})
