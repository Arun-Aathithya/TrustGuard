# MQTT: topics, messages and broker setup

```
ESP32 --Wi-Fi--> Mosquitto (MQTT broker) --> FastAPI backend --> database --> website (WebSocket)
```
The backend is the only MQTT client besides your devices. The website never talks to the broker.

> **Hardware status:** nothing in this document has been verified with a physical ESP32 by the author. The backend side
> is covered by automated tests that hand messages to the same code the broker connection uses; the firmware/hardware
> side is yours to verify (checklist at the end).

## 1. Topics

| Direction | Topic | Meaning |
|---|---|---|
| device -> backend | `<base>/<machine_id>/<sensor_type>/<sensor_id>` | one reading of one configured sensor |

* `<base>` is `MQTT_BASE_TOPIC` (default `trustguard/sensors`).
* `<sensor_type>` is `temperature` (DS18B20) or `vibration` (MPU6050).
* `<sensor_id>` is the number the website assigns when you add the sensor.
* **The exact topic of every sensor is stored with it.** Open the sensor's *Details* on the dashboard (or `GET /api/sensors/<id>`, field `mqtt_topic`) and use that string in the firmware. Example: `trustguard/sensors/1/temperature/7`.
* The backend subscribes to `<base>/#` at QoS 1 and ignores retained messages. Publish **without** the retain flag, otherwise an old value would look alive after the device died.

## 2. Message (JSON, UTF-8, at most 2048 bytes)

```json
{"device_id": "ESP32-A1", "value": 21.5, "timestamp": "2026-10-18T12:00:00Z"}
```

| Field | Required | Rules |
|---|---|---|
| `device_id` | yes | 3-80 characters `A-Z a-z 0-9 _ . -`. Must equal the Device ID linked to that sensor. |
| `value` | yes | a number, or `null` when the sensor could not be read. `null` is stored as a **missing** reading (it lowers trust); never send 0 or a stale value instead. Temperature in °C; vibration = RMS of dynamic acceleration in m/s². |
| `timestamp` | no | ISO-8601 (UTC) or epoch seconds/milliseconds. Omit it when the ESP32 clock is not synced; the server then uses the receive time. |
| `sensor_id` | no | the sensor's number; if present it must match the topic. Required for HTTP ingestion when one device has several sensors of the same type. |
| `sensor_type` | no | if present it must match the sensor (`temperature` / `vibration`). |
| `unit` | no | if present it must match the sensor's unit (`°C`, `m/s²`; notation like `m/s2` is accepted). |

Unknown extra fields are ignored.

### What happens to a message

| Situation | Result (recorded in `GET /api/hardware/events`) |
|---|---|
| valid | stored as a reading with source `hardware`; dashboard updates within a few seconds |
| `value: null` | stored as missing (`missing`) |
| not UTF-8 / not JSON / not an object / missing or wrongly typed fields / NaN / over 2048 bytes | rejected `malformed` or `invalid_value`; nothing stored |
| topic belongs to no sensor | rejected `unregistered_topic` |
| sensor has no device linked yet | rejected `device_not_linked` (enter the Device ID on the dashboard) |
| `device_id`, `sensor_id`, `sensor_type` or `unit` disagree with the configuration | rejected `device_mismatch` / `sensor_mismatch` / `type_mismatch` / `unit_mismatch` |
| same sensor + same timestamp already stored (retransmission) | rejected `duplicate` |
| physically impossible value (e.g. a DS18B20 error value of -127) | stored but flagged `out_of_range` and treated as an outlier |
| more than ~30 s old / older than 1 h / in the future | `delayed` (stored) / `too_old` (rejected) / server time used |
| more than `MQTT_MAX_MESSAGES_PER_SECOND` arriving | extra messages dropped and counted (`messages_dropped`) |

**Disconnected devices.** The backend notices silence: a sensor is *online* if a message arrived in the last 30 s, *stale* up to 120 s, then *offline*; going offline raises an alert and lowers confidence. (Thresholds: `DEVICE_STALE_SECONDS`, `DEVICE_OFFLINE_SECONDS`.) There is no Last-Will message yet, so a device that dies is detected by silence, not instantly.

**Reconnection.** The backend reconnects to the broker by itself (1-30 s back-off) and resubscribes on every connect. `GET /api/hardware/broker` shows `connected`, `disconnects`, `last_error`, `messages_received`, `messages_dropped`.

### HTTP fallback
`POST /api/hardware/ingest` with header `X-Device-Key` accepts the same JSON plus `sensor_type` (or `sensor_id`). Same validation, same pipeline.

## 3. Backend settings (`backend/.env`, see `.env.example`)

`MQTT_ENABLED`, `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TLS`, `MQTT_CA_CERTS`, `MQTT_BASE_TOPIC`, `MQTT_CLIENT_ID`, `MQTT_KEEPALIVE_SECONDS`, `MQTT_MAX_MESSAGES_PER_SECOND`. They are validated at startup; a bad value (non-numeric port, missing CA file with TLS on, password without username, `mqtt://` in the host, ...) is reported in `/api/hardware/broker` (`last_error`) and the log, and MQTT stays off while the rest of the app runs. No password or key is stored in source code.

**One connection only.** The bridge starts once at application startup and closes at shutdown; starting twice returns the existing connection. Run uvicorn with a single worker (each worker would open its own connection), and do not run two backends with the same `MQTT_CLIENT_ID`: the broker disconnects the older one and the two fight forever.

## 4. Choose the broker setup that matches reality

The backend only reports TLS as **on** when `MQTT_TLS=true` and the TLS client was set up. Make the broker and `.env` agree:

**A. Local development (no TLS, password login), what you get if you have not created certificates.**
Broker: `docs/mosquitto/trustguard-dev.conf` + `docs/mosquitto/trustguard.acl` (listener 1883, `allow_anonymous false`).
`.env`: `MQTT_ENABLED=true`, `MQTT_BROKER_HOST=localhost` (or the broker PC's address), `MQTT_BROKER_PORT=1883`, `MQTT_TLS=false`, `MQTT_USERNAME=trustguard_backend`, `MQTT_PASSWORD=<what you set with mosquitto_passwd>`.
Firmware: `USE_TLS=false`, port 1883, the `esp32` user. **Credentials and data are unencrypted.** Use a network you control. The dashboard shows "TLS off" and a warning, which is accurate.
Windows broker PC: allow TCP 1883 in the firewall, and give the ESP32 the PC's LAN IP (not `localhost`).

**B. TLS (anything beyond a trusted bench).** Create a CA and a server certificate whose name/IP matches `MQTT_BROKER_HOST`, use `docs/mosquitto/trustguard.conf` (listener 8883) and the same ACL, and set `MQTT_TLS=true`, `MQTT_BROKER_PORT=8883`, `MQTT_CA_CERTS=/path/ca.crt`. Paste the CA certificate into the firmware's `CA_CERT`.
No certificates are included in this project, so TLS is **not** enabled until you create them.

**Check the broker without the backend:**
```bash
mosquitto_sub -h <host> -p 1883 -u trustguard_backend -P '<password>' -t 'trustguard/sensors/#' -v
mosquitto_pub -h <host> -p 1883 -u esp32 -P '<password>' -t 'trustguard/sensors/1/temperature/7' \
  -m '{"device_id":"ESP32-A1","value":21.5}'
```
Then `GET /api/hardware/broker` should show `"connected": true`, and the sensor's reading appears on the dashboard. (A reading sent this way is real data as far as the backend can tell. Delete the sensor or its readings afterwards if it was only a test.)

## 5. Verify on your own hardware
1. `GET /api/hardware/broker` -> `connected: true`.
2. Add the sensor on the dashboard, link the Device ID, copy its topic into the firmware.
3. Flash; within one publish interval the sensor shows a value, status *online*.
4. Unplug the DS18B20: the next messages carry `null` and show as missing. Power the ESP32 off: the sensor goes stale, then offline, with an alert.
5. Stop and start Mosquitto: `disconnects` increases and data resumes without restarting the backend.
