# LineZero API Reference (Parts 1 + 2)

Base URL: `http://127.0.0.1:8000/api/v1` · Swagger UI: `/docs` · OpenAPI JSON: `/openapi.json` · Health: `GET /health`

> Example JSON below shows the **structure** returned. Numbers are illustrative, not measured output.

## Conventions
* **Timestamps**: ISO-8601, always UTC in stored data and responses (`2026-11-14T09:30:00+00:00`). Query parameters accept ISO-8601; a value without a zone is read as UTC. Analytics bucket labels can be aligned to another zone with `tz_offset_minutes` (then labels carry that offset, e.g. `+05:30`).
* **Units** (keys say which): prediction `*_s` = seconds; analytics `*_min` = minutes; optimisation `*_min` = minutes, rates = customers/minute.
* **Errors** (all endpoints): `{"error": {"code": "...", "message": "...", "details": ...}}`
  `404 not_found/queue_not_found/...` · `409 conflict-type` (e.g. `no_active_counters`, `optimization_infeasible`) · `422 validation_error` (bad body/params, `invalid_date_range`, `arrival_rate_required`...) · `501 export_unavailable` (PDF library missing) · `500 internal_error`.
* **Synthetic data**: every Part 2 response carries `is_synthetic` or `meta.contains_synthetic_data`; reports carry a `data_notice`.

---
## Part 1 (unchanged)
Queues, entries, counters, simulations: see README.md ("API" table). Part 1 had no analytics endpoints, so the Part 2 analytics routes do not replace anything.

---
## Predictions
### `GET /predictions/{queue_id}?store=true`
Predict the wait for a customer joining now. Errors: 404 unknown queue; 409 `no_active_counters`.
```json
{
  "queue_id": 2, "prediction_id": 17,
  "predicted_waiting_time_s": 480.0, "predicted_waiting_time_min": 8.0,
  "prediction_method": "statistical_baseline",
  "prediction_timestamp": "2026-11-14T09:30:00.123456+00:00",
  "baseline_waiting_time_s": 480.0,
  "input_features": {"queue_ahead": 5, "busy_counters": 3, "active_counters": 3, "avg_service_time_s": 240.0,
                     "arrival_rate_per_min": 0.9, "load_ratio": 1.2, "hour_sin": 0.5, "hour_cos": -0.8,
                     "hist_hour_mean_wait_s": 300.0, "recent_avg_wait_s": 350.0, "baseline_wait_s": 480.0},
  "queue_state": {"queue_length": 5, "active_counters": 3, "busy_counters": 3, "arrival_rate_per_min": 0.9,
                  "observed_mean_service_s": 240.0, "hour_of_day_utc": 9},
  "uncertainty": {"lower_s": 400.0, "upper_s": 560.0, "level": 0.8, "basis": "empirical quantiles of 236 out-of-sample residuals ..."},
  "assumptions": ["Prediction is for a customer who joins this queue right now ...", "..."],
  "notes": [],
  "model": {"selected": "statistical_baseline", "training": {"status": "trained", "reason": "...", "validation_metrics": {}}},
  "is_synthetic": true
}
```
* `prediction_method`: `statistical_baseline` | `linear_regression` | `random_forest`. ML is only used if it beat the baseline by ≥5 % MAE on a chronological hold-out set; otherwise the baseline is returned and `model.training.reason` says why.
* `model.training.status`: `no_history` | `insufficient_data` (<100 usable samples: **no ML model is trained**) | `trained`.
* `uncertainty` is `null` unless ≥30 out-of-sample residuals exist. It is an unconditional empirical interval, not a guarantee.
* `store=false` skips saving the record (`prediction_id` is null).

### `GET /predictions/{queue_id}/history?limit=50&offset=0`
Stored predictions with `actual_waiting_time_s`, `error_s` (predicted − actual), `absolute_error_s` once evaluated.

### `POST /predictions/evaluate`
```json
{"queue_id": 2, "mode": "stored", "prediction_ids": [17, 18],
 "actuals": [{"prediction_id": 17, "actual_waiting_time_s": 420}], "max_match_gap_seconds": 900}
```
* `mode: "stored"` (default): fills actuals (supplied `actuals`, else the first customer who joined after the prediction, within `max_match_gap_seconds`, and has started service) and returns
  `{"metrics": {"n","mae_s","rmse_s","mean_error_s","median_abs_error_s","max_abs_error_s"}, "by_method": {...}, "predictions": [...], "predictions_evaluated", "predictions_unresolved", "matching_rule", "notes"}`. With no outcomes, metrics are `null` — nothing is estimated.
* `mode: "backtest"`: replays history. Returns `backtest.training_report` (hold-out metrics per method, selection reason) and `backtest.baseline_metrics_all_history`.

---
## Bottlenecks
### `POST /bottlenecks/analyze` → 201
```json
{"queue_id": 2, "window_minutes": 240, "lookback_minutes": 1440, "as_of": null}
```
Omit `queue_id` to analyse every non-closed queue. `as_of` defaults to now (generated queues whose data is older than the window are anchored at their last activity; see `by_queue[].as_of_basis`). Every finding is stored.
```json
{"analyzed_at": "...", "window_minutes": 240, "lookback_minutes": 1440, "thresholds": {"overload_util": [0.85, 0.92, 0.97], "...": "..."},
 "queues_analyzed": 1, "detection_count": 1,
 "detections": [{
   "detection_id": 41, "bottleneck_type": "capacity_demand_imbalance", "severity": "HIGH",
   "queue_id": 2, "counter_id": null,
   "supporting_metrics": {"arrival_rate_per_min": 0.97, "service_capacity_per_min": 0.75, "demand_to_capacity_ratio": 1.3,
                          "counters_needed_for_target_utilization": 5, "thresholds": {"ratio": [0.9, 1.0, 1.15, 1.4]}},
   "explanation": "Arrivals averaged 0.97/min against a configured capacity of 0.75/min ...",
   "operational_impact": "Customers who started service in the window waited 31.2 min on average ...",
   "recommendation": "Add capacity: about 5 counters ...",
   "detection_timestamp": "2026-11-14T09:30:00+00:00", "window_start": "...", "window_end": "...", "is_synthetic": true}],
 "by_queue": [{"queue_id": 2, "as_of": "...", "as_of_basis": "now", "summary": {"arrival_rate_per_min": 0.97, "counter_utilization": {"7": 0.96}}, "notes": [], "detections": ["..."]}]}
```
Types: `counter_overload`, `uneven_utilization`, `arrival_spike`, `slow_service`, `capacity_demand_imbalance`. Severities: `LOW|MEDIUM|HIGH|CRITICAL`. `counter_id` is null for queue-level findings.

### `GET /bottlenecks?queue_id=&counter_id=&severity=&bottleneck_type=&limit=100&offset=0`
Stored detections (same item shape as above), newest first.

---
## Optimization
### `POST /optimization/run` → 201
```json
{"queue_id": 2, "arrival_rate": null, "arrival_window_minutes": 240,
 "cost_per_counter_hour": 1.0, "counter_costs_per_hour": {"7": 1.5},
 "new_counter_service_rate": 0.25, "new_counter_cost_per_hour": 1.0,
 "constraints": {"max_active_counters": 6, "min_active_counters": 1, "max_cost_per_hour": 6.0,
                 "max_counter_utilization": 0.9, "allow_new_counters": 2, "allow_policy_change": true},
 "simulation": {"duration_minutes": 480, "replications": 8, "seed": 12345, "service_distribution": "exponential"}}
```
`arrival_rate` (customers/min) is estimated from recent arrivals when null (422 `arrival_rate_required` if impossible). Only existing non-closed counters (paused ones are assumed resumable) plus up to `allow_new_counters` hypothetical ones are used. Results are **recommendations only** — nothing is applied.
Response (also `GET /optimization/{optimization_id}`):
```json
{"optimization_id": 5, "queue_id": 2, "created_at": "...",
 "current_allocation": {"assignment_policy": "lowest_index", "active_counter_count": 3, "counters": [{"counter_id": 7, "name": "Counter 1", "service_rate_per_min": 0.25, "action": "keep"}],
                        "total_service_capacity_per_min": 0.75, "cost_per_hour": 3.0, "counters_to_deactivate": []},
 "proposed_allocation": {"assignment_policy": "longest_idle", "active_counter_count": 5, "counters": [{"counter_id": null, "key": "new-1", "action": "add_new"}], "...": "..."},
 "current_metrics": {"avg_waiting_time_min": 53.5, "p95_waiting_time_min": 120.0, "avg_utilization": 0.99, "counter_utilization": {"7": 0.99}, "utilization_imbalance": 0.01, "cost_per_hour": 3.0, "demand_to_capacity_ratio": 1.33, "waits_per_rep": []},
 "proposed_metrics": {"...": "same keys"},
 "estimated_improvement": {"avg_waiting_time_min": {"current": 53.5, "proposed": 1.4, "absolute_reduction": 52.1, "percent_reduction": 97.4,
                           "paired_difference": {"mean": 52.1, "std_error": 4.0, "ci95": [41.0, 63.2], "significant": true, "replications": 8}},
                           "utilization_imbalance": {}, "cost_per_hour": {"change": 2.0}, "is_improvement": true},
 "resource_requirements": {"active_counters": 5, "counters_to_activate": [], "new_counters_required": 2, "cost_per_hour": 5.0,
                           "cost_change_per_hour": 2.0, "constraint_checks": [{"name": "max_cost_per_hour", "limit": 6.0, "value": 5.0, "ok": true}], "within_constraints": true},
 "explanation": "...", "details": {"candidates": [], "assumptions": [], "optimality": "Best among the evaluated candidates only. Global optimality is NOT claimed or proven."},
 "is_synthetic": true}
```
Errors: 409 `optimization_infeasible` (constraints cannot be met / no active counter), 409 `no_counters`, 422 `invalid_optimization_request`.

---
## Analytics
All: `GET /analytics/{overview|arrivals|waiting-times|utilization|peak-hours}`
Filters: `queue_id`, `counter_id`, `start_date`, `end_date`, `tz_offset_minutes` (default 0). `arrivals|waiting-times|utilization` also take `granularity=hour|day`; `overview` takes `compare_previous=true` (compares with the equally long period right before the range).
With `counter_id`, only customers served by that counter are included. 404 unknown queue/counter; 422 counter not in queue, `end_date < start_date`, too many buckets.
Common envelope:
```json
{"filters": {"queue_id": 2, "counter_id": null, "start_date": "...", "end_date": "...", "tz_offset_minutes": 0},
 "meta": {"empty": false, "contains_synthetic_data": true, "data_notice": "...", "timezone": "UTC+00:00", "duration_unit": "minutes", "notes": []},
 "summary": {}, "charts": {}, "tables": {}}
```
* `charts.<name>` = `{"type": "line|bar", "title", "x": {"label","type": "time|category"}, "y": {"label","unit"}, "series": [{"key","name","data": [{"x","y"}]}]}`
* `overview.summary.kpis`: `arrivals, served, abandoned, avg/median/p95/max_waiting_time_min, avg_service_time_min, throughput_per_hour, arrival_rate_per_hour, avg_utilization, avg_queue_length, max_queue_length, peak_hours`; `summary.comparison` (when requested) has per-metric `current/previous/change/change_pct/verdict`. Tables: `hourly`, `daily`, `by_counter`. Charts: `arrivals_per_hour, waiting_time_per_hour, queue_length_over_time, throughput_per_hour, daily_performance, utilization_by_counter`.
* `arrivals`: charts `arrivals_over_time, arrivals_by_hour_of_day, arrivals_by_weekday`; summary has `trend`.
* `waiting-times`: charts `waiting_time_over_time` (avg, p95), `service_time_over_time`, `waiting_time_distribution`; table `by_bucket`.
* `utilization`: charts `utilization_by_counter`, `utilization_over_time` (one series per counter); table `by_counter`. Basis: busy time ÷ elapsed time (paused time is not excluded).
* `peak-hours`: `summary.peak_hours` (hours of day), table `by_hour_of_day` with `p_value_vs_flat_demand`. An empty `peak_hours` list means no hour stands out statistically.
* Empty data → HTTP 200 with `meta.empty = true` and the same keys.

---
## Reports
| Method | Path | Notes |
|---|---|---|
| POST | `/reports/generate` → 201 | body below |
| GET | `/reports?report_type=&queue_id=&limit=&offset=` | list (no `report_data`) |
| GET | `/reports/{report_id}` | full stored JSON |
| GET | `/reports/{report_id}/export?format=csv\|json\|pdf` | file download (`Content-Disposition: attachment`) |

```json
{"report_type": "queue_performance", "queue_id": 2, "simulation_id": null, "optimization_id": null,
 "start_date": null, "end_date": null, "tz_offset_minutes": 0, "window_minutes": 240, "lookback_minutes": 1440}
```
`report_type`: `queue_performance` (queue_id) · `simulation_results` (simulation_id) · `prediction_evaluation` (queue_id) · `bottleneck_analysis` (queue_id; runs and stores a fresh analysis) · `optimization_comparison` (optimization_id).
```json
{"report_id": 3, "report_type": "queue_performance", "title": "...", "queue_id": 2, "contains_synthetic_data": true, "created_at": "...",
 "report_data": {"meta": {"generated_at": "...", "data_origin": "synthetic|simulation|recorded", "contains_synthetic_data": true, "data_notice": "SYNTHETIC DATA: ...", "parameters": {}},
                 "summary": {}, "tables": {"name": {"columns": ["a"], "rows": [[1]]}}, "details": {}}}
```
CSV = `section,key,value` rows for meta and summary followed by each table. PDF needs the `reportlab` package (501 `export_unavailable` otherwise) and shows at most 60 rows per table.

---
## Digital Twin (`/twin`)

Reads real queue state from the database; every projection is simulation (SimPy). **No twin endpoint writes to queues, counters or customers.** Errors use the same envelope as the rest of the API (`404 queue_not_found`, `409 no_active_counters`, `422 validation_error` / `invalid_twin_request`).

Time unit: minutes. Rates: customers per minute. Seeds: `replications` runs use `seed, seed+1, …`; the first run is returned for playback. Example JSON shows **structure**, not measured output.

### `TwinConfig` (request body `configuration`)
Extends the simulator's `SimulationConfig` (`arrival_rate`, `mean_service_time`, `num_counters`, `duration`, `arrival_distribution`, `service_distribution`, `abandonment_enabled`, `mean_patience`, `counter_speed_factors`, `counter_assignment`, `arrival_profile`, `seed`) with:

| Field | Meaning |
|---|---|
| `outages[]` | `{counter, start, end?, kind: "failure"\|"outage"}`; `end` omitted = down until the end. Graceful: the customer in service finishes. |
| `speed_changes[]` | `{counter?, start, end?, factor}`; `counter` omitted = all counters; `factor` 0.6 = 40% slower |
| `standby_counters[]` | Counters that start closed (reserve) |
| `staff_available` | Number of staffed counters; higher-numbered counters start closed |
| `actions[]` | Scheduled recovery: `{type: "activate_counter"\|"deactivate_counter"\|"boost_speed", at, counter?, factor?, duration?}` |
| `recovery` | Reactive policy `{enabled, queue_threshold, sustain, check_interval, cooldown, max_activations, boost_factor}` |
| `initial_queue`, `initial_busy_counters[]` | Start from a given live state |
| `cost_per_counter_hour` | Cost weight for `resource_cost` (counter-hours open × this) |
| `sample_interval`, `congestion_queue` | Playback frame spacing; queue length counted as congestion (default `max(5, 2 × counters)`) |

Counter indices are zero-based. Runs are limited to ~8,000 expected customers (422 otherwise).

### `GET /twin/status`
`{"engine": "simpy", "gemini": {"configured": false, "model": null}, "horizons_min": [5,15,30,60], "max_compare_scenarios": 5, "writes_to_real_queues": false}`. Never returns the key.

### `GET /twin/presets?arrival_rate=1.2&mean_service_time=4&num_counters=5&duration=120`
List of `{id, name, description, assumptions[], configuration}` for `normal`, `arrival_surge`, `staff_shortage`, `counter_failure`, `slow_service`, `peak_hour`. Sizes are illustrative assumptions.

### `GET /twin/live/{queue_id}`
```json
{ "queue": {"id": 1, "name": "…", "status": "active", "is_synthetic": true}, "as_of": "…",
  "counters": [{"index": 0, "id": 1, "name": "…", "status": "active", "service_rate_per_min": 0.25, "active": true, "busy": true}],
  "waiting": [{"token": 12, "position": 1, "waiting_seconds": 95.0}], "serving": [{"token": 11, "counter_id": 1, "service_elapsed_seconds": 40.0}],
  "metrics": {"queue_length": 5, "active_counters": 3, "busy_counters": 3, "idle_counters": 0, "counter_utilization_now": 1.0,
              "longest_current_wait_min": 4.2, "avg_current_wait_min": 2.1, "arrival_rate_per_min": 0.9, "arrival_rate_source": "…",
              "service_capacity_per_min": 0.75, "load_ratio": 1.2, "congestion_threshold": 6},
  "operational_status": "normal | busy | congested | no_capacity",
  "predicted_wait_now": {"waiting_time_min": 8.0, "method": "statistical_baseline"},
  "suggested_configuration": {"arrival_rate": 0.9, "mean_service_time": 4.0, "num_counters": 3, "duration": 120, "counter_speed_factors": [1,1,1], "standby_counters": []},
  "data_provenance": {"queue_and_counters": "…", "arrival_rate": "…"} }
```
`predicted_wait_now` is `null` if the prediction engine cannot answer (e.g. no active counters). `arrival_rate_per_min` may be `null` with too little history.

### `GET /twin/forecast/{queue_id}?replications=30&seed=2026&arrival_rate=`
5/15/30/60-minute forecast from the live state. `arrival_rate` overrides the estimated rate (`arrival_rate_source: "user_override"`). 409 `no_active_counters` if no counter is active.
```json
{ "method": "replicated_simpy_from_live_state", "replications": 30,
  "horizons": [{"horizon_min": 5, "queue_length": {"mean": 0, "p10": 0, "p90": 0}, "waiting_time_min": {…}, "arrivals_since_now": {…},
                "counter_utilization": {…}, "congestion": {"probability": 0.0, "risk": "low|moderate|high", "threshold_queue": 6, "definition": "…"}}, …],
  "starting_state": {"queue_length": 5, "active_counters": 3, "busy_counters": 3, "arrival_rate_per_min": 0.9, "arrival_rate_source": "…", "service_capacity_per_min": 0.75, "load_ratio": 1.2},
  "assumptions": ["…"], "notes": {"arrival_rate_floored": false, "queue_truncated": false},
  "current_prediction": {"waiting_time_min": 8.0, "method": "…"}, "data_provenance": {"…": "…"} }
```
`p10`/`p90` are percentiles across simulation replications, not a validated prediction interval.

### `POST /twin/simulate`
`{"configuration": TwinConfig, "replications": 5, "seed": 2026}` (replications 1-20). Returns `stats` (per metric `mean, std, ci95, min, max, n`), `summary` (means), per-counter aggregates, `per_replication`, and `playback` for the first seed:
`frames[]` (`t, queue, in_service, arrivals, served, abandoned, longest_wait, counters[]` with 0 idle, 1 busy, 2 failed, 3 closed), `customers[]` (`[id, arrival, service_start, service_end, counter, abandon_time]`), `events[]` (`counter_failure`, `counter_repaired`, `recovery_trigger`, `recovery_action`), `episodes` (`formation[]`, `bottlenecks[]` with most-loaded counter) and the run's own metrics. Metrics: `avg_waiting_time`, `p95_waiting_time` (includes customers still waiting at the end), `max_queue_length`, `total_served`, `abandoned`, `abandonment_rate`, `avg_utilization_available` (while open), `resource_cost`.

### `POST /twin/compare`
`{"scenarios": [{"name": "Baseline", "configuration": {…}}, …], "replications": 8, "seed": 2026}`; 2-5 scenarios, first is the baseline, all on the same seeds. Returns `metrics{metric: {values, ci95, delta, pct, best_index, paired[]}}` and `improvements[]` (before/after per metric with `paired {mean_diff, ci95, significant}`).

### `POST /twin/recommend`
`{"configuration": {…}, "replications": 6, "seed": 2026, "max_extra_cost": null}` (replications 2-20). Returns `diagnosis`, `recommendations[]` (ranked; each has `actions`, `improvement` before/after, `score`, `significant`, `extra_cost`, `assumptions`), `recommended_id` (null if nothing clearly helps), `score_formula`, `simulation_only: true`.

### `POST /twin/recover`
Same request. Searches reactive recovery policies; returns `chosen` policy, `before_after`, `candidates[]`, and playback payloads `baseline.primary` and `recovered.primary`. `chosen` is `null` (with `notes`) if no policy clearly beats doing nothing.

### `POST /twin/explain`
`{"kind": "congestion|counter|intervention|scenarios", "configuration": {…} | "scenarios": […], "replications": 6, "seed": 2026, "question": null}`. The server recomputes the facts; the client cannot supply them. Returns `text`, `source` (`gemini` or `deterministic`), `deterministic_text`, `facts`, and `gemini {configured, used, model, rejected_reason, error}`. If Gemini's answer contains a number that is not in `facts`, it is discarded and `rejected_reason` explains.

---

## Adaptive intelligence (LineZero 2.0)

All routes are under `/api/v1`. Errors use the common envelope `{"error": {"code", "message", "details"}}`. Every response carries a `provenance` block (`observed_real_data` / `synthetic_demo_data`, a notice for synthetic queues, and a legend of data kinds). Methods and formulas: [ADAPTIVE_INTELLIGENCE.md](ADAPTIVE_INTELLIGENCE.md).

### Calibration (`/calibration/{queue_id}`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Active version, data sufficiency, nominal parameters, drift summary. |
| POST | `/run` | Fit on the earlier customers, validate on the latest, accept only if validation MAE improves. Body: `validation_fraction`, `min_improvement_pct`, `prior_arrival_minutes`, `prior_service_pseudo_n`, `lookback_minutes`, `dry_run`. Rejected candidates are stored without a version; `dry_run` stores nothing. |
| GET | `/versions` | All versions, newest first (`include_rejected=true`). |
| POST | `/rollback` | `{version, reason, operator}`: restores an old version's parameters as a **new** active version. |
| GET | `/drift` | Arrival-rate, service-time and waiting-time drift between the reference and recent windows. |
| GET / POST | `/evaluation` | Predicted vs actual waits (`scope=new_data` is out-of-sample; `all` is flagged in-sample). POST stores the snapshot. |
| GET | `/error-history` | Stored evaluation snapshots. |

### Risk (`/risk`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/{queue_id}/assess` | Score the 7 categories now. Stores nothing. Query: `wait_sla_min`, `forecast_replications`, `seed`. |
| POST | `/{queue_id}/scan` | Assess and store/refresh risk events; events no longer detected are resolved. Body: `persist`, `forecast_replications`, `seed`, `wait_sla_min`. |
| GET | `/{queue_id}/events` | Stored events (`status=open|resolved|all`). |
| POST | `/events/{event_id}/resolve` | `{operator, note}`. |

### Interventions (`/interventions`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/{queue_id}/evaluate` | Simulate baseline and candidates (common random numbers), price and rank them. Body: `horizon_min` (10-240), `replications` (3-20), `seed`, `risk_event_id`, `cost_model`, `persist`, `use_calibration`. Always `simulation_only: true`, `executed: false`. 409 `no_active_counters`. |
| GET | `/{queue_id}/history` | Stored candidates (`status` filter). |
| GET | `/item/{id}` | One record with baseline, expected result, assumptions and `simulation_meta` (`config_hash`, seeds). |
| POST | `/item/{id}/approve` · `/reject` | `{operator, note}`. Changes nothing in the queue. 409 `invalid_transition` / `another_candidate_in_force`. |
| POST | `/item/{id}/applied` | `{operator, note, applied_at}`: the operator confirms they carried it out. Requires prior approval; not in the future. |
| POST | `/item/{id}/outcome` | `{mode: observe|manual, window_minutes, observed, operator, note}`. `observe` measures before/after windows (409 `outcome_window_not_elapsed` / `outcome_insufficient_data`); `manual` stores operator-reported figures. Returns a `verification` label. |
| GET | `/{queue_id}/learning` | Expected vs observed statistics, kept apart by verification label, plus advisory recalibration signal. |

### Operations loop (`/operations`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/{queue_id}/overview` | Counts for each loop stage. |
| POST | `/{queue_id}/cycle` | Runs only the automatic stages (recalibrate, scan risks, simulate interventions). Never approves or applies. |

Existing `GET /twin/live/{queue_id}` additionally returns `active_calibration` (additive; nothing else changed).
