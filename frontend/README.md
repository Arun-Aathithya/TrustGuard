# TrustGuard AI — Frontend

React + Vite dashboard for the TrustGuard AI predictive maintenance system.

## Setup

```bash
cd frontend
npm install
cp .env.example .env      # points at the backend, defaults to localhost:8000
npm run dev
```

Open http://localhost:5173. Make sure the backend (`../backend`) is running
first — the dashboard needs it for machine/sensor/prediction data.

## What's here

- **Sidebar** — the machine fleet with live status and failure risk
- **Instrument gauges** — Failure Risk, Prediction Confidence, Overall Sensor
  Trust, styled as an industrial dial rather than a generic progress ring
- **Sensor array** — live value, trust score, and sparkline per sensor
- **AI Recommendation banner** — the decision engine's explainable output
- **Cross-sensor validation panel** — which sensors agree / disagree
- **Prediction history chart** — risk, confidence, and trust over time
- **Alerts feed** — open alerts with one-click resolve
- **Scenario controls** — trigger normal/noisy/drift/failure/missing-data
  scenarios on demand to see the whole pipeline react in real time

Live updates arrive over the `/ws/live` WebSocket; if that connection drops,
the app automatically falls back to REST polling every 5 seconds.

## Build for production

```bash
npm run build
```

Outputs to `dist/` — serve with any static host (the FastAPI backend stays
a separate service; point `VITE_API_BASE_URL` / `VITE_WS_URL` at wherever
it's deployed).
