"""
Sensor Data Simulator
======================
Generates realistic temperature / vibration / pressure / current / rpm
readings without needing physical hardware. Supports five scenarios:

    normal   - stable readings with tiny natural noise
    noisy    - normal signal with amplified random noise
    drift    - the sensor's baseline slowly wanders away from truth
    failure  - the sensor reports a stuck, flat-lined, or wildly wrong value
    machine_fault - every sensor shows a consistent, genuine machine problem (not a sensor fault)
    missing  - the sensor simply fails to report (null reading)

The same output shape is used whether data comes from this simulator or a
real ESP32 over MQTT, so the rest of the pipeline (trust engine, ML, etc.)
never needs to know the difference.
"""
import math
import random
import time
from dataclasses import dataclass

# Baseline "healthy" operating ranges per sensor type.
BASELINES = {
    "temperature": {"mean": 65.0, "std": 1.5, "unit": "°C"},
    "vibration": {"mean": 2.5, "std": 0.3, "unit": "mm/s"},
    "pressure": {"mean": 100.0, "std": 3.0, "unit": "kPa"},
    "current": {"mean": 12.0, "std": 0.5, "unit": "A"},
    "rpm": {"mean": 1750.0, "std": 25.0, "unit": "RPM"},
}

SCENARIOS = ["normal", "noisy", "drift", "failure", "missing", "machine_fault"]

# machine_fault: a *genuine* machine problem (bearing wear / overload) seen consistently by every
# sensor. Target value each sensor ramps towards. Unlike the sensor-fault scenarios, the signals stay
# smooth and mutually consistent, so trust should stay high while risk rises.
MACHINE_FAULT_TARGET = {"temperature": 95.0, "vibration": 7.0, "pressure": 112.0, "current": 18.0, "rpm": 1700.0}


@dataclass
class SimulatedReading:
    sensor_type: str
    value: float | None
    raw_value: float | None
    is_missing: bool
    is_outlier: bool
    scenario: str


class SensorSimulator:
    """
    Stateful simulator - keeps a per-sensor drift offset and failure state so
    that scenarios evolve realistically across multiple calls instead of
    being independent random draws every tick.
    """

    def __init__(self):
        self._drift_offset: dict[str, float] = {}
        self._stuck_value: dict[str, float] = {}
        self._fault_level: dict[str, float] = {}
        self._t0 = time.time()

    def _phase(self, sensor_type: str) -> float:
        """A slow sine wave so 'normal' data still looks organic on a chart."""
        elapsed = time.time() - self._t0
        freq = {"temperature": 0.002, "vibration": 0.01, "pressure": 0.003,
                "current": 0.004, "rpm": 0.001}.get(sensor_type, 0.002)
        return math.sin(elapsed * freq * 2 * math.pi)

    def generate(self, sensor_type: str, sensor_key: str, scenario: str = "normal") -> SimulatedReading:
        if sensor_type not in BASELINES:
            raise ValueError(f"Unknown sensor_type: {sensor_type}")
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")

        base = BASELINES[sensor_type]
        mean, std = base["mean"], base["std"]
        organic = self._phase(sensor_type) * std * 0.8

        if scenario == "normal":
            value = random.gauss(mean + organic, std * 0.4)
            return SimulatedReading(sensor_type, round(value, 3), round(value, 3), False, False, scenario)

        if scenario == "noisy":
            value = random.gauss(mean + organic, std * 3.5)
            is_outlier = abs(value - mean) > std * 3
            return SimulatedReading(sensor_type, round(value, 3), round(value, 3), False, is_outlier, scenario)

        if scenario == "drift":
            # Slowly accumulating bias that never resets on its own.
            self._drift_offset[sensor_key] = self._drift_offset.get(sensor_key, 0.0) + std * 0.05
            value = mean + organic + self._drift_offset[sensor_key]
            return SimulatedReading(sensor_type, round(value, 3), round(value, 3), False, False, scenario)

        if scenario == "failure":
            # Sensor gets "stuck" reporting the same (or a nonsensical) value.
            if sensor_key not in self._stuck_value:
                self._stuck_value[sensor_key] = mean * random.choice([0.0, 2.5, -1.0])
            raw = random.gauss(mean, std)  # what the real physical value probably was
            return SimulatedReading(sensor_type, self._stuck_value[sensor_key], round(raw, 3), False, True, scenario)

        if scenario == "missing":
            raw = random.gauss(mean, std)
            return SimulatedReading(sensor_type, None, round(raw, 3), True, False, scenario)

        if scenario == "machine_fault":
            level = min(1.0, self._fault_level.get(sensor_key, 0.0) + 0.4)  # reaches full effect in 3 ticks
            self._fault_level[sensor_key] = level
            target = MACHINE_FAULT_TARGET[sensor_type]
            value = random.gauss(mean + (target - mean) * level, std * 0.4)
            return SimulatedReading(sensor_type, round(value, 3), round(value, 3), False, False, scenario)

        raise AssertionError("unreachable")

    def reset(self, sensor_key: str):
        self._drift_offset.pop(sensor_key, None)
        self._stuck_value.pop(sensor_key, None)
        self._fault_level.pop(sensor_key, None)


# Module-level singleton so drift/failure state persists across API calls
# within the same running backend process.
simulator = SensorSimulator()
