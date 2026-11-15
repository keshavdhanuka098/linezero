import { describe, expect, it } from 'vitest'
import { RADAR_ORDER, nextActions, num, observedKind, pct, radarRows, sevTone, signed, typeLabel, VERIFICATION } from './adaptive'
import type { Provenance, RiskRadarItem } from '../api/adaptiveTypes'

const prov = (is_synthetic: boolean) => ({ is_synthetic }) as Provenance

describe('formatting never invents numbers', () => {
  it('shows a dash for missing or non-finite values', () => {
    expect(num(null)).toBe('—'); expect(num(undefined)).toBe('—'); expect(num(NaN)).toBe('—'); expect(pct(null)).toBe('—'); expect(signed(Infinity)).toBe('—')
  })
  it('formats values', () => {
    expect(num(1.2345)).toBe('1.23'); expect(pct(0.256)).toBe('26%'); expect(signed(-1.5)).toBe('−1.50'); expect(signed(2)).toBe('+2.00'); expect(signed(0)).toBe('0.00')
  })
})

describe('severity and provenance labelling', () => {
  it('maps severities to tones and leaves none unmapped', () => {
    expect(sevTone('LOW')).toBe('ok'); expect(sevTone('CRITICAL')).toBe('crit'); expect(sevTone(null)).toBeUndefined()
  })
  it('observed figures on a synthetic queue are labelled synthetic', () => {
    expect(observedKind(prov(true))).toBe('synthetic'); expect(observedKind(prov(false))).toBe('observed')
  })
  it('only real measurements are called verified', () => {
    expect(VERIFICATION.verified_real_observation.label).toMatch(/Verified/)
    expect(VERIFICATION.synthetic_observation.label).not.toMatch(/Verified/i)
    expect(VERIFICATION.operator_reported.label).not.toMatch(/Verified/i)
  })
})

describe('operator workflow', () => {
  it('offers only the legal next actions', () => {
    expect(nextActions('proposed')).toEqual(['approve', 'reject'])
    expect(nextActions('approved')).toEqual(['applied', 'reject'])
    expect(nextActions('applied')).toEqual(['outcome'])
    expect(nextActions('rejected')).toEqual([]); expect(nextActions('evaluated')).toEqual([])
  })
  it('cannot skip approval: "applied" is never offered for a proposal', () => {
    expect(nextActions('proposed')).not.toContain('applied')
  })
})

describe('radar rows', () => {
  const item = (score: number): RiskRadarItem => ({ label: 'x', score, severity: null, resource: '', status: 'ok' })
  it('keeps a fixed order, scales to 0-100 and omits missing categories', () => {
    const rows = radarRows({ abnormal_arrivals: item(0.5), queue_congestion: item(0.256) })
    expect(rows.map(r => r.key)).toEqual(['queue_congestion', 'abnormal_arrivals']); expect(rows[0].value).toBe(26)
    expect(radarRows(undefined)).toEqual([]); expect(RADAR_ORDER).toHaveLength(7)
  })
})

describe('labels', () => { it('humanises type keys', () => expect(typeLabel('open_counter')).toBe('Open counter')) })
