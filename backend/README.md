# LineZero Backend — Parts 1 + 2

Standalone FastAPI backend for LineZero: queue management, a SimPy discrete-event simulation engine, a synthetic
data generator, and (Part 2) waiting-time prediction, bottleneck detection, resource optimisation, analytics and
reports. The React frontend lives in `../frontend`. See **../docs/API_REFERENCE.md** and **../docs/FRONTEND_INTEGRATION.md**.

## Part 2 at a glance
| Module | What it does | Honest limits |
|---|---|---|
| `engines/prediction_engine.py` | Transparent baseline `wait = max(L+1-idle,0)/capacity`, optional Linear Regression / Random Forest. ML trains only with >=100 usable historical samples, is judged on a chronological hold-out set, and is used only if it beats the baseline by >=5% MAE. Reports MAE, RMSE, signed error. | An untrained model is never reported as trained; intervals appear only with >=30 out-of-sample residuals. Models are cached in memory per queue history. |
| `engines/bottleneck_engine.py` | Five rules (overload, uneven utilisation, arrival spike, slow service, capacity-demand imbalance) with severities and the measured evidence behind each. Spikes use a Bonferroni-corrected Poisson test; slow service a Welch-style z-test. | Statistical power depends on sample size. On simulated data (240-min window, ~17 services) the slow-counter rule found a 3x slower counter in ~70% of runs and falsely flagged equal counters in ~2-3%; widen `window_minutes` for more power. Utilisation does not exclude paused time. |
| `engines/optimization_engine.py` | Searches "k fastest counters x assignment policy" candidates, simulates each (SimPy, common random numbers, replications), scores wait + imbalance + cost, validates constraints. | Recommendation only; best of the evaluated candidates, **not** proven globally optimal; starts from an empty queue. |
| `engines/analytics_engine.py` | Arrivals, waits, service time, queue length, utilisation, peak hours (statistically tested), daily/hourly tables, previous-period comparison, chart-ready JSON. | Durations in minutes; counter filter limits data to customers that counter served. |
| `engines/report_engine.py` + `services/report_service.py` | JSON, CSV and PDF (ReportLab) reports for 5 report types; synthetic/simulated data is labelled. | PDF shows <=60 rows per table. |

Migration `0002_intelligence_layer` adds `prediction_records`, `bottleneck_detections`, `optimization_results`, `reports`
(applied automatically at startup, or `python -m app.core.init_db`).

## Stack
Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, Alembic, SQLite (PostgreSQL-compatible schema),
NumPy, Pandas, SimPy, Pytest, HTTPX.

## Windows PowerShell quick start
Run from the `backend` folder.

```powershell
# 1. Create the virtual environment (use `python` if `py` is not installed)
py -3.11 -m venv .venv

# 2. Activate it  (if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# (optional) local configuration
Copy-Item .env.example .env

# 4. Initialise the database (applies Alembic migrations -> data\linezero.db)
python -m app.core.init_db

# 5. Generate labelled synthetic data (all 7 scenarios, ~500 customers each, reproducible)
python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset

# 6. Start the API  ->  http://127.0.0.1:8000/docs
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 7. Run the tests (each test uses its own temporary database)
python -m pytest
```

The API also migrates the database automatically on startup (`AUTO_MIGRATE=true`).

## Configuration (`.env`)
| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/linezero.db` | Relative SQLite paths resolve against `backend/`. PostgreSQL: `postgresql+psycopg://user:pass@host/db` (install `psycopg`). |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Use these values with uvicorn. |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated or JSON list. |
| `DEBUG` | `false` | |
| `AUTO_MIGRATE` | `true` | Run `alembic upgrade head` at startup. |

## Project layout
```
app/
  main.py                    app factory, CORS, health, startup migration
  core/                      config, database, errors, migrations, init_db
  models/                    SQLAlchemy models (+ UTC datetime type, enums)
  schemas/                   Pydantic request/response models
  api/routes/                queues.py, counters.py, simulation.py (thin HTTP layer)
  services/                  queue_service.py, simulation_service.py (business logic, transactions)
  engines/                   simulation_engine.py, queueing_theory.py, comparison.py (no DB / HTTP)
  seed/generate_demo_data.py synthetic data generator (CLI + functions)
alembic/                     migrations (0001 = initial schema)
tests/                       pytest suite
```

## API (all under `/api/v1`, interactive docs at `/docs`)
| Area | Endpoints |
|---|---|
| Queues | `GET/POST /queues` · `GET/PUT/DELETE /queues/{id}` · `GET /queues/{id}/state` · `GET /queues/{id}/events` |
| Entries | `POST/GET /queues/{id}/entries` · `GET/DELETE /queues/{id}/entries/{entry_id}` · `GET …/position` · `POST …/assign` · `POST …/complete` · `POST /queues/{id}/serve-next` |
| Counters | `GET/POST /counters` · `GET/PATCH /counters/{id}` · `POST /counters/{id}/pause` · `POST /counters/{id}/resume` |
| Simulations | `POST /simulations/run` · `GET /simulations` · `GET /simulations/{id}` · `POST /simulations/compare` · `DELETE /simulations` (reset) · `DELETE /simulations/{id}` |
| Predictions | `GET /predictions/{queue_id}` · `GET /predictions/{queue_id}/history` · `POST /predictions/evaluate` |
| Bottlenecks | `GET /bottlenecks` · `POST /bottlenecks/analyze` |
| Optimization | `POST /optimization/run` · `GET /optimization/{id}` |
| Analytics | `GET /analytics/overview｜arrivals｜waiting-times｜utilization｜peak-hours` |
| Reports | `GET /reports` · `POST /reports/generate` · `GET /reports/{id}` · `GET /reports/{id}/export?format=csv｜json｜pdf` |
| Meta | `GET /health` |

Endpoints beyond the brief (`state`, `events`, `position`, `assign`, `complete`, `GET counters/{id}`, simulation delete/reset)
exist because the brief's operations (queue position, assignment, event history, completing service so
`ServiceRecord`s exist, simulation reset) need an HTTP surface.

Errors always look like `{"error": {"code": "...", "message": "...", "details": ...}}`
(404 not found, 409 state conflicts such as `queue_empty` / `no_available_counter`, 422 validation).

### Queue semantics
* Entries are anonymous: a token number only, no personal data.
* Tokens increase per queue and are never reused (atomic counter on the queue row); position = rank among
  *waiting* entries by token, so removals move everyone up.
* `serve-next` is strict FIFO; it picks the lowest-id idle active counter unless `{"counter_id": n}` is given.
  A counter serves one customer at a time (`current_load` 0/1).
* Queue status: `active` (everything), `paused` (accepts entries, no serving), `closed` (rejects entries).
* Pausing a counter lets its current customer finish; it just receives nobody new. Pause/resume are idempotent.
* Removing a non-waiting entry returns 409. Deleting a queue cascades to its counters, entries, events and records.
* Units: `service_rate` = customers per minute; `ServiceRecord` times are in seconds; all timestamps are UTC.

## Simulation engine
`POST /simulations/run`
```json
{
  "name": "baseline",
  "configuration": {
    "arrival_rate": 1.2, "mean_service_time": 2.0, "num_counters": 3, "duration": 480,
    "arrival_distribution": "poisson",
    "service_distribution": "exponential",
    "seed": 42,
    "abandonment_enabled": false, "mean_patience": null,
    "counter_speed_factors": null, "counter_assignment": "longest_idle", "arrival_profile": null
  }
}
```
* Arrivals: `poisson` (exponential gaps), `deterministic`, `uniform`. Optional `arrival_profile`
  (`[{"start":120,"end":180,"multiplier":3}]`, Poisson only) models rush periods exactly via thinning.
* Service: `exponential`, `deterministic`, `uniform` (0.5×–1.5× mean), `lognormal` (σ = 0.5). `counter_speed_factors`
  gives each counter its own speed.
* Abandonment: exponential patience with mean `mean_patience`.
* Time is unitless; the rest of LineZero treats one unit as one minute.
* The seed is resolved before running and stored in the configuration, so every stored run is reproducible.
  Independent random streams are used for arrivals, service and patience.
* Results: total arrivals / served / remaining, abandoned, average / max / p50 / p95 waiting time (for customers who
  started service) plus `longest_unserved_wait`, time-weighted average and max queue length, average service time,
  per-counter and average utilisation, throughput, and a `theoretical` block (M/M/1, M/M/c via Erlang C, M/D/1 and
  M/G/1 via Pollaczek–Khinchine) whenever the configuration matches a textbook model.
* `POST /simulations/compare` runs 2–10 configurations with a shared seed (like-for-like) and returns per-metric
  values, deltas and % change vs. the first configuration, and the best configuration per metric.
* Runs are synchronous. `run_simulation(config)` is a pure function of picklable data, so moving it to a
  worker/thread pool later only touches `SimulationService._execute` (the `status` column already allows
  `queued/running/failed`).

## Synthetic data
```powershell
python -m app.seed.generate_demo_data --list
python -m app.seed.generate_demo_data --scenario normal,slow_counter --customers 1000 --seed 7 --reset
python -m app.seed.generate_demo_data --reset-only        # delete synthetic data only
```
Scenarios: `normal`, `arrival_spike`, `insufficient_capacity`, `uneven_utilization`, `slow_counter`,
`excess_capacity`, `mixed_rates`. Each creates one queue with counters, entries, events and service records,
produced by the same SimPy engine. Every row has `is_synthetic = true`; queues also carry `scenario` and a
`[SYNTHETIC]` description. Filter with `GET /queues?synthetic=true`. `--reset` removes only synthetic rows.

## Tests
Part 2 adds: `test_prediction_engine`, `test_bottleneck_engine`, `test_analytics_engine`, `test_optimization_engine`,
`test_report_engine` (pure NumPy/Pandas tests on data with known ground truth, via `tests/frames.py`; no SimPy needed)
and `test_intelligence_api` (API + DB + real SimPy, uses the Part 1 generator). `test_database` also covers the new tables.

`python -m pytest` covers: migrations, relationships, foreign keys and constraints, cascade deletes, UTC timestamps;
queue/entry/counter operations and error handling; arrival generation, service completion, multiple counters,
waiting-time and utilisation maths (a hand-calculated case), reproducibility and reset; agreement with M/M/1, M/M/2
(Erlang C) and M/D/1 theory; the simulation and generator APIs. API tests use `fastapi.testclient.TestClient`
(an `httpx.Client`) against a fresh temporary SQLite database per test.


## Part 2 files
```
app/engines/      prediction_engine.py bottleneck_engine.py optimization_engine.py analytics_engine.py report_engine.py
app/services/     prediction_ bottleneck_ optimization_ analytics_ report_service.py, data_access.py
app/models/       prediction.py bottleneck.py optimization.py report.py
app/api/routes/   intelligence.py (predictions, bottlenecks, optimization, analytics, reports)
app/schemas/      intelligence.py
alembic/versions/ 0002_intelligence_layer.py
tests/            frames.py (NumPy-only FIFO simulator for ground-truth tests), test_*_engine.py, test_intelligence_api.py
```

## Windows PowerShell: run everything (from the `backend` folder)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.core.init_db            # applies migrations 0001 + 0002
python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset
python -m pytest                      # full Part 1 + Part 2 suite
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload   # Swagger: http://127.0.0.1:8000/docs
```
