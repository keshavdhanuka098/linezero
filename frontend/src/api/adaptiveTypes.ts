/** Response shapes of the adaptive-intelligence endpoints (calibration, risk, interventions, operations). */
export type DataKind = 'observed' | 'synthetic' | 'simulated' | 'predicted' | 'explanation' | 'configured'
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface Provenance {
  observations: 'observed_real_data' | 'synthetic_demo_data'
  is_synthetic: boolean
  notice: string | null
  legend: Partial<Record<DataKind, string>>
  explanations: string
}

export interface Metrics { n: number; mae_s: number; rmse_s: number; mean_error_s: number; mape_pct: number | null; mape_n: number }
export interface CalParams { arrival_rate_per_min: number | null; service_rate_per_min: number; counter_service_rates: Record<string, number>; source: string }
export interface CalRecord {
  id: number; version: number | null; status: 'active' | 'superseded' | 'rejected'; source: string; decision: string; reason: string
  parameters: CalParams; confidence: number | null; created_at: string; is_synthetic: boolean
  incumbent_version: number | null; rollback_to_version: number | null
  n_train_services: number | null; n_validation: number | null
  candidate_metrics: Metrics | null; incumbent_metrics: Metrics | null; mae_improvement_pct: number | null
}
export interface DriftSignal {
  status: 'ok' | 'insufficient_data'; p_value?: number; effect?: number; drifted?: boolean; direction?: string | null
  reference_mean?: number; recent_mean?: number; reference_rate_per_min?: number; recent_rate_per_min?: number
  n_reference?: number; n_recent?: number; test?: string
}
export interface Drift {
  status: string; drift_detected: boolean; severity: string | null; drifted_signals: string[]
  signals?: Record<'arrival_rate' | 'service_time' | 'waiting_time', DriftSignal>; rule?: string
}
export interface CalStatus {
  queue: { id: number; name: string; is_synthetic: boolean }; provenance: Provenance
  observations: { rows: number; served: number; needed_for_calibration: number; ready: boolean }
  nominal_parameters: CalParams; active: CalRecord | null; model: string; versions: number; rejected_candidates: number
  drift: Drift
}
export interface CalRun {
  decision: string; reasons: string[]; persisted: boolean; dry_run?: boolean; provenance: Provenance
  result: { candidate_metrics: Metrics; incumbent_metrics: Metrics; mae_improvement_pct: number | null; confidence: { value: number }; incumbent_label: string; n_validation: number } | null
  record: CalRecord | null
}
export interface CalEvaluation {
  provenance: Provenance; scope: string; active_version: number | null; n: number; out_of_sample: boolean; notes: string[]
  calibrated: Metrics | null; nominal: Metrics | null; series: { t: number; actual_min: number; predicted_min: number }[]
}

export interface RiskAssessment {
  category: string; label: string; resource_type: string; resource_id: number | null; resource_name: string
  score: number; severity: Severity | null; components: Record<string, number>; score_formula: string
  time_to_impact_min: number | null; supporting_metrics: Record<string, unknown>; confidence: number | null
  explanation: string; recommended_intervention: { type?: string; label?: string; text?: string } | null; status: string
}
export interface RiskRadarItem { label: string; score: number; severity: Severity | null; resource: string; status: string }
export interface RiskResult {
  provenance: Provenance; assessments: RiskAssessment[]; events: RiskAssessment[]; radar: Record<string, RiskRadarItem>
  overall_score: number; overall_severity: Severity | null; bands: Record<Severity, number>; utilization_caveat?: string
  snapshot: { queue_length: number; serving: number; longest_wait_min: number; active_counters: number; reserve_counters: number; load_ratio: number; capacity_per_min: number }
  service_rate_source: string; forecast_used: boolean; persisted: boolean
  persisted_events: (RiskAssessment & { id: number; detected_at: string; status: string })[]
}
export interface RiskEventRow extends RiskAssessment { id: number; detected_at: string; last_seen_at: string; resolved_at: string | null }

export interface CostModel { counter_hour_cost: number; assist_staff_hour_cost: number; diversion_cost_per_customer: number; max_extra_cost: number | null; max_assist_staff: number; cost_weight: number }
export interface Candidate {
  key: string; type: string; label: string; description: string; assumptions: string[]; feasible: boolean; infeasible_reason: string | null
  score: number; net_value: number; significant: boolean; improves: boolean; rank: number | null; is_recommended: boolean
  extra_cost: { total: number; counter_hours: number; assisting_staff: number; diversion: number }
  wait_reduction_min: { mean: number | null; ci95: number | null; pct: number | null }
  p95_wait_reduction_min: number; summary: { avg_waiting_time: number; p95_waiting_time: number; abandoned: number }
  confidence: { value: number | null }; record_id: number | null
}
export interface Evaluation {
  simulation_only: true; executed: false; requires_operator_approval: true; provenance: Provenance
  baseline: { score: number; summary: { avg_waiting_time: number; p95_waiting_time: number; max_queue_length: number }; starting_state: { queue_length: number } }
  candidates: Candidate[]; not_evaluated: { key?: string; label?: string; reason: string }[]; recommended_key: string | null
  explanation: string; global_assumptions: string[]; disclaimer: string; ranking_rule: string; score_formula: string
  reproducibility: { base_seed: number; replications: number; config_hash: string; common_random_numbers: boolean }
  inputs: { service_rate_source: string; arrival_rate_source: string; calibration_version: number | null }
  evaluation_id: string | null; persisted: boolean; horizon_min: number
}

export type IvStatus = 'proposed' | 'approved' | 'rejected' | 'applied' | 'evaluated'
export type Verification = 'verified_real_observation' | 'synthetic_observation' | 'operator_reported'
export interface OutcomeWindow { customers_served: number; avg_wait_min: number | null; p95_wait_min: number | null; throughput_per_min: number; arrival_rate_per_min: number; abandonment_rate: number | null }
export interface Outcome {
  mode: 'observe' | 'manual'; status: string; caveats: string[]; verification: Verification; recorded_by: string; note?: string | null
  observed_wait_reduction_min?: number; pre?: OutcomeWindow; post?: OutcomeWindow; confounders?: string[]
  reduction_interval95?: { low: number; high: number } | null; calibration_eligible: boolean
  comparison?: { expected_wait_reduction_min: number | null; error_min: number | null; verdict: string }
  reported?: { avg_wait_min: number }
}
export interface Intervention {
  id: number; queue_id: number; evaluation_id: string; created_at: string; intervention_type: string; label: string
  rank: number; is_recommended: boolean; status: IvStatus; is_synthetic: boolean; decided_by: string | null; applied_by: string | null
  applied_at: string | null; outcome_recorded_at: string | null; executed_by_linezero: false; outcome_verification: Verification | null; calibration_eligible: boolean
  expected: { wait_reduction_min?: { mean: number | null }; extra_cost?: { total: number } } | null; outcome: Outcome | null; result_kind: string
}
export interface LearningStats { n: number; mean_error_min?: number; mean_abs_error_min?: number; over_optimistic?: number; under_optimistic?: number; as_expected?: number }
export interface Learning {
  provenance: Provenance; status_counts: Record<IvStatus, number>; note: string
  summary: { counts: Record<Verification, number>; verified_real: LearningStats; by_type: Record<string, LearningStats>; synthetic: LearningStats; operator_reported: LearningStats }
  advice: { recalibrate: boolean; reason: string }; calibration_eligible_outcomes: number; outcomes: Intervention[]
}
export interface LoopStage { stage: string; label: string; metric: number | null; unit: string; attention?: boolean }
export interface Overview { provenance: Provenance; stages: LoopStage[]; model: string; open_risks: number; automation: string }
export interface CycleResult { steps: { step: string; skipped?: boolean; reason?: string; [k: string]: unknown }[]; note: string; executed: false; overview: Overview }
