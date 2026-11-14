export interface ApiQueue { id: number; name: string; status: string; is_synthetic: boolean; scenario: string | null; waiting_count: number; serving_count: number; counter_count: number }

export interface ChartPoint { x: string | number; y: number | null }
export interface ApiChart {
  type: 'line' | 'bar'
  title: string
  x: { label: string; type: 'time' | 'category' }
  y: { label: string; unit?: string }
  series: { key: string; name: string; data: ChartPoint[] }[]
}
export interface Analytics {
  filters: Record<string, unknown>
  meta: { empty: boolean; contains_synthetic_data: boolean; data_notice?: string; notes: string[] }
  summary: Record<string, any>
  charts: Record<string, ApiChart>
  tables: Record<string, Record<string, any>[]>
}

export interface SimResults {
  seed_used: number; duration: number; num_counters: number
  total_arrivals: number; total_served: number; abandoned: number; abandonment_rate: number
  customers_remaining: number
  avg_waiting_time: number; max_waiting_time: number; p50_waiting_time: number; p95_waiting_time: number
  avg_queue_length: number; max_queue_length: number; avg_service_time: number; avg_utilization: number; throughput: number
  counters: { counter_index: number; speed_factor: number; served: number; busy_time: number; utilization: number }[]
  theoretical?: { applicable: boolean; model?: string; note?: string; stable?: boolean; utilization?: number; avg_waiting_time?: number; avg_queue_length?: number }
}
export interface SimRun { id: number; name: string | null; status: string; configuration: Record<string, any>; results: SimResults | null; seed: number | null; runtime_ms: number | null; comparison_id: string | null; created_at: string }
export interface SimCompare { comparison_id: string; runs: SimRun[]; comparison: Record<string, any> }

export interface Detection {
  detection_id: number; bottleneck_type: string; severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'; queue_id: number; counter_id: number | null
  supporting_metrics: Record<string, any>; explanation: string; operational_impact: string; recommendation: string; detection_timestamp: string; is_synthetic: boolean
}
export interface BottleneckResult { analyzed_at: string; window_minutes: number; queues_analyzed: number; detection_count: number; detections: Detection[]; by_queue: { queue_id: number; as_of_basis: string; notes: string[] }[] }

export interface Allocation { assignment_policy: string; active_counter_count: number; counters: { counter_id: number | null; key: string; name?: string; service_rate_per_min: number; action: string }[]; total_service_capacity_per_min: number; cost_per_hour: number }
export interface OptMetrics { avg_waiting_time_min: number; p95_waiting_time_min: number; avg_utilization: number; utilization_imbalance: number; cost_per_hour: number; demand_to_capacity_ratio: number; avg_queue_length: number }
export interface Optimization {
  optimization_id: number; queue_id: number; created_at: string
  current_allocation: Allocation; proposed_allocation: Allocation; current_metrics: OptMetrics; proposed_metrics: OptMetrics
  estimated_improvement: { avg_waiting_time_min: { current: number; proposed: number; absolute_reduction: number; percent_reduction: number; paired_difference: { significant: boolean; ci95: [number, number] } }; is_improvement: boolean }
  resource_requirements: { active_counters: number; new_counters_required: number; cost_per_hour: number; cost_change_per_hour: number; within_constraints: boolean; constraint_checks: { name: string; ok: boolean }[] }
  explanation: string
  details: { optimality: string; assumptions: string[]; candidates_evaluated: number }
  is_synthetic: boolean
}

export interface Prediction {
  queue_id: number; predicted_waiting_time_min: number; prediction_method: string
  uncertainty: { lower_s: number; upper_s: number; level: number } | null
  queue_state: { queue_length: number; active_counters: number; busy_counters: number }
  assumptions: string[]; notes: string[]; is_synthetic: boolean
}

export interface ReportSummary { report_id: number; report_type: string; title: string | null; queue_id: number | null; contains_synthetic_data: boolean; created_at: string }
export interface ReportFull extends ReportSummary { report_data: { meta: { data_notice?: string; data_origin?: string }; summary: Record<string, any>; tables: Record<string, { columns: string[]; rows: any[][] }> } }
