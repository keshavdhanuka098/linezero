import { describe, expect, it } from 'vitest'
import { compositionCount, cost, evaluate, minServersFor, searchBest, summarize, type QInput } from '../optimizer'

const mk = (id: string, lambda: number, svc: number, current: number): QInput => ({ id, name: id, lambda, svc, current, ca: 1, cs: 0.6 })
const inputs = [mk('a', 1.2, 4, 6), mk('b', 0.3, 4, 3), mk('c', 0.1, 8, 2)]

describe('optimizer', () => {
  it('counts compositions', () => {
    expect(compositionCount(5, 2)).toBe(4)
    expect(compositionCount(2, 3)).toBe(0)
  })
  it('exhaustive search equals brute force', () => {
    const total = 11
    const r = searchBest(inputs, total)!
    let best = Infinity
    for (let x = 1; x <= total - 2; x++) for (let y = 1; y <= total - x - 1; y++) best = Math.min(best, cost(inputs, [x, y, total - x - y]))
    expect(r.exhaustive).toBe(true)
    expect(r.evaluated).toBe(compositionCount(total, 3))
    expect(r.cost).toBeCloseTo(best, 12)
    expect(r.alloc.reduce((a, b) => a + b, 0)).toBe(total)
  })
  it('never proposes fewer than one server per queue', () => {
    expect(searchBest(inputs, 3)!.alloc).toEqual([1, 1, 1])
    expect(searchBest(inputs, 2)).toBeNull()
  })
  it('flags unstable allocations and ranks them worse', () => {
    expect(evaluate(inputs[0], 4).stable).toBe(false)
    expect(cost(inputs, [4, 3, 2])).toBeGreaterThan(cost(inputs, [8, 2, 1]))
  })
  it('minServersFor returns the smallest stable count within target', () => {
    const n = minServersFor(inputs[0], 5)!
    expect(evaluate(inputs[0], n).wq).toBeLessThanOrEqual(5)
    expect(evaluate(inputs[0], n - 1).wq).toBeGreaterThan(5)
  })
  it('summarize reports infinite wait when any queue is unstable', () => {
    expect(summarize(inputs, [4, 3, 2]).avgWait).toBe(Infinity)
    expect(Number.isFinite(summarize(inputs, [8, 3, 2]).avgWait)).toBe(true)
  })
})
