/** Response shapes of the /sla endpoints. */
import type { Provenance } from './adaptiveTypes'

export type SlaStatus = 'safe' | 'at_risk' | 'critical' | 'breached'

export interface SlaPolicy {
  id: number; queue_id: number; service_class: string; label: string | null; max_wait_min: number
  at_risk_probability: number; critical_probability: number; updated_by: string; created_at: string; updated_at: string
}
export interface PolicyList { queue: { id: number; name: string; is_synthetic: boolean }; configured: boolean; default_class: string; policies: SlaPolicy[]; note: string }

export interface SlaCustomer {
  entry_id: number; token: number; queue_id: number; position: number; service_class: string; class_fallback: boolean
  current_wait_min: number; predicted_total_wait_min: number | null; sla_target_min: number; remaining_sla_min: number
  breach_probability: number; status: SlaStatus; completions_needed: number; basis: string; highlight: boolean
}
export interface PredictedCompliance { n: number; score: number | null; expected_breaches: number | null; kind: 'predicted'; definition: string; label?: string }
export interface SlaMonitor {
  configured: boolean; reason?: string; queue: { id: number; name: string; is_synthetic: boolean }; provenance: Provenance
  as_of?: string; as_of_basis?: string; customers: SlaCustomer[]; counts?: Record<SlaStatus, number>; waiting?: number; serving?: number
  predicted_compliance?: PredictedCompliance
  capacity?: { active_counters: number; busy_counters: number; idle_counters: number; service_capacity_per_min: number; service_rate_source: string }
  assumptions?: string[]
}

export interface Score {
  n: number; met: number; breached: number; score: number | null; interval95: [number, number] | null
  avg_wait_min: number | null; p95_wait_min: number | null; avg_target_min: number | null; avg_over_target_min: number | null
  kind: 'observed'; label: string
}
export interface ClassRow { service_class: string; label: string | null; target_min: number | null; n: number; met: number; breached: number; score: number | null; avg_wait_min: number | null; p95_wait_min: number | null }
export interface TrendBucket { start_s: number; end_s: number; served: number; met: number; breached: number; score: number | null; avg_wait_min: number | null; avg_target_min: number | null }
export interface SlaPerformance {
  configured: boolean; reason?: string; queue: { id: number; name: string; is_synthetic: boolean }; provenance: Provenance
  as_of?: string; as_of_basis?: string
  window?: { current_minutes: number; lookback_hours: number; bucket_minutes: number }
  scores?: { current: Score; historical: Score; overall: Score; predicted: PredictedCompliance | null; definition: string }
  summary?: { served: number; met_sla: number; breached_sla: number; abandoned: number; waiting_now: number | null; serving_now: number | null
    avg_wait_min: number | null; p95_wait_min: number | null; avg_target_min: number | null; avg_over_target_min: number | null }
  per_class?: ClassRow[]; trend?: TrendBucket[]; targets_note?: string
}

export interface SlaCandidate {
  key: string; label: string; type: string; rank: number; is_recommended: boolean; description: string
  expected_wait_reduction_min: { mean: number | null; ci95: number | null; pct: number | null }
  avg_wait_after_min: number; p95_wait_after_min: number; p95_within_target: boolean
  extra_cost: { total: number }; net_value: number; significant: boolean; assumptions: string[]; record_id: number | null; kind: 'simulated'
}
export interface SlaRecommendation {
  needed: boolean; message?: string; queue: { id: number; name: string; is_synthetic: boolean }; provenance: Provenance
  affected: Record<SlaStatus, number>; target_min?: number; worst_customer?: SlaCustomer; reasons?: string[]
  capacity_gap?: { for_token: number; required_capacity_per_min: number; current_capacity_per_min: number; extra_capacity_per_min: number; approx_extra_counters: number | null; method: string } | null
  baseline?: { avg_wait_min: number; p95_wait_min: number; kind: 'simulated' } | null
  candidates?: SlaCandidate[]; recommended_key?: string | null; explanation?: string | null; evaluation_id?: string | null
  persisted?: boolean; disclaimer?: string; note?: string; simulation_only: true; executed: false
  reproducibility?: { base_seed: number; replications: number; config_hash: string } | null
}
export interface SlaSummaryRow {
  queue_id: number; name: string; is_synthetic: boolean; configured: boolean; standard_target_min: number | null
  current_score?: number | null; current_n?: number; overall_score?: number | null; counts?: Record<SlaStatus, number>; predicted_score?: number | null
}
