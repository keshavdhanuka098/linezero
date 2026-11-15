# LineZero Frontend

React 18 + TypeScript + Vite. Landing page at `/`, application at `/app`.

    npm install
    npm run dev          # http://localhost:5173
    npm run build        # tsc + vite build
    npm run preview

## Data sources

The top bar has a source switch:

- **Server API** (default when the backend is reachable): dashboard predictions, live monitor, analytics, simulator (SimPy), bottleneck analysis, optimizer and reports all come from the LineZero backend.
- **Browser demo**: the original self-contained synthetic demo (no backend needed). Also used automatically when the API is unreachable.

The dev and preview servers proxy `/api` and `/health` to `http://127.0.0.1:8000`. Copy `.env.example` to `.env` to change the proxy target (`VITE_API_PROXY`) or point the build at another API (`VITE_API_URL`, e.g. `https://host/api/v1`; the backend's `CORS_ORIGINS` must then include your origin).

## Layout

- `src/api` HTTP client, response types, connection and source state
- `src/app/server` pages that render backend data
- `src/app/pages` browser-demo pages (each page switches between the two)
- `src/app/twin` Digital Twin (`/app/digital-twin`): live floor view and forecast, what-if/chaos lab with playback and timeline, self-healing, scenario comparison, explanations. Server mode only: it needs the backend's SimPy engines
- `src/store`, `src/lib` demo engine, queue maths, simulator, optimizer, exporters; `src/lib/twinPlayback.ts` is the Digital Twin's pure form/config/playback logic (unit-tested)
- `src/landing` landing page
