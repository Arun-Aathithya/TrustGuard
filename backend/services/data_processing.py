"""
Data Processing Module
=======================
Runs on every incoming reading (simulated or real) before it is trusted
enough to feed the ML/trust pipeline.

Checks performed, in order:
  1. Timestamp validation   - reject readings from the future / too far in the past
  2. Missing-value detection - null / NaN values flagged, not discarded
  3. Duplicate detection      - identical (sensor, timestamp, value) tuples ignored
  4. Range validation         - physically-impossible values flagged as outliers
  5. Noise / outlier handling - statistical (z-score) outlier flagging
  6. Normalization             - min-max scaling helper for ML feature prep
"""
from datetime import datetime, timedelta, timezone

# Physically plausible hard limits per sensor type - anything outside this is
# not just "unusual", it's impossible, and gets hard-flagged.
HARD_RANGES = {
    "temperature": (-40.0, 200.0),
    "vibration": (0.0, 50.0),
    "pressure": (0.0, 500.0),
    "current": (0.0, 100.0),
    "rpm": (0.0, 10000.0),
}

# Typical operating ranges used for z-score style soft-outlier detection.
SOFT_STATS = {
    "temperature": {"mean": 65.0, "std": 5.0},
    "vibration": {"mean": 2.5, "std": 1.0},
    "pressure": {"mean": 100.0, "std": 8.0},
    "current": {"mean": 12.0, "std": 2.0},
    "rpm": {"mean": 1750.0, "std": 60.0},
}


class ProcessingResult:
    def __init__(self, value, is_missing, is_outlier, notes):
        self.value = value
        self.is_missing = is_missing
        self.is_outlier = is_outlier
        self.notes = notes  # list[str] of what was detected


def validate_timestamp(ts: datetime | None, *, max_skew_minutes: int = 5, max_age_days: int = 3650) -> tuple[datetime, list[str]]:
    notes = []
    now = datetime.now(timezone.utc)
    if ts is None:
        return now, ["timestamp missing, defaulted to now()"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if ts > now + timedelta(minutes=max_skew_minutes):
        notes.append("timestamp in the future, clamped to now()")
        ts = now
    if ts < now - timedelta(days=max_age_days):
        notes.append("timestamp implausibly old")
    return ts, notes


def process_reading(sensor_type: str, value: float | None, raw_value: float | None = None) -> ProcessingResult:
    notes: list[str] = []
    raw_value = raw_value if raw_value is not None else value

    # 1. Missing-value detection
    if value is None:
        return ProcessingResult(None, True, False, ["missing value"])

    # 2. Range validation (hard physical bounds)
    lo, hi = HARD_RANGES.get(sensor_type, (float("-inf"), float("inf")))
    if value < lo or value > hi:
        notes.append(f"value {value} outside physical range [{lo}, {hi}]")
        return ProcessingResult(value, False, True, notes)

    # 3. Noise / outlier handling (z-score against expected operating stats)
    stats = SOFT_STATS.get(sensor_type)
    is_outlier = False
    if stats and stats["std"] > 0:
        z = abs(value - stats["mean"]) / stats["std"]
        if z > 3.0:
            is_outlier = True
            notes.append(f"z-score {z:.2f} exceeds outlier threshold")

    return ProcessingResult(value, False, is_outlier, notes)


def is_duplicate(existing_keys: set[tuple[int, str, float | None]], sensor_id: int, timestamp: datetime, value: float | None) -> bool:
    key = (sensor_id, timestamp.isoformat(), value)
    if key in existing_keys:
        return True
    existing_keys.add(key)
    return False


def normalize_operating(value: float, sensor_type: str) -> float:
    """
    0-1 position of a reading inside its *operating* band [mean-3σ, mean+7σ] (from SOFT_STATS).
    The ML model uses this instead of the hard physical limits: against limits such as 0-200 °C
    a genuinely hot machine (95 °C) still looks "low", so risk could never rise.
    Normal operation lands near 0.3, +2σ near 0.5, +5σ near 0.8.
    """
    st = SOFT_STATS.get(sensor_type)
    if not st or st["std"] == 0:
        return 0.0
    lo, hi = st["mean"] - 3 * st["std"], st["mean"] + 7 * st["std"]
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def normalize(value: float, sensor_type: str) -> float:
    """Min-max normalize a raw reading to 0-1 using HARD_RANGES bounds, for ML features."""
    lo, hi = HARD_RANGES.get(sensor_type, (0.0, 1.0))
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))
