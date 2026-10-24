# Hardware setup (ESP32 + MQTT)

> **Topics, message format and broker setups (local no-TLS vs TLS) are defined in [`docs/MQTT.md`](MQTT.md).** Sensors you add on the website have their own topic `<base>/<machine_id>/<type>/<sensor_id>`; the sections below about registering by machine and type describe the older flow, which still works.

> **Status: not yet verified on a physical ESP32.** `tools/fake_esp32.py` can prove the software path (broker -> backend -> dashboard) without the board, but only your own hardware run proves the firmware and sensors work. The backend side is implemented and covered by tests, but **end-to-end operation with a physical ESP32 and a real broker has not been verified by the author of this change** - follow the checklist at the bottom on your own hardware before claiming it works.

## 1. Broker (Mosquitto example)
```bash
sudo apt install mosquitto mosquitto-clients
sudo mosquitto_passwd -c /etc/mosquitto/passwd trustguard_backend   # backend user
sudo mosquitto_passwd /etc/mosquitto/passwd esp32                   # device user
```
Ready-made config with TLS, authentication and per-user topic rules (backend may only read, each device may only write its own machine's topics): copy `docs/mosquitto/trustguard.conf` to `/etc/mosquitto/conf.d/` and `docs/mosquitto/trustguard.acl` to `/etc/mosquitto/`, then `sudo systemctl restart mosquitto`. Create the server certificate with your own CA (the ESP32 needs that CA certificate, see section 4).
(For a quick LAN-only test use `listener 1883` instead and set `MQTT_TLS=false` - credentials then travel unencrypted.)

## 2. Backend `.env`
```
MQTT_ENABLED=true
MQTT_BROKER_HOST=<broker host>   MQTT_BROKER_PORT=8883   MQTT_TLS=true   MQTT_CA_CERTS=/path/ca.crt
MQTT_USERNAME=trustguard_backend MQTT_PASSWORD=<secret>
ADMIN_API_KEY=<random>           DEVICE_API_KEY=<random>
```
Check `GET /api/hardware/broker` -> `"connected": true`.

## 3. Register the device -> machine mapping
```bash
curl -X POST localhost:8000/api/hardware/devices/register -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"device_id":"ESP32-A1","machine_id":1,"sensor_type":"temperature","unit":"°C"}'
curl -X POST localhost:8000/api/hardware/devices/register -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"device_id":"ESP32-A1","machine_id":1,"sensor_type":"vibration","unit":"m/s²"}'
```
The accelerometer maps to the `vibration` sensor type. Topics default to `trustguard/sensors/<machine_id>/<sensor_type>`.

## 4. Flash `firmware/esp32_trustguard/esp32_trustguard.ino` (edit the settings block first).
- Paste your broker's **CA certificate** into `CA_CERT`. With TLS on, the firmware now **refuses to connect without it** (it no longer silently disables certificate checks). `ALLOW_INSECURE_TLS = true` exists for a lab bench only.
- It also refuses to run while `MQTT_PASS` is still `CHANGE_ME`. Use a separate broker user per device and never commit real credentials.

## 4b. Calibrate the sensors (required before trusting scores on real data)
The model/trust baselines use the simulator's scale (vibration = mm/s, healthy mean 2.5). The ESP32 sends acceleration RMS in **m/s²**, a different physical quantity, so raw values are not comparable.
1. Run the machine in a known-good state for 10+ minutes.
2. `python tools/calibrate_baseline.py --api http://localhost:8000 --sensor-id <id> --sensor-type vibration --device-id ESP32-A1`
3. Paste the printed `SENSOR_CALIBRATION=...` line into `backend/.env`, restart the backend. (Temperature normally needs none; to fix a known bias use `--offset-only` against a reference thermometer.)
Calibrated vibration is an **index** aligned to the healthy baseline, not a true mm/s measurement; the original value stays in `raw_value`. Calibration is applied only to hardware readings. This aligns scales; it does not prove accuracy. Test on labelled data (known-good vs known-faulty runs) before making any claim.

### Units: m/s² is not mm/s
The model's vibration baseline is RMS **velocity** in mm/s; the firmware sends RMS **acceleration** in m/s². There is no exact conversion: velocity from acceleration needs the frequency content (for one dominant frequency f, v_rms = a_rms / (2π f)), and the firmware reports broadband RMS over ~200 ms. So until you calibrate, TrustGuard shows the sensor with a "Units not converted" warning and keeps it **out of the risk estimate and cross-sensor checks** (confidence is lowered because an input is missing). After calibration it is shown as an index (`idx`), not mm/s. Do not compare it with readings from a real velocity sensor.

## 4c. Use the setup checklist
The Hardware page opens with a four-step checklist per device: MQTT broker connected -> device registered -> first reading received -> sensor online. The first unfinished step says what to do next.

## 4d. Add a third sensor if you can
With only temperature + vibration, a disagreement cannot be resolved: TrustGuard reports "the two sensors disagree; cannot tell which is wrong" and blames neither. A third channel (e.g. motor current with an INA219/ACS712, or a second temperature probe) lets the other two outvote a faulty one. Register it like the others (section 3).

## 5. Test without hardware
```bash
python tools/fake_esp32.py --host <host> --port 8883 --tls --cafile ca.crt -u esp32 -P <pw> --machine 1 --case all   # normal, null, malformed, duplicate, old
mosquitto_pub -h <host> -p 8883 --cafile ca.crt -u esp32 -P <pw> -t trustguard/sensors/1/temperature \
  -m '{"device_id":"ESP32-A1","value":66.2}'
curl -X POST localhost:8000/api/hardware/ingest -H "X-Device-Key: $DEVICE_API_KEY" \
  -d '{"device_id":"ESP32-A1","sensor_type":"temperature","value":66.2}'          # HTTP fallback
curl -X POST localhost:8000/api/hardware/devices/<sensor_id>/test                   # test-connection checklist
curl localhost:8000/api/hardware/events                                             # rejected / delayed messages
```

## Payload rules
| Case | Result |
|---|---|
| Not JSON / wrong types / missing `device_id` or `value` | rejected `malformed` |
| `value: null` | stored as **missing** reading (lowers trust) |
| Outside physical range | stored, flagged **out_of_range** + outlier |
| Timestamp > 30 s old | stored, flagged **delayed**; > 1 h old rejected `too_old` |
| Future timestamp / unsynced device clock | server time used, flagged |
| Same sensor + timestamp twice | rejected `duplicate` |
| Unknown topic, wrong `device_id`/`sensor_type` | rejected `unregistered_topic` / `device_mismatch` / `type_mismatch` |
| Retained MQTT messages | ignored (they are not proof the device is alive) |

Device status: **Online** < 30 s since last message, **Stale** 30-120 s, **Offline** > 120 s or never (`DEVICE_STALE_SECONDS`, `DEVICE_OFFLINE_SECONDS`). Going offline raises a `device_offline` alert and re-runs the pipeline; it auto-resolves when data resumes.

## Security checklist (shared network / anything beyond your desk)
1. Broker: TLS (port 8883), `allow_anonymous false`, per-user passwords and the ACL in `docs/mosquitto/`.
2. Firmware: real `CA_CERT`; `ALLOW_INSECURE_TLS = false`; unique credentials per device.
3. Backend `.env`: `APP_ENV=production`, `MQTT_TLS=true`, `MQTT_CA_CERTS`, `MQTT_USERNAME/PASSWORD`, strong `ADMIN_API_KEY` and `DEVICE_API_KEY`. In production the MQTT bridge now refuses to start without TLS and credentials (override only for an isolated lab: `ALLOW_INSECURE_MQTT=true`).
4. The Hardware page and `GET /api/hardware/broker` list any remaining problems under `security_warnings`.
5. Put the API behind HTTPS (reverse proxy) and restrict `CORS_ORIGINS`; the admin key is sent as a header, so it must not travel over plain HTTP on a shared network.

## Known limitations
- Calibration aligns scales but no labelled-data validation of risk/trust accuracy has been done.
- Devices can also be registered from the Hardware management page in the dashboard.

## Verification checklist (do on real hardware)
Tick each box yourself; nothing below has been verified on a physical ESP32 by the author of this change.
1. [ ] Dashboard banner lists the remaining security/setup issues; none left before you use a shared network.
2. [ ] Hardware page checklist step 1 "MQTT broker connected" is done (`/api/hardware/broker` shows connected).
3. [ ] Step 2 "Device registered": both topics registered (temperature, vibration).
4. [ ] Step 3 "First reading received" turns done within one publish interval of powering the ESP32.
5. [ ] Step 4 "Sensor online" is done; sidebar shows DASHBOARD = LIVE and SENSOR DATA = FRESH.
6. [ ] Vibration shows "Units not converted" until calibrated (section 4b), then reads in `idx`, never mm/s.
7. [ ] Unplug the ESP32: after 30 s the stale banner shows the last-update time; after 120 s Offline + alert. Replug: Online, alert resolves.
8. [ ] Publish a duplicate / malformed message: it appears in `/api/hardware/events`.
9. [ ] With only two sensors, heat the temperature probe: the panel says CANNOT TELL and no sensor is blamed.

## Full test chain
```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt && pytest -q
TEST_POSTGRES_URL=postgresql+psycopg2://user:pw@localhost:5432/trustguard_test pytest -q   # same suite on a throw-away PostgreSQL
cd ../frontend && npm ci && npm run build
python tools/validate_labelled.py csv your_runs.csv --label-col faulty   # real labelled runs; see the script header
```
