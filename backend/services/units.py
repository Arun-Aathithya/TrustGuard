"""
Unit consistency for sensor readings.

The simulator, trust thresholds and ML model all work in the simulator's units. For vibration that is
RMS VELOCITY in mm/s (healthy mean 2.5). The ESP32 accelerometer firmware reports RMS ACCELERATION in m/s^2.
These are different physical quantities:

  * Velocity can only be derived from acceleration with knowledge of the frequency content
    (for one dominant frequency f: v_rms = a_rms / (2*pi*f)). A broadband RMS acceleration over ~200 ms
    cannot be converted exactly, so there is NO universal conversion factor.
  * What this project offers instead is a per-machine *calibration*: map the measured healthy baseline onto
    the model's healthy value (tools/calibrate_baseline.py). The result is an INDEX on the mm/s scale, not mm/s.

So a hardware vibration sensor is in one of three states:
  ok               - declared unit already matches the model's unit (e.g. a real mm/s velocity sensor), or not vibration
  calibrated_index - raw acceleration, with a SENSOR_CALIBRATION entry applied (shown as "idx", not "mm/s")
  unconverted      - raw acceleration (or unit unknown) with NO calibration: values are NOT comparable with the
                     mm/s baseline, so they must not feed risk or cross-sensor checks.
"""
from services.calibration import is_calibrated
from simulation.simulator import BASELINES

ACCEL_UNITS = {"m/s2", "m/s^2", "m/s²", "g", "mg", "gal"}
INDEX_UNIT = "idx"


def _norm(unit: str | None) -> str:
    return (unit or "").strip().lower().replace(" ", "")


def unit_assessment(sensor_type: str, data_source: str | None, unit: str | None, device_id: str | None) -> dict:
    """-> {status, display_unit, warning, note}. Simulated sensors are always 'ok' (they already use model units)."""
    base_unit = BASELINES.get(sensor_type, {}).get("unit", unit or "")
    ok = {"status": "ok", "display_unit": unit or base_unit, "warning": None, "note": None}
    if (data_source or "simulation") != "hardware" or sensor_type != "vibration":
        return ok
    u = _norm(unit)
    if u == _norm(base_unit):  # declared as mm/s: a genuine velocity sensor
        return ok
    declared = unit or "unknown unit"
    if is_calibrated(sensor_type, device_id):
        return {
            "status": "calibrated_index", "display_unit": INDEX_UNIT, "warning": None,
            "note": f"Raw {declared} acceleration mapped onto the mm/s baseline scale by calibration. "
                    "This is a relative index, not a true velocity in mm/s.",
        }
    why = "an acceleration unit" if u in ACCEL_UNITS else "an undeclared or different unit"
    return {
        "status": "unconverted", "display_unit": unit or "?",
        "warning": f"Units not converted: reported in {declared} ({why}) but the model expects {base_unit}. "
                   "Calibrate this sensor (tools/calibrate_baseline.py) before its readings are mixed with mm/s data.",
        "note": "Excluded from risk and cross-sensor checks until calibrated.",
    }


def excluded_from_models(assessment: dict) -> bool:
    return assessment["status"] == "unconverted"
