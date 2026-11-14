/** Types for the Digital Twin API (`/api/v1/twin/*`). Mirrors backend/app/engines/twin_*.py output. */

export type CounterState = 0 | 1 | 2 | 3 // idle, busy, failed, closed
export interface TwinFrame { t: number; queue: number; in_service: number; arrivals: number; served: number; abandoned: number; longest_wait: number; counters: CounterState[] }
/** [id, arrival, serviceStart, serviceEnd, counterIndex, abandonTime] */
export type TwinCustomer = [number, number, number | null, number | null, number | null, number | null]
export interface TwinEvent { t: number; type: string; counter?: number; action?: string; factor?: number; source?: string; applied?: boolean; note?: string | null; queue?: number; threshold?: number; scheduled_end?: number | null }
export interface Bottleneck { start: number; end: number; peak_queue: number; most_loaded_counter: number; most_loaded_utilization: number; failed_counters: number[]; closed_counters: number[]; avg_counters_available: number | null; threshold: number }
export interface Episodes { formation: { start: number; end: number; peak_queue: number }[]; bottlenecks: Bottleneck[]; congestion_threshold: number; formation_threshold: number }

export interface Stat { mean: number; std: number | null; ci95: number | null; min: number; max: number; n: number }
export interface CounterAgg { counter_index: number; name: string; utilization_available: number; served: number; closed_time: number; failed_time: number }
export type Summary = Record<string, number>

export interface Playback {
  seed_used: number; duration: number; num_counters: number
  frames: TwinFrame[]; customers: TwinCustomer[]; events: TwinEvent[]; episodes: Episodes
  summary: Summary; total_arrivals: number; total_served: number; abandoned: number
}
export interface SimulateResponse { replications: number; base_seed: number; stats: Record<string, Stat>; summary: Summary; counters: CounterAgg[]; per_replication: Summary[]; playback: Playback }

export interface Paired { mean_diff: number; ci95: number; significant: boolean; n: number }
export interface MetricBlock { label: string; better: 'lower' | 'higher' | null; values: number[]; ci95: (number | null)[]; delta: number[]; pct: (number | null)[]; best_index: number | null; paired: (Paired | null)[] }
export interface Improvement { label: string; before: number; after: number; delta: number; pct: number | null; better: 'lower' | 'higher' | null; paired: Paired | null; significant: boolean; improved: boolean | null }
export type ImprovementSet = Record<string, Improvement>
export interface CompareResponse { labels: string[]; baseline_index: number; replications: number; base_seed: number; scenarios: { name: string; summary: Summary; stats: Record<string, Stat>; counters: CounterAgg[] }[]; metrics: Record<string, MetricBlock>; improvements: { scenario: string; vs: string; metrics: ImprovementSet }[]; method: string }

export interface TwinAction { type: 'activate_counter' | 'deactivate_counter' | 'boost_speed'; at: number; counter?: number | null; factor?: number | null; duration?: number | null }
export interface Recommendation { rank: number; id: string; type: string; label: string; description: string; actions: TwinAction[]; patch: Record<string, unknown>; assumptions: string[]; score: number; score_delta: number; significant: boolean; improves: boolean; extra_cost: number; within_budget: boolean; improvement: ImprovementSet; summary: Summary }
export interface Diagnosis { first_congestion_at: number | null; most_loaded_counter: { index: number; name: string; utilization_while_open: number } | null; underused_counters: string[]; closed_counters: string[]; failed_counters: string[]; base_load_ratio: number | null; base_load_ratio_note: string; avg_wait_min: number; p95_wait_min: number; max_queue: number; bottleneck_episodes: Bottleneck[] }
export interface RecommendResponse { mode: 'assisted'; simulation_only: true; replications: number; apply_at: number; score_formula: string; baseline_score: number; baseline: { summary: Summary }; diagnosis: Diagnosis; recommendations: Recommendation[]; recommended_id: string | null; notes: string[]; disclaimer: string }
export interface RecoveryPolicy { enabled: boolean; queue_threshold: number; sustain: number; check_interval: number; cooldown: number; max_activations: number; boost_factor: number }
export interface RecoverResponse { mode: 'automatic'; simulation_only: true; replications: number; score_formula: string; baseline_score: number; policies_evaluated: number; candidates: { policy: RecoveryPolicy; score: number; score_delta: number; significant: boolean; extra_cost: number; within_budget: boolean; summary: Summary }[]; baseline: { summary: Summary; primary: Playback }; chosen: { policy: RecoveryPolicy; score: number; score_delta: number; extra_cost: number } | null; recovered: { summary: Summary; stats: Record<string, Stat>; primary: Playback } | null; before_after: ImprovementSet | null; notes: string[]; disclaimer: string }

export interface ForecastStat { mean: number; p10: number; p90: number }
export interface ForecastHorizon { horizon_min: number; queue_length: ForecastStat; waiting_time_min: ForecastStat; arrivals_since_now: ForecastStat; counter_utilization: ForecastStat; congestion: { probability: number; risk: 'low' | 'moderate' | 'high'; threshold_queue: number; definition: string } }
export interface ForecastResponse { method: string; replications: number; horizons: ForecastHorizon[]; starting_state: { queue_length: number; active_counters: number; busy_counters: number; arrival_rate_per_min: number; arrival_rate_source: string | null; service_capacity_per_min: number; load_ratio: number | null }; assumptions: string[]; notes: { arrival_rate_floored: boolean; queue_truncated: boolean }; current_prediction: { waiting_time_min: number; method: string } | null; data_provenance: Record<string, string> }

export interface LiveCounter { index: number; id: number; name: string; status: string; service_rate_per_min: number; active: boolean; busy: boolean }
export interface TwinConfigJson { arrival_rate: number; mean_service_time: number; num_counters: number; duration: number; [k: string]: unknown }
export interface LiveResponse {
  queue: { id: number; name: string; status: string; is_synthetic: boolean }; as_of: string
  counters: LiveCounter[]; waiting: { token: number; position: number | null; waiting_seconds: number | null }[]
  serving: { token: number; counter_id: number | null; service_elapsed_seconds: number | null }[]
  metrics: { queue_length: number; serving: number; completed_total: number; abandoned_total: number; active_counters: number; busy_counters: number; idle_counters: number; counter_utilization_now: number | null; longest_current_wait_min: number; avg_current_wait_min: number; arrival_rate_per_min: number | null; arrival_rate_source: string; service_capacity_per_min: number; load_ratio: number | null; congestion_threshold: number }
  operational_status: 'normal' | 'busy' | 'congested' | 'no_capacity'
  predicted_wait_now: { waiting_time_min: number; method: string } | null
  suggested_configuration: (TwinConfigJson & { arrival_rate_is_estimated_from_data: boolean }) | null
  data_provenance: Record<string, string>
}

export interface Preset { id: string; name: string; description: string; assumptions: string[]; configuration: TwinConfigJson }
export interface ExplainResponse { kind: string; text: string; source: 'gemini' | 'deterministic'; deterministic_text: string; facts: unknown; gemini: { configured: boolean; used: boolean; model: string | null; rejected_reason: string | null; error: string | null } }
export interface TwinStatus { engine: string; gemini: { configured: boolean; model: string | null }; horizons_min: number[]; max_compare_scenarios: number; writes_to_real_queues: boolean }
