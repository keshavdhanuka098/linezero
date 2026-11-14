# LineZero Frontend Integration Guide

Everything is plain HTTP + JSON. The bundled React app (`../frontend`) uses these endpoints through `src/api/client.ts`; any other client can do the same.

## Base URL & CORS
* API base: `http://127.0.0.1:8000/api/v1` (host/port from `API_HOST` / `API_PORT`).
* CORS: allowed origins come from `CORS_ORIGINS` in `.env` (default `http://localhost:3000,http://localhost:5173`, i.e. Create-React-App/Next and Vite). Add your origin as a comma-separated entry or JSON list, then restart the server. All methods/headers are allowed; credentials are allowed (so `*` is not used).
* If the browser reports a CORS error but the response is a 500, the real problem is on the server — check the uvicorn console.

## Data formats
* JSON in/out; send `Content-Type: application/json`.
* Dates: ISO-8601 with offset, parse with `new Date(str)`. Send filters like `start_date=2026-11-02T00:00:00Z` (URL-encode `+` as `%2B` — `URLSearchParams` does it for you).
* Durations: `_s` seconds (predictions), `_min` minutes (analytics, optimisation). Utilisation is a fraction 0–1.
* Ids are integers. Nullable fields are explicit `null`.
* Errors always `{error: {code, message, details}}`; branch on `code`, show `message`.

## Fetch helper
```js
const API = "http://127.0.0.1:8000/api/v1";

async function api(path, { method = "GET", body, params } = {}) {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null)) : "";
  const res = await fetch(API + path + qs, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.blob();
  if (!res.ok) throw Object.assign(new Error(data.error?.message ?? res.statusText), { status: res.status, error: data.error });
  return data;
}
```

## Examples
```js
// Prediction for a queue (seconds)
const p = await api(`/predictions/${queueId}`);
console.log(p.predicted_waiting_time_min, p.prediction_method, p.uncertainty /* may be null */, p.assumptions);

// Evaluate stored predictions / backtest
await api("/predictions/evaluate", { method: "POST", body: { queue_id: queueId, mode: "backtest" } });

// Bottlenecks
const found = await api("/bottlenecks/analyze", { method: "POST", body: { queue_id: queueId, window_minutes: 240 } });
found.detections.forEach(d => console.log(d.severity, d.bottleneck_type, d.explanation, d.recommendation));
const stored = await api("/bottlenecks", { params: { queue_id: queueId, severity: "HIGH" } });

// Optimisation (can take a few seconds: it runs simulations synchronously)
const o = await api("/optimization/run", { method: "POST", body: {
  queue_id: queueId, constraints: { max_active_counters: 6, allow_new_counters: 1 },
  simulation: { duration_minutes: 480, replications: 8 } } });
const saved = await api(`/optimization/${o.optimization_id}`);

// Analytics (chart-ready)
const a = await api("/analytics/arrivals", { params: { queue_id: queueId, granularity: "hour", tz_offset_minutes: 330 } });
const chart = a.charts.arrivals_over_time;           // {type, title, x, y, series:[{key,name,data:[{x,y}]}]}
const overview = await api("/analytics/overview", { params: { queue_id: queueId, compare_previous: true } });

// Reports
const rep = await api("/reports/generate", { method: "POST", body: { report_type: "queue_performance", queue_id: queueId } });
const csvBlob = await api(`/reports/${rep.report_id}/export`, { params: { format: "csv" } });
const url = URL.createObjectURL(csvBlob);            // then <a href={url} download="report.csv">
```

## Mapping a chart to any chart library
Every chart is `{type, title, x:{label,type}, y:{label,unit}, series:[{key,name,data:[{x,y}]}]}`.
For a library that wants one row per x: `const rows = {}; for (const s of chart.series) for (const p of s.data) (rows[p.x] ??= {x: p.x})[s.key] = p.y;` → `Object.values(rows)`. `y` can be `null` (no data in that bucket): render a gap, not zero. `x.type === "time"` values are ISO strings; `"category"` values are labels/hours.

## Response structures to rely on
* Prediction: `predicted_waiting_time_s|min, prediction_method, prediction_timestamp, input_features, assumptions, uncertainty|null, notes, model.training`.
* Bottleneck: `detection_id, bottleneck_type, severity (LOW|MEDIUM|HIGH|CRITICAL), queue_id, counter_id|null, supporting_metrics, explanation, operational_impact, recommendation, detection_timestamp`.
* Optimization: `current_allocation, proposed_allocation, current_metrics, proposed_metrics, estimated_improvement, resource_requirements, explanation, details`. Show `details.optimality` and `estimated_improvement.avg_waiting_time_min.paired_difference.significant` so users see the uncertainty. If `estimated_improvement.is_improvement` is false the proposal equals the current allocation.
* Analytics: envelope `{filters, meta, summary, charts, tables}`; check `meta.empty` before rendering and show `meta.data_notice` when `meta.contains_synthetic_data` is true.

## Simulation configuration (Part 1, used for what-if screens)
`POST /simulations/run` with `{name, configuration: {arrival_rate, mean_service_time, num_counters, duration, seed, arrival_distribution, service_distribution, abandonment_enabled, mean_patience, counter_speed_factors, counter_assignment, arrival_profile}}`; see README for field meanings. Time unit = minutes. `POST /simulations/compare` runs 2–10 configurations with a shared seed.

## Practical notes
* Optimisation and report generation are synchronous; show a spinner and allow ~5–30 s for large settings.
* Predictions are stored on every call by default; pass `store=false` for polling (e.g. a live dashboard widget).
* Use `GET /queues?synthetic=true` to find generated demo queues; label synthetic data in the UI.
* Interactive docs for exact schemas: `/docs`.
