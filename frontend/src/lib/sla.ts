import type { SlaCustomer, SlaStatus, TrendBucket } from '../api/slaTypes'
import type { Tone } from './adaptive'

export const SLA_STATUS: Record<SlaStatus, { label: string; tone: Tone; rank: number }> = {
  safe: { label: 'Safe', tone: 'ok', rank: 0 }, at_risk: { label: 'At risk', tone: 'warn', rank: 1 },
  critical: { label: 'Critical', tone: 'hot', rank: 2 }, breached: { label: 'Breached', tone: 'crit', rank: 3 },
}
export const SLA_ORDER: SlaStatus[] = ['safe', 'at_risk', 'critical', 'breached']

/** Compliance score tone. Thresholds are display bands only; the score itself always comes from the backend. */
export function scoreTone(score: number | null | undefined): Tone {
  if (score == null) return undefined
  return score >= 95 ? 'ok' : score >= 85 ? 'warn' : score >= 70 ? 'hot' : 'crit'
}

export const probPct = (p: number | null | undefined) => (p == null || !Number.isFinite(p) ? '—' : p >= 0.995 && p < 1 ? '>99%' : p > 0 && p < 0.005 ? '<1%' : `${Math.round(p * 100)}%`)
export const scoreText = (s: number | null | undefined) => (s == null || !Number.isFinite(s) ? '—' : `${s.toFixed(s % 1 === 0 ? 0 : 1)}`)

/** "3.2 min left" / "over by 1.4 min" */
export function remainingText(min: number): string {
  if (!Number.isFinite(min)) return '—'
  return min >= 0 ? `${min.toFixed(1)} min left` : `over by ${Math.abs(min).toFixed(1)} min`
}

export const rowClass = (s: SlaStatus) => `sla-row ${s}`

export function sortCustomers(rows: SlaCustomer[]): SlaCustomer[] {
  return [...rows].sort((a, b) => SLA_STATUS[b.status].rank - SLA_STATUS[a.status].rank || b.breach_probability - a.breach_probability || a.position - b.position)
}

/** Trend rows for charts. Buckets without customers keep a null score so the chart shows a gap, never a made-up value. */
export function trendRows(buckets: TrendBucket[], label: (s: number) => string) {
  return buckets.map(b => ({ t: label(b.start_s), score: b.score, breached: b.breached, served: b.served, avgWait: b.avg_wait_min, target: b.avg_target_min }))
}

export const isAtRisk = (s: SlaStatus) => s !== 'safe'
export const atRiskCount = (c: Record<SlaStatus, number> | undefined) => (c ? c.at_risk + c.critical + c.breached : 0)

export function validatePolicy(maxWait: number, atRisk: number, critical: number): string | null {
  if (!Number.isFinite(maxWait) || maxWait <= 0 || maxWait > 1440) return 'Maximum wait must be between 0 and 1440 minutes'
  if (!(atRisk > 0 && atRisk < 1) || !(critical > 0 && critical < 1)) return 'Probabilities must be between 0% and 100% (exclusive)'
  if (atRisk >= critical) return 'The “at risk” probability must be lower than the “critical” probability'
  return null
}
export const CLASS_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/
