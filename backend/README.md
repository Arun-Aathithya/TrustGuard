# TrustGuard AI — Backend

FastAPI service implementing the full pipeline from the architecture doc:

```
Data Processing → Sensor Trust Engine → Cross-Sensor Validation
  → ML Failure Prediction → Prediction Confidence → Recommendation Engine
  → Alerts + Maintenance
```

## Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # defaults to local SQLite, no DB server needed
```

### (Optional) Train the ML model

The API works out of the box with a transparent heuristic fallback. To use
the actual RandomForest model:

```bash
python -m ml.train
```

This writes `ml_models/failure_model.joblib`. Re-run any time to retrain.

### Run the API

```bash
uvicorn main:app --reload --port 8000
```

On first run this creates all tables and nothing else: the database starts with no machines, devices,
sensors or readings. Add machines in the dashboard (or `POST /api/machines`) and register sensors under
Hardware management.

- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health
- Live dashboard websocket: ws://localhost:8000/ws/live

### Remove the demo fleet from an older database

Older builds pre-loaded 5 demo machines. For a database that already has them:

```bash
python purge_demo_data.py          # dry run: prints what would change
python purge_demo_data.py --apply  # delete (SQLite: a backup copy is written first)
```

Only machines with the old demo names are touched. A demo machine that has a registered hardware sensor is kept
(with its hardware sensors and readings); only its simulated sensors, predictions, alerts and maintenance tasks are removed.

### Advance the simulation manually

```bash
curl -X POST http://localhost:8000/api/simulate/tick \
  -H "Content-Type: application/json" \
  -d '{"scenario": "drift"}'
```

Valid scenarios: `normal`, `noisy`, `drift`, `failure`, `missing`.

## Switching to PostgreSQL / Supabase

Edit `.env`:

```
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/trustguard
```

Nothing else needs to change — SQLAlchemy handles the rest.

## Connecting real ESP32 hardware later

1. Set `MQTT_ENABLED=true` and the broker host/port in `.env`.
2. Point each ESP32 at topic `trustguard/sensors/<machine_id>/<sensor_type>`,
   publishing JSON: `{"value": 71.4, "device_id": "ESP32-A1"}`.
3. Register the device's `device_id` against its sensor via
   `POST /api/hardware/devices/register`.

Real and simulated data flow through the exact same ingestion pipeline —
the frontend never talks to hardware directly.
