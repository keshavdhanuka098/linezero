import type { DataKind, IvStatus, Provenance, RiskRadarItem, Severity, Verification } from '../api/adaptiveTypes'

export type Tone = 'ok' | 'warn' | 'hot' | 'crit' | 'vio' | 'demo' | undefined

export const sevTone = (s: Severity | string | null | undefined): Tone =>
  s === 'LOW' ? 'ok' : s === 'MEDIUM' ? 'warn' : s === 'HIGH' ? 'hot' : s === 'CRITICAL' ? 'crit' : undefined

export const num = (v: number | null | undefined, d = 2) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—')
export const pct = (v: number | null | undefined, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : '—')
export const signed = (v: number | null | undefined, d = 2) => (typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}` : '—')

/** What kind of data a figure is. Shown as a tag next to numbers so measurements are never confused with model output. */
export const KIND: Record<DataKind, { label: string; tone: Tone }> = {
  observed: { label: 'Observed', tone: 'ok' },
  synthetic: { label: 'Synthetic', tone: 'demo' },
  simulated: { label: 'Simulated', tone: 'vio' },
  predicted: { label: 'Predicted', tone: 'warn' },
  explanation: { label: 'Explanation', tone: undefined },
}
/** Observed figures on a synthetic queue are synthetic, not real measurements. */
export const observedKind = (p: Provenance | null | undefined): DataKind => (p?.is_synthetic ? 'synthetic' : 'observed')

export const VERIFICATION: Record<Verification, { label: string; tone: Tone; text: string }> = {
  verified_real_observation: { label: 'Verified real observation', tone: 'ok', text: 'Measured from real queue data.' },
  synthetic_observation: { label: 'Synthetic observation', tone: 'demo', text: 'Measured on synthetic demo data — not a real-world result.' },
  operator_reported: { label: 'Operator reported', tone: 'warn', text: 'Typed in by an operator; not measured by LineZero.' },
}

export const STATUS_LABEL: Record<IvStatus, string> = { proposed: 'Proposed', approved: 'Approved', rejected: 'Rejected', applied: 'Applied by operator', evaluated: 'Outcome recorded' }
export const STATUS_TONE: Record<IvStatus, Tone> = { proposed: 'vio', approved: 'warn', rejected: undefined, applied: 'warn', evaluated: 'ok' }

/** Operator actions that are legal for a status (mirrors the backend workflow; the backend still enforces it). */
export function nextActions(status: IvStatus): ('approve' | 'reject' | 'applied' | 'outcome')[] {
  switch (status) {
    case 'proposed': return ['approve', 'reject']
    case 'approved': return ['applied', 'reject']
    case 'applied': return ['outcome']
    default: return []
  }
}

export const RADAR_ORDER = ['queue_congestion', 'counter_overload', 'waiting_time_trend', 'capacity_shortage', 'counter_failure_precursor', 'abnormal_arrivals', 'utilization_imbalance']

/** Radar chart rows in a fixed order, scores as 0-100. Categories the backend did not return are left out, never invented. */
export function radarRows(radar: Record<string, RiskRadarItem> | undefined) {
  if (!radar) return []
  return RADAR_ORDER.filter(k => radar[k]).map(k => ({ key: k, label: radar[k].label, value: Math.round(radar[k].score * 100), severity: radar[k].severity, status: radar[k].status, resource: radar[k].resource }))
}

export const VERDICT: Record<string, string> = {
  as_expected: 'About as the simulation expected', consistent_with_expectation: 'Within the uncertainty of the measurement',
  better_than_expected: 'Better than simulated', worse_than_expected: 'Worse than simulated', no_expectation: 'No expectation to compare with',
}

export const typeLabel = (t: string) => t.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
