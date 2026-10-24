# Historical readings: storage and API

## What is stored
Every accepted reading is a row in `sensor_readings` and is **kept**: new readings are added, nothing is overwritten by the latest value, and there is no automatic deletion.

| Column | Meaning |
|---|---|
| `id` | unique reading id |
| `sensor_id` | the configured sensor (its custom name, type, unit and machine are in `sensors`; the history API joins them in) |
| `timestamp` | when the value was measured (UTC; the device's timestamp if it sent a plausible one, else the server's receive time) |
| `value` | the cleaned value; `null` = the sensor failed to read (a gap, never a number) |
| `raw_value` | what the device sent before calibration/cleaning |
| `is_missing`, `is_outlier`, `is_delayed` | quality flags |
| `source` | `hardware` (arrived from a device) or `simulation` |

Readings of a sensor are deleted **only** when that sensor (or its machine) is removed; the dashboard asks for confirmation first.

### Protection against duplicates and bad data
* Malformed, wrongly typed, non-finite, oversize or mismatching messages are rejected before anything is written (see `docs/MQTT.md`).
* A hardware reading with the same sensor and timestamp as an existing one is rejected by the application, **and** the database enforces it with a unique index (`uq_sensor_readings_hw_sensor_ts`), so two identical messages processed at the same moment cannot both be stored.
* Existing databases get the new indexes automatically at startup. If duplicates already exist the unique index cannot be built; the app keeps running, logs a warning, and `python dedupe_hardware_readings.py` (dry run by default, `--apply` to delete; SQLite is backed up first) removes the surplus copies.

## Endpoints (all `GET`, no key needed, like the other read endpoints)

Common time filters: `start`, `end` (ISO-8601 such as `2026-10-24T12:00:00Z`, or epoch seconds/ms) and `range` = `15m | 1h | 6h | 24h | 7d | 30d | all` (default `24h`; an explicit `start` wins over `range`). Invalid values give HTTP 422. Times in responses are UTC with a trailing `Z`.

### `/api/history/sensors?machine_id=`
Every configured sensor with `name`, `sensor_type`, `hardware_model`, `unit`, `machine_id`, `reading_count`, `first_at`, `last_at` (zero readings are listed too). Use it to fill a sensor picker.

### `/api/history/readings`
Parameters: `sensor_id` (repeat for several), `machine_id`, time filters, `source=hardware|simulation`, `include_missing=true|false`, `order=asc|desc` (default `desc`), `limit` (1-5000, default 500), `offset`.
Returns `{start, end, total, limit, offset, has_more, items:[{id, timestamp, sensor_id, sensor_name, sensor_type, hardware_model, unit, machine_id, value, raw_value, is_missing, is_outlier, is_delayed, source}]}`.

### `/api/history/sensors/{sensor_id}/series`
Chart data. Parameters: time filters, `source`, `max_points` (10-2000, default 300).
Returns `{sensor, start, end, bucket_seconds, summary:{count, missing, min, max, avg, first_at, last_at}, points:[{t, avg, min, max, count, missing}]}`. Buckets with only missing readings have `avg: null` so a chart can show the gap. The reading count is limited by `HISTORY_SERIES_MAX_ROWS` (default 2,000,000).

### `/api/history/export.csv`
Same filters as `/readings` (except paging); downloads `trustguard_history.csv`. Refused with 422 above `HISTORY_EXPORT_MAX_ROWS` (default 500,000). Cell values that would start a spreadsheet formula (`=`, `+`, `-`, `@`) get a leading `'`.

### Examples
```bash
curl 'localhost:8000/api/history/sensors'
curl 'localhost:8000/api/history/readings?sensor_id=7&range=6h&limit=100'
curl 'localhost:8000/api/history/readings?sensor_id=7&start=2026-10-24T08:00:00Z&end=2026-10-24T09:00:00Z&order=asc'
curl 'localhost:8000/api/history/sensors/7/series?range=24h&max_points=200'
curl -o history.csv 'localhost:8000/api/history/export.csv?machine_id=1&range=7d&source=hardware'
```
The older `GET /api/readings?sensor_id=&minutes=` still works unchanged.
