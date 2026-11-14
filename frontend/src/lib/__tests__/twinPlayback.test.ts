import { describe, expect, it } from 'vitest'
import type { Playback, TwinCustomer, TwinFrame } from '../../api/twinTypes'
import { DEFAULT_FORM, buildConfig, customerTimeline, formFromConfig, frameAt, injectChaos, sceneAt, systemTimeline, validateForm } from '../twinPlayback'

const frames: TwinFrame[] = [0, 1, 2, 3].map(t => ({ t, queue: t, in_service: 1, arrivals: t, served: 0, abandoned: 0, longest_wait: t, counters: t < 2 ? [1, 0] : [2, 0] }))
// id, arrival, start, end, counter, abandon
const customers: TwinCustomer[] = [[1, 0, 0, 2, 0, null], [2, 0.5, 2, null, 1, null], [3, 1, null, null, null, 2.5], [4, 1.5, null, null, null, null]]
const pb = { customers, frames, num_counters: 2 }

describe('frameAt', () => {
  it('returns the last frame at or before t', () => {
    expect(frameAt(frames, 0).t).toBe(0)
    expect(frameAt(frames, 1.9).t).toBe(1)
    expect(frameAt(frames, 99).t).toBe(3)
  })
})

describe('sceneAt', () => {
  it('places customers as waiting / in service / served / abandoned', () => {
    const s = sceneAt(pb, 1.6)
    expect(s.arrivals).toBe(4)
    expect(s.counters[0].servingId).toBe(1)
    expect(s.dots.map(d => d.id)).toEqual([2, 3, 4])
    const later = sceneAt(pb, 2.6)
    expect(later.served).toBe(1)
    expect(later.abandoned).toBe(1)
    expect(later.counters[1].servingId).toBe(2)
    expect(later.counters[0].state).toBe('failed')
  })
  it('caps visible dots and reports the overflow', () => {
    const many: TwinCustomer[] = Array.from({ length: 50 }, (_, i) => [i + 1, 0, null, null, null, null])
    const s = sceneAt({ customers: many, frames, num_counters: 1 }, 1, 36)
    expect(s.dots).toHaveLength(36)
    expect(s.overflow).toBe(14)
  })
})

describe('timelines', () => {
  it('lists customer lifecycle events in time order', () => {
    const items = customerTimeline({ customers })
    expect(items.map(i => i.t)).toEqual([...items.map(i => i.t)].sort((a, b) => a - b))
    expect(items.filter(i => i.kind === 'arrival')).toHaveLength(4)
    expect(items.some(i => i.kind === 'abandon')).toBe(true)
  })
  it('turns engine events and episodes into timeline items', () => {
    const items = systemTimeline({
      events: [{ t: 5, type: 'counter_failure', counter: 0 }, { t: 9, type: 'recovery_action', action: 'activate_counter', counter: 3, source: 'auto', applied: true }],
      episodes: { formation: [{ start: 3, end: 8, peak_queue: 6 }], bottlenecks: [{ start: 6, end: 12, peak_queue: 14, most_loaded_counter: 1, most_loaded_utilization: 0.98, failed_counters: [0], closed_counters: [], avg_counters_available: 3, threshold: 10 }], congestion_threshold: 10, formation_threshold: 3 },
    } as Pick<Playback, 'events' | 'episodes'>)
    expect(items.map(i => i.kind)).toEqual(['queue_formation', 'counter_failure', 'bottleneck', 'recovery', 'bottleneck_cleared'])
  })
})

describe('form validation and config building', () => {
  it('accepts the default form', () => { expect(validateForm(DEFAULT_FORM)).toEqual({}) })
  it('rejects impossible values', () => {
    const e = validateForm({ ...DEFAULT_FORM, arrival_rate: '-1', num_counters: '2.5', staff: '9', duration: '1' })
    expect(Object.keys(e)).toEqual(expect.arrayContaining(['arrival_rate', 'num_counters', 'duration']))
    expect(validateForm({ ...DEFAULT_FORM, staff: '9' }).staff).toBeDefined()
  })
  it('rejects overlapping surges and unknown counters', () => {
    const f = { ...DEFAULT_FORM, surges: [{ id: 1, start: '10', end: '40', multiplier: '2' }, { id: 2, start: '30', end: '50', multiplier: '2' }], outages: [{ id: 3, counter: 9, start: '5', end: '' }] }
    const e = validateForm(f)
    expect(e.surge2).toMatch(/overlap/)
    expect(e.outage3).toMatch(/Counter/)
  })
  it('builds the API configuration for chaos settings', () => {
    const f = { ...DEFAULT_FORM, staff: '3', speed_pct: '80', outages: [{ id: 1, counter: 0, start: '20', end: '' }], surges: [{ id: 2, start: '30', end: '60', multiplier: '2' }] }
    const c = buildConfig(f)
    expect(c.staff_available).toBe(3)
    expect(c.counter_speed_factors).toEqual(Array(5).fill(0.8))
    expect(c.outages).toEqual([{ counter: 0, start: 20, end: null, kind: 'failure' }])
    expect(c.arrival_profile).toEqual([{ start: 30, end: 60, multiplier: 2 }])
    expect(c.recovery).toBeUndefined()
  })
  it('round-trips a config through the form', () => {
    const c = buildConfig({ ...DEFAULT_FORM, staff: '3', standby: [4], outages: [{ id: 1, counter: 1, start: '10', end: '50' }] })
    const back = buildConfig(formFromConfig(c))
    expect(back).toEqual(c)
  })
  it('injects chaos at the playhead', () => {
    const f = injectChaos(DEFAULT_FORM, 'outage', 42, 2, 10)
    expect(f.outages[0]).toMatchObject({ counter: 2, start: '42', end: '52' })
    expect(validateForm(f)).toEqual({})
    expect(injectChaos(DEFAULT_FORM, 'failure', 30, 0).outages[0].end).toBe('')
    expect(injectChaos(DEFAULT_FORM, 'staff', 30, 1).actions[0].type).toBe('deactivate_counter')
  })
})
