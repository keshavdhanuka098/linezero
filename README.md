# LineZero

    linezero/
      backend/    FastAPI + SimPy + SQLite API (queues, simulation, prediction, bottlenecks, optimisation, analytics, reports)
      frontend/   React + TypeScript application and landing page
      shared/     queueing_fixtures.json (reference values both test suites check)
      docs/       API_REFERENCE.md, FRONTEND_INTEGRATION.md
      scripts/    start-backend / start-frontend for macOS/Linux (.sh) and Windows (.ps1)

## Run

Two terminals, from this folder:

    ./scripts/start-backend.sh        # Windows: .\scripts\start-backend.ps1   -> http://127.0.0.1:8000/docs
    ./scripts/start-frontend.sh       # Windows: .\scripts\start-frontend.ps1  -> http://localhost:5173

Open http://localhost:5173/app. The frontend proxies `/api` to the backend and uses its built-in demo data if the API is not running. No database is committed: the start script creates `backend/data/linezero.db` and seeds labelled synthetic demo data on first run (`data/seeded.flag` marks it done). To reseed, delete that flag or run `python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset` from `backend/`.

## Why some logic exists twice

The frontend keeps a small TypeScript demo engine (`frontend/src/lib`: simulator, bottleneck rules, optimizer, queue maths) so the app works offline and without a backend. The backend is the source of truth when connected. The two are deliberately different models, not copies: the frontend optimizer uses an Allen-Cunneen G/G/c formula with exhaustive search, the backend scores candidates with replicated SimPy runs. The only shared maths is the M/M/c (Erlang C) formula. It is pinned by `shared/queueing_fixtures.json`, which both test suites assert against, so changing it in one language without the other fails a test.

## Test

    cd backend && python -m pytest                    # API, engines, shared fixtures
    cd frontend && npm test                           # Vitest unit tests (queue maths, simulator, optimizer, validation, CSV)
    cd frontend && npm run test:e2e                   # Playwright; demo-mode specs always run, server-mode specs run when the API is up
    cd frontend && npm run build

Playwright needs a browser: `npx playwright install chromium` once (or set `PLAYWRIGHT_CHROMIUM_PATH` to an existing Chromium).
