"""
Per-sensor calibration for REAL hardware readings (simulation is never calibrated).

    calibrated = raw * scale + offset

Configured in the backend .env as JSON, keyed by sensor type or by "DEVICE_ID:sensor_type" (device key wins):
    SENSOR_CALIBRATION={"vibration": {"scale": 6.0, "offset": 0.0}, "ESP32-A1:temperature": {"scale": 1.0, "offset": -0.4}}

Why: the trust/risk logic is tuned to the simulator's scale (vibration = mm/s, healthy mean 2.5), while the ESP32
accelerometer reports RMS acceleration in m/s^2. These are different physical quantities, so there is no exact
conversion; calibration maps your machine's *measured healthy baseline* onto the scale the model expects.
Use tools/calibrate_baseline.py to compute it. Calibrated vibration is an "index", not a true mm/s measurement.
The device's original value is kept in sensor_readings.raw_value.
"""
import json
import logging
import math
import os

logger = logging.getLogger("trustguard.calibration")
_cache: dict = {"raw": None, "table": {}}


def _table() -> dict:
    raw = os.getenv("SENSOR_CALIBRATION", "")
    if raw == _cache["raw"]:
        return _cache["table"]
    table: dict = {}
    if raw.strip():
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("must be a JSON object")
            for key, cfg in data.items():
                scale, offset = float(cfg.get("scale", 1.0)), float(cfg.get("offset", 0.0))
                if not (math.isfinite(scale) and math.isfinite(offset)) or scale == 0:
                    raise ValueError(f"{key}: scale must be non-zero and values finite")
                table[key] = (scale, offset)
        except Exception as exc:  # bad config must never break ingestion: log and run uncalibrated
            logger.error("Ignoring invalid SENSOR_CALIBRATION (%s)", exc)
            table = {}
    _cache.update(raw=raw, table=table)
    return table


def calibrate(sensor_type: str, device_id: str | None, value: float | None) -> tuple[float | None, bool]:
    """Returns (value, was_calibrated). None (missing reading) passes through untouched."""
    if value is None:
        return None, False
    table = _table()
    cfg = table.get(f"{device_id}:{sensor_type}") or table.get(sensor_type)
    if not cfg:
        return value, False
    return round(value * cfg[0] + cfg[1], 4), True


def is_calibrated(sensor_type: str, device_id: str | None) -> bool:
    """True if a SENSOR_CALIBRATION entry applies to this device/sensor type (device key wins)."""
    table = _table()
    return bool(table.get(f"{device_id}:{sensor_type}") or table.get(sensor_type))
