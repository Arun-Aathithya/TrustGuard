# TrustGuard AI

A predictive-maintenance system that doesn't just predict machine failure —
it tells you how much to trust that prediction, based on the reliability of
the sensors feeding it. Built from the architecture doc: simulated sensor
data today, real ESP32/IoT hardware later, same backend pipeline for both.

```
React Dashboard
  ↓ REST / WebSocket
FastAPI Backend
  ↓
Data Processing → Sensor Trust Engine → Cross-Sensor Validation
  → ML Failure Prediction → Prediction Confidence → Recommendation Engine
  ↓
PostgreSQL / Supabase (SQLite by default, zero setup)
```

## Quick start

**1. Backend**

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m ml.train          # optional: train the real RandomForest model
uvicorn main:app --reload --port 8000
```

The database starts **empty**: no machines, devices, sensors or readings are pre-loaded.
API docs at http://localhost:8000/docs. If you are upgrading a database created by an older build that
did pre-load demo machines, run `python purge_demo_data.py` (dry run) and then `python purge_demo_data.py --apply`.

**2. Frontend**

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open http://localhost:5173.

**3. Try it**

Click **+ Add machine**, name it, then use **+ Add sensor** to add Temperature (DS18B20) or Vibration (MPU6050) sensors with your own names, and link each to its ESP32 (Device ID)
(see `docs/HARDWARE_SETUP.md`). Nothing is shown as a reading until a sensor really reports. Optionally, on a machine
that has sensors, use the clearly labelled "SIMULATION ONLY" buttons on its dashboard — Normal, Noisy, Drift, Sensor Failure, Missing
Data — and watch the Failure Risk, Prediction Confidence, and AI
Recommendation update live as the pipeline reprocesses each tick.

## What each module does

| Module | Responsibility |
|---|---|
| `simulation/` | Generates realistic sensor data (5 types × 5 scenarios) without hardware |
| `services/data_processing.py` | Missing-value, duplicate, range, outlier, timestamp, normalization checks |
| `trust_engine/` | Computes each sensor's 0–100% Trust Score; flags cross-sensor disagreement |
| `ml/` | RandomForest Failure Risk model (heuristic fallback if untrained) |
| `prediction/confidence.py` | Turns sensor trust (and cross-sensor conflicts) into Prediction Confidence. The only place trust acts on a prediction |
| `recommendation/` | Turns risk + confidence + trust into one explainable action (risk itself never uses trust) |
| `hardware/mqtt_client.py` | Drop-in bridge for real ESP32 sensors — same pipeline, no frontend changes |
| `api/` | REST endpoints + `/ws/live` for the dashboard |

Full setup details, environment variables, and how to plug in a real
PostgreSQL/Supabase database or real ESP32 hardware are in
`backend/README.md` and `frontend/README.md`.

## Notes on this build

- Runs entirely on SQLite by default — no database server required to try it.
  Switching to PostgreSQL/Supabase is a one-line `.env` change.
- The ML model is trained automatically on first start (a few seconds) on a physically-motivated
  synthetic dataset, because a new deployment has no real failure history; retrain any time with
  `python -m ml.train`. **It has not been validated against labelled real failures**, so treat risk
  as a decision aid, not a reliability claim (the UI says so).
- The trust engine's "flatline detection" is worth knowing about: a sensor
  that gets stuck reporting one constant value has *zero* variance, which a
  naive consistency check would score as "perfectly stable." This build
  treats a suspiciously flat signal as a red flag instead, since real
  physical sensors always carry a small amount of natural jitter.


---

## Improvement roadmap (phased)

| Phase | Scope | Status |
|---|---|---|
| 1 | Backend & hardware core: MQTT fix, device registry, Online/Stale/Offline, validation, auth, ESP32 firmware | **done** - see `docs/HARDWARE_SETUP.md` |
| 2 | Dashboard: data-source indicator, overview summary, Hardware Management page, sensor cards | **done** |
| 3 | Explainable recommendations, sensor detail/history, responsive + accessibility, demo scenarios | **done** - see `docs/DEMO_SCRIPT.md` |

### Phase 1 changes at a glance
- **Fixed:** the MQTT bridge crashed on the pinned `paho-mqtt 2.x` (`Client()` needs a callback API version) and died if the broker was down; it now auto-reconnects, supports username/password + TLS, and ignores retained messages.
- **New:** `ingestion_events` log, `sensors.data_source / last_seen_at`, `sensor_readings.source / is_delayed` (existing databases are upgraded automatically).
- **New API:** `/api/hardware/{summary,broker,devices,devices/register,devices/{id}/unregister,devices/{id}/test,events,ingest}`; sensor payloads now include `data_source`, `device_status`, `seconds_since_seen`; machine dashboards include `data_source`.
- **Behaviour:** simulation never writes to hardware sensors; hardware and simulated history never mix in trust windows; identical open alerts are no longer re-raised on every reading.
- **Security:** `ADMIN_API_KEY` guards register/unregister, machine/sensor create+delete, alert resolve, maintenance update; `DEVICE_API_KEY` guards HTTP ingest. Keys are backend-only. *Note: when `ADMIN_API_KEY` is set, the current UI's "resolve alert"/maintenance buttons get 401 until Phase 2 adds an admin-key prompt.*
- **Tests:** `pip install -r requirements-dev.txt && pytest -q` (in `backend/`).

### Phase 2 changes at a glance (frontend)
- **Overview page** (new default view): active data source badge (Real hardware / Simulation / Mixed), connected devices, stale sensors, active faults, and three clearly separate measures: sensor trust, machine failure risk, prediction confidence. Includes a per-machine table.
- **Hardware management page**: broker status, admin-key entry (held in the browser tab only, never in code), device/sensor mapping table with device ID, MQTT topic, Online/Stale/Offline status and last-seen time, register / unregister, test-connection checklist, and a log of rejected/delayed/malformed messages.
- **Sensor cards**: device status pill, hardware-vs-simulated label, last-updated time, and plain-language warnings (stale, offline, missing readings, drift, noise, suspicious value, disagreement) shown as text, not colour alone.
- **Machine dashboard**: data-source badge, a visible delayed-data warning banner, and simulation controls separated and labelled (hidden for machines that are 100% hardware).
- **Other**: alert-resolve errors now shown; sidebar navigation with `aria-current`; focus outlines; layouts wrap on narrow screens (full responsive polish comes in Phase 3).

### Phase 3 changes at a glance
- **Explainable recommendations** (`recommendation/explain.py`, returned as `explanation` on every machine dashboard): action, urgency (routine / soon / immediate), *why risk is this level*, *why confidence is this level*, per-sensor contributions, and a clear split between **suspected sensor faults** and **probable machine faults**. Wording is evidence-based ("suggests", "may"), and a caveat about unvalidated accuracy, stale hardware data and simulated data is always shown.
- **Sensor detail view**: "Details & history" on each sensor card opens a dialog (Esc to close) with value, trust, status, last-seen, MQTT topic, reading history with missing/suspicious/delayed points marked, trust-component history, 15 min / 1 h / 6 h range, plus loading, empty and error states.
- **Guided demo** (`DemoGuide`): 1) normal, 2) injected sensor fault, 3) simulated machine failure, each labelled SIMULATED / INJECTED. Hidden for hardware-only machines; never touches real sensors.
- **Responsive + accessible**: sidebar becomes a top bar on phones, tablet layout, tables scroll inside themselves, skip link, 44 px navigation targets, higher-contrast secondary text, text alternatives for charts, announced errors/loading.
- **Admin key prompt** appears inline when resolving an alert returns 401 (fixes the Phase 1 note).
- **Fixed while validating the prediction logic** (these were real bugs, not polish):
  1. The risk model scaled readings against physical limits (e.g. 0-200 °C), so even a clearly overheating machine scored under 10% risk and "potential machine failure" could never be shown. Features are now scaled to the operating band (`normalize_operating`), model version `rf-v2`; stale/old model files are retrained automatically.
  2. A machine-wide shift (2+ sensors moving together) was being scored as per-sensor *drift*, lowering trust. It is now treated as a machine condition.
  3. Simulation "faults" hit every sensor, which made cross-sensor validation useless in the demo. Injected sensor faults now affect the **temperature sensor only**; a new `machine_fault` scenario affects all sensors consistently.
- **Tests**: new pure-logic tests for the explanation and scaling (`pytest -q` in `backend/`).

## Telegram bot (alerts + status on your phone)
Free and built into the backend (standard library only). Pushes new alerts and urgency changes to authorised Telegram chats and answers `/status`, `/machine <id>`, `/alerts`, `/devices`, `/mute`. Disabled by default; setup in `docs/TELEGRAM_BOT.md`. Tested against a local fake of Telegram's server only: confirm with the **Send test message** button on the Hardware page.


## How risk, trust and confidence stay independent
- **Failure risk** is computed from the process readings only (temperature, vibration, pressure, current, rpm). Sensor trust is *not* a model input, so distrusting a sensor can never move the risk number.
- **Sensor trust** scores data reliability per sensor (consistency, noise, drift, missing data, cross-sensor agreement, communication).
- **Prediction confidence** is the only place trust affects a prediction: low or conflicting trust lowers confidence, never risk.
- **Cross-sensor verdicts** (`trust_engine/cross_sensor.py`): *machine change* (two or more sensors moved together: nobody is penalised, drift is not charged to any sensor), *sensor suspect* (one moved, two or more stayed normal: only that sensor loses trust), *cannot tell* (only two sensors and they disagree: nobody is blamed, confidence drops, an alert says "the two sensors disagree; cannot tell which is wrong"; add a third sensor to break the tie).
- **Units**: a hardware vibration sensor reporting m/s² is not comparable with the mm/s baseline. Until it is calibrated it is kept out of risk and cross-sensor checks and flagged "Units not converted". After calibration it is shown as an index (`idx`), never as mm/s.
