# SLA & Customer Experience Intelligence

Server mode only. Predicts service-level breaches for customers who are waiting, measures compliance for customers already served, and recommends actions that are validated by the existing simulation and intervention engines. **LineZero never executes an action; operators approve and carry it out.**

## Configuration
- `sla_policies` (migration `0004`): one row per queue and service class with `max_wait_min` (0 to 1440), `at_risk_probability` and `critical_probability` (`0 < at_risk < critical < 1`, defaults 0.25 / 0.6), `updated_by`.
- The `standard` class is required first and applies to customers without a class. **No target is assumed**: until one is set, the module reports "not configured" and predicts nothing.
- Queues have no "type" in LineZero, so targets are per queue. Customers had no priority, so a nullable `queue_entries.service_class` was added (optional body on `POST /queues/{id}/entries`; a class must have a policy). A class changes the target only, not the service order.

## Breach probability
For a waiting customer with `ahead` customers in front and `idle` idle counters, `k = max(ahead + 1 - idle, 0)` completions are needed (the same quantity as `prediction_engine.baseline_wait`). With the sum of active counter rates `mu` (calibrated rates when an active calibration exists), the exact tail is

`P(breach) = P(Poisson(mu * (target - elapsed) / 60) <= k - 1)`

and the expected remaining wait is `k / mu * 60`, identical to the prediction engine. Status: **Breached** if elapsed >= target; **Critical** if p >= critical threshold; **At risk** if p >= at-risk threshold; else **Safe**. With no active counter p = 1.0 and no predicted wait is shown.
Assumptions (listed in every response): FIFO order, constant service rates, memoryless service, counters keep their state.

## Compliance score
`100 * served within target / completed`, with a Wilson 95% interval; `null` when nothing was completed (never 0). Abandoned customers are excluded and reported separately.
- **Current**: last `window_minutes` (default 60). **Historical**: earlier within `lookback_hours` (default 24). **Overall**: the whole lookback. All are measured.
- **Predicted** (kind: predicted): mean of `1 - p` over customers waiting now. A model estimate, never a measurement.
- Trend buckets without customers stay empty (null); nothing is interpolated. History is evaluated against the **current** targets.
- Anchor time: wall clock for live queues, the latest recorded activity for synthetic queues (labelled).

## Recommendations
`POST /sla/{q}/recommendations` finds the affected queue and customers, explains why, computes the capacity gap (service rate needed for the worst at-risk customer to reach p <= 0.5), and runs `InterventionService.evaluate` (common random numbers, same cost model and config hash). Expected wait reduction and the simulated P95 versus the tightest at-risk target come from that simulation. `persist=false` by default; `persist=true` stores proposals in the existing approval workflow (**Autonomous Interventions**).

## API (`/api/v1/sla`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/summary` | per-queue score, status counts, predicted score |
| GET | `/{q}/policies` | targets |
| PUT | `/{q}/policies/{class}` | create or update a target (operator required) |
| DELETE | `/{q}/policies/{class}?operator=` | remove (`standard` only when no other class exists) |
| POST | `/{q}/entries/{entry_id}/class` | set the class of a waiting customer |
| GET | `/{q}/monitor` | live customers, probabilities, statuses, predicted compliance |
| GET | `/{q}/performance?window_minutes&lookback_hours&bucket_minutes` | scores, KPIs, trend, classes |
| POST | `/{q}/recommendations` | simulated, validated recommendations |

Errors use the standard envelope with codes such as `sla_not_configured`, `invalid_window`, `invalid_service_class`, `standard_class_required`, `policy_not_found`, `operator_required`, `unknown_service_class`.

## Limitations
Constant rates and memoryless service are approximations; a customer's real service time is unknown in advance. Few completed customers give a wide Wilson interval, which is shown. Predictions say nothing about demand changes. Priority classes do not reorder the queue.
