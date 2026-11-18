import { describe, expect, it } from 'vitest'
import type { SlaCustomer, TrendBucket } from '../api/slaTypes'
import { atRiskCount, CLASS_PATTERN, probPct, remainingText, scoreText, scoreTone, sortCustomers, trendRows, validatePolicy } from './sla'

const cust = (position: number, status: SlaCustomer['status'], p: number) => ({ position, status, breach_probability: p }) as SlaCustomer

describe('sla helpers', () => {
  it('formats probabilities without rounding to false certainty', () => {
    expect(probPct(0.999)).toBe('>99%'); expect(probPct(1)).toBe('100%'); expect(probPct(0.001)).toBe('<1%')
    expect(probPct(0)).toBe('0%'); expect(probPct(null)).toBe('—'); expect(probPct(Number.NaN)).toBe('—')
  })
  it('shows a missing score as a dash, never zero', () => {
    expect(scoreText(null)).toBe('—'); expect(scoreText(100)).toBe('100'); expect(scoreText(87.46)).toBe('87.5')
    expect(scoreTone(null)).toBeUndefined(); expect(scoreTone(96)).toBe('ok'); expect(scoreTone(50)).toBe('crit')
  })
  it('describes remaining time and overruns', () => {
    expect(remainingText(3.24)).toBe('3.2 min left'); expect(remainingText(-1.4)).toBe('over by 1.4 min')
  })
  it('sorts the most urgent customers first', () => {
    const rows = sortCustomers([cust(1, 'safe', 0.01), cust(2, 'breached', 1), cust(3, 'critical', 0.7), cust(4, 'critical', 0.9)])
    expect(rows.map(r => r.position)).toEqual([2, 4, 3, 1])
  })
  it('counts every non-safe customer', () => {
    expect(atRiskCount({ safe: 5, at_risk: 2, critical: 1, breached: 3 })).toBe(6); expect(atRiskCount(undefined)).toBe(0)
  })
  it('keeps empty trend buckets as gaps', () => {
    const b = [{ start_s: 0, score: null, served: 0, breached: 0, avg_wait_min: null, avg_target_min: null }] as unknown as TrendBucket[]
    expect(trendRows(b, () => 'x')[0].score).toBeNull()
  })
  it('validates a policy like the backend does', () => {
    expect(validatePolicy(10, 0.25, 0.6)).toBeNull()
    expect(validatePolicy(0, 0.25, 0.6)).toMatch(/between 0 and 1440/); expect(validatePolicy(2000, 0.25, 0.6)).toMatch(/1440/)
    expect(validatePolicy(10, 0.6, 0.25)).toMatch(/lower/); expect(validatePolicy(10, 0, 0.5)).toMatch(/exclusive/)
    expect(CLASS_PATTERN.test('priority')).toBe(true); expect(CLASS_PATTERN.test('Bad Name')).toBe(false)
  })
})
