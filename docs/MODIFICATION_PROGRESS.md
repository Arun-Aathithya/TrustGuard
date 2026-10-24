# Phase 3 modification progress

| Step | Scope | Status |
|---|---|---|
| 1 | Inspect project, remove preset fleet | **done** |
| 2 | User-configurable Temperature (DS18B20) / Vibration (MPU6050) sensors with custom names | **done** |
| 3 | MQTT + FastAPI integration | **done** |
| 4 | Persistent historical readings + APIs | **done** (this ZIP) |
| 5 | Dashboard: live readings + history | pending |
| 6 | ESP32 firmware + OLED | pending |
| 7 | Integration test + final docs | pending |

## Step 1 changes
- Removed `backend/services/seed_service.py` and `backend/seed_db.py`; startup no longer creates machines, sensors or history.
- Added `backend/purge_demo_data.py` (dry run by default) to clean databases created by older builds.
- `POST /api/simulate/tick` returns 409 for a machine with no sensors instead of producing a prediction from nothing.
- Frontend: empty-state page, **+ Add machine** form, **Remove machine** button; machines with no data show "No data yet"
  instead of default 0% risk / 100% confidence / 100% trust figures.
- Tests: `tests/conftest.py` creates its own test machines; new `tests/test_no_preset_fleet.py`.

## Step 4 changes
- **History API** (`backend/api/history.py`, documented in `docs/HISTORY_API.md`): `GET /api/history/sensors`, `/readings` (filter by sensor(s), machine, time range, source; paging; newest or oldest first), `/sensors/{id}/series` (bucketed min/avg/max + summary for charts, streamed so memory does not grow with the number of readings) and `/export.csv` (formula-safe). Bad filters return 422/404 instead of being ignored.
- **Stored history:** readings were already kept indefinitely (nothing prunes them); each reading links to its sensor, so name, type, unit and machine are returned with every row. Readings are removed only with their sensor/machine.
- **Duplicate protection in the database:** unique partial index on hardware readings (sensor + timestamp) plus an index for sensor/time-range queries. Added to existing databases automatically at startup; a race between two identical messages is now answered with a clean `duplicate` rejection instead of a 500. `dedupe_hardware_readings.py` cleans an older database that already holds duplicates.
- **Tests:** `tests/test_history_service.py` (pure; runs here) and `tests/test_history_api.py` (**not run** in the sandbox).

## Known limitations after Step 4
- Backend integration tests and the frontend build were not run in the authoring sandbox (no package installs). 19 pure test cases for history plus the 40 MQTT config/payload tests did run; run `pytest -q` on your machine.
- Bucketing is done in Python while streaming rows. Fine for a local installation (seconds for hundreds of thousands of readings), but a very large PostgreSQL history would be better served by database-side aggregation.
- Removing a sensor permanently deletes its history. A "keep history of removed sensors" option is not implemented.
- The website does not use the history API yet (Step 5). `GET /api/history/*` has no authentication, like the other read endpoints.

## Step 3 changes
- **Documented contract:** `docs/MQTT.md` defines the topics (`<base>/<machine_id>/<type>/<sensor_id>`), the JSON message, what happens to each kind of bad message, and two broker setups: local development (password, no TLS) and TLS. New `docs/mosquitto/trustguard-dev.conf`; the ACL now explains the topic layout.
- **Correct sensor association:** the topic selects the sensor; `device_id` must match the linked device, and optional `sensor_id`, `sensor_type` and `unit` must match the configuration. Several sensors of one type on one ESP32 are allowed (each has its own topic); over HTTP they need `sensor_id` (otherwise `ambiguous_sensor`). A sensor with no device linked rejects messages with `device_not_linked`.
- **Settings validated up front** (`hardware/mqtt_config.py`): bad port/host/topic, a missing CA file with TLS on, a password without username, and the production rules are reported in `/api/hardware/broker` and the log; the app still starts. Passwords never appear in logs or API output. `TLS` is reported on only if the TLS client was really configured.
- **One connection:** the bridge starts once and stops on shutdown (`stop_mqtt_bridge`); starting twice returns the existing client. Warns when `WEB_CONCURRENCY > 1`.
- **Reconnection / health:** automatic reconnect with resubscribe; status now includes `disconnects`, `last_disconnect_at`, `messages_dropped`, `client_id`, `config_warnings`, and a hint when the broker rejects credentials.
- **Flood protection:** `MQTT_MAX_MESSAGES_PER_SECOND` (default 100); over-long topics are dropped.
- **`.env.example`:** documented MQTT block with new `MQTT_CLIENT_ID`, `MQTT_KEEPALIVE_SECONDS`, `MQTT_MAX_MESSAGES_PER_SECOND` (placeholders only).
- `tools/fake_esp32.py` can target a configured sensor's topic (with a warning that its data is indistinguishable from real data).
- **Tests:** `tests/test_mqtt_config.py` (pure; 40 cases run successfully in the authoring sandbox), `tests/test_mqtt_ingest.py` (matching, bad messages, duplicates, flood limit, lifecycle with a fake paho; **not run** in the sandbox).

## Step 2 changes
- **Only two sensor types can be added:** Temperature (DS18B20, °C) and Vibration (MPU6050, m/s², RMS of dynamic acceleration as the firmware reports it). Defined once in `backend/services/sensor_catalog.py`; the API rejects anything else (422), including on `POST /api/hardware/devices/register`.
- **Sensor API** (`/api/sensors`): `GET /types`, `POST` (machine, type, custom name, optional device ID), `PATCH /{id}` (rename, link a device), `DELETE /{id}`. Writes need the admin key when `ADMIN_API_KEY` is set. Names are trimmed, 1-60 characters, unique per machine (case-insensitive). Several sensors of the same type are allowed.
- **Stored in the database:** new columns `sensors.name` and `sensors.hardware_model`, added to existing databases automatically at startup (additive, no data lost). Configuration therefore survives refresh and restart.
- **A new sensor never shows a value until a real device reports.** It starts as a hardware sensor with status "No device" (or offline once a Device ID is linked) and "—" for its reading. Removing a sensor deletes its readings, trust history and its alerts, then recomputes (or clears) the machine's prediction.
- **Website:** "+ Add sensor" on a machine (type, name, optional Device ID); each sensor card shows its name, type and model, latest reading with unit, connection status, last updated time, and a "Remove sensor" button. The Hardware page's type list is limited to the two types.
- **Device registration** now binds a device to a waiting sensor (for example one added on the website) instead of duplicating it, and gives a second sensor of the same type its own topic.
- **Tests:** new `tests/test_sensor_config.py`; `tests/test_hardware_api.py` moved off pressure/current/rpm devices.

## Known limitations after Step 3
- No real Mosquitto broker, ESP32 or paho-mqtt was available: the broker connection and TLS handshake are untested here (a fake client module checks the lifecycle). Backend integration tests and the frontend build were not run either; run `pytest -q` and `npm run build`.
- No MQTT Last-Will message: a dead device is detected by silence (stale 30 s, offline 120 s), not instantly.
- The existing firmware still publishes to the old per-type topics `<base>/<machine>/<type>` and cannot yet carry several sensors per ESP32; Step 6 rewrites it for the per-sensor topics.
- Without a timestamp from the device, a retransmitted message cannot be recognised as a duplicate.
- Not tested with a real broker: authentication failure messages, TLS certificate errors.

## Known limitations after Step 2
- Not executed in the authoring sandbox: backend tests and the frontend build (no package install possible there). Frontend sources were only syntax-checked. Run `pytest -q` and `npm run build` on your machine.
- Sensors added on the website get the MQTT topic `trustguard/sensors/<machine_id>/<type>/<sensor_id>`. The final topic and JSON scheme, and how several same-type sensors on one ESP32 are told apart, are fixed in Step 3. Until then one device provides at most one sensor of each type, and nothing flows to a website-added sensor until the firmware publishes to its topic with a matching `device_id`.
- Sensors created by older builds (including pressure, current and rpm) still display; they just cannot be added any more. Their custom name is empty, so the type label is shown.
- A vibration sensor reporting m/s² is shown but kept out of failure-risk scoring until calibrated (existing behaviour, `docs/HARDWARE_SETUP.md` 4b).
- The "SIMULATION ONLY" controls still exist for machines that have simulated sensors; website-added sensors are never simulated.

## Known limitations after Step 1
- Not executed in the authoring sandbox: backend tests and the frontend build (no package install possible there). Frontend sources were only syntax-checked. Run `pytest -q` and `npm run build` on your machine.
- Five sensor types and the simulation controls still exist; they are narrowed to Temperature/Vibration in Step 2.
- Machine/sensor creation still needs `ADMIN_API_KEY` if one is set in `.env`.
