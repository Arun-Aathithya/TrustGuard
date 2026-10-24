"""
Hardware payload parsing & validation (pure functions - no database access).

Expected JSON from a device (full contract in docs/MQTT.md):
    {"device_id": "ESP32-A1",                                 # required
     "value": 71.4,                                           # required: number, or null = sensor read failed
     "timestamp": "2026-10-18T12:00:00Z",                     # optional: ISO-8601 or epoch seconds/ms
     "sensor_id": 7,                                          # optional on MQTT (the topic identifies the sensor); needed over HTTP
                                                              #   when a device has several sensors of one type
     "sensor_type": "temperature",                            # optional; must match the configured sensor
     "unit": "°C"}                                            # optional; must match the configured sensor
"""
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

MAX_PAYLOAD_BYTES = 2048
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,80}$")
MIN_PLAUSIBLE_EPOCH = 1_000_000_000  # Sep 2001 - below this the device clock is certainly unsynced


class PayloadError(Exception):
    def __init__(self, event_type: str, detail: str):
        super().__init__(detail)
        self.event_type = event_type
        self.detail = detail


@dataclass
class ParsedPayload:
    device_id: str
    sensor_type: str | None
    value: float | None
    timestamp: datetime | None  # None => caller uses server receive time
    flags: list[str] = field(default_factory=list)
    sensor_id: int | None = None
    unit: str | None = None


def normalize_unit(unit: str | None) -> str:
    """'m/s²', 'M/S2', 'm/s^2' -> 'm/s2'; '°C', 'C', 'degC' -> 'c'. Used only to compare units."""
    u = (unit or "").strip().lower().replace(" ", "").replace("²", "2").replace("^2", "2").replace("°", "")
    return {"degc": "c", "celsius": "c"}.get(u, u)


def same_unit(a: str | None, b: str | None) -> bool:
    return normalize_unit(a) == normalize_unit(b)


def _parse_timestamp(raw) -> tuple[datetime | None, str | None]:
    """Returns (timestamp, flag). flag is set when the device timestamp had to be replaced."""
    if raw is None:
        return None, "timestamp_missing"
    if isinstance(raw, bool):
        raise PayloadError("malformed", "timestamp has an invalid type")
    if isinstance(raw, (int, float)):
        if not math.isfinite(raw):
            raise PayloadError("malformed", "timestamp is not finite")
        seconds = raw / 1000.0 if raw > 1e11 else float(raw)
        if seconds < MIN_PLAUSIBLE_EPOCH:
            return None, "timestamp_replaced: device clock not synced"
        return datetime.fromtimestamp(seconds, tz=timezone.utc), None
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            raise PayloadError("malformed", "timestamp is not valid ISO-8601")
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.timestamp() < MIN_PLAUSIBLE_EPOCH:
            return None, "timestamp_replaced: device clock not synced"
        return ts.astimezone(timezone.utc), None
    raise PayloadError("malformed", "timestamp has an invalid type")


def parse_payload(raw: bytes | str | dict) -> ParsedPayload:
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise PayloadError("malformed", f"payload larger than {MAX_PAYLOAD_BYTES} bytes")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PayloadError("malformed", "payload is not valid UTF-8")
    if isinstance(raw, str):
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise PayloadError("malformed", f"payload larger than {MAX_PAYLOAD_BYTES} bytes")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            raise PayloadError("malformed", "payload is not valid JSON")
    else:
        obj = raw
    if not isinstance(obj, dict):
        raise PayloadError("malformed", "payload must be a JSON object")

    device_id = obj.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID_RE.match(device_id):
        raise PayloadError("malformed", "device_id is required (3-80 chars: letters, digits, _ . -)")

    sensor_type = obj.get("sensor_type")
    if sensor_type is not None and not isinstance(sensor_type, str):
        raise PayloadError("malformed", "sensor_type must be a string")

    sensor_id = obj.get("sensor_id")
    if sensor_id is not None:
        if isinstance(sensor_id, bool) or not isinstance(sensor_id, int) or sensor_id < 1:
            raise PayloadError("malformed", "sensor_id must be a positive whole number")

    unit = obj.get("unit")
    if unit is not None and (not isinstance(unit, str) or len(unit) > 20):
        raise PayloadError("malformed", "unit must be a short string")

    if "value" not in obj:
        raise PayloadError("malformed", "value field is missing (send null if the sensor read failed)")
    value = obj["value"]
    if value is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadError("malformed", "value must be a number or null")
        if not math.isfinite(value):
            raise PayloadError("invalid_value", "value is NaN or infinite")
        value = float(value)

    ts, flag = _parse_timestamp(obj.get("timestamp"))
    flags = [flag] if flag else []
    return ParsedPayload(device_id=device_id, sensor_type=sensor_type.strip().lower() if sensor_type else None,
                         value=value, timestamp=ts, flags=flags, sensor_id=sensor_id, unit=unit.strip() if unit else None)


def classify_timing(ts: datetime, now: datetime, *, delayed_after_s: float, max_age_s: float, future_skew_s: float):
    """Returns (status, adjusted_ts): status in ok | delayed | too_old | future."""
    age = (now - ts).total_seconds()
    if age < -future_skew_s:
        return "future", now
    if age > max_age_s:
        return "too_old", ts
    if age > delayed_after_s:
        return "delayed", ts
    return "ok", ts
