"""
Cross-Sensor Validation
=========================
Compares the sensors of one machine to decide WHO is wrong when something looks abnormal:
the machine, or one sensor. A sensor is said to have "moved" when its latest value is more than 2 sigma from
its normal operating level, or when it has drifted well away from its own baseline.

    verdict           when                                              effect on trust
    ----------------  ------------------------------------------------  ---------------------------------------
    agree             nothing moved                                     none
    machine_change    two or more sensors moved together                 none: the shift is real process change,
                                                                         so drift is NOT charged to any sensor
    sensor_suspect    exactly one moved, and two or more others are      that sensor only: cross-agreement down
                      normal                                              (the majority outvotes it)
    ambiguous         exactly one moved and exactly one is normal        none: with two sensors there is no
                      (i.e. the two sensors disagree)                     majority, so nobody is blamed. Only
                                                                         prediction confidence is reduced.
    insufficient      fewer than two sensors have data                   none

Limits (also stated in the UI): a genuine fault that shows up on ONE physical channel only (e.g. a local bearing
hot spot) looks identical to a faulty sensor; and sensors that move together because they share a cause
(a miswired supply, one broken ADC) look like a machine change. Cross-validation is evidence, not proof.
"""
from dataclasses import dataclass, field

from services.data_processing import SOFT_STATS

AGREE, MACHINE_CHANGE, SENSOR_SUSPECT, AMBIGUOUS, INSUFFICIENT = "agree", "machine_change", "sensor_suspect", "ambiguous", "insufficient"
DRIFT_MOVED_BELOW = 50.0  # a drift sub-score under this counts as "this sensor has moved away from its baseline"


def _status(sensor_type: str, value: float) -> str:
    stats = SOFT_STATS.get(sensor_type)
    if not stats or stats["std"] == 0:
        return "normal"
    z = (value - stats["mean"]) / stats["std"]
    if z > 2.0:
        return "high"
    if z < -2.0:
        return "low"
    return "normal"


@dataclass
class CrossSensorResult:
    verdict: str
    detail: str
    moved_sensor_types: list[str] = field(default_factory=list)
    suspect_sensor_types: list[str] = field(default_factory=list)  # blamed: only for sensor_suspect
    normal_sensor_types: list[str] = field(default_factory=list)

    @property
    def disagreement(self) -> bool:
        """Sensors conflict (one blamed, or nobody can be). Lowers prediction confidence."""
        return self.verdict in (SENSOR_SUSPECT, AMBIGUOUS)

    @property
    def machine_change(self) -> bool:
        return self.verdict == MACHINE_CHANGE

    @property
    def outlier_sensor_types(self) -> list[str]:
        """Backwards-compatible name: sensors that moved."""
        return self.moved_sensor_types


def validate(latest_by_type: dict[str, float], drifting_types: set[str] | frozenset[str] = frozenset()) -> CrossSensorResult:
    """
    latest_by_type: e.g. {"temperature": 92.1, "vibration": 2.4, "pressure": 99.5}   (only sensors with usable data)
    drifting_types: sensor types whose own drift sub-score is low (they moved even if the latest value is still in band)
    """
    types = list(latest_by_type)
    if len(types) < 2:
        return CrossSensorResult(INSUFFICIENT, "not enough sensors to cross-validate", normal_sensor_types=types)

    moved = [t for t in types if _status(t, latest_by_type[t]) != "normal" or t in drifting_types]
    normal = [t for t in types if t not in moved]

    if not moved:
        return CrossSensorResult(AGREE, "all sensors agree", normal_sensor_types=normal)
    if len(moved) >= 2:
        return CrossSensorResult(
            MACHINE_CHANGE,
            f"{', '.join(moved)} moved together: this looks like a real change in the machine or process, not a sensor fault. "
            "No sensor is penalised for it.",
            moved_sensor_types=moved, normal_sensor_types=normal)
    # exactly one moved
    if len(types) == 2:
        return CrossSensorResult(
            AMBIGUOUS,
            f"The two sensors disagree; cannot tell which is wrong ({moved[0]} moved, {normal[0]} did not). "
            "Inspect both by hand, or add a third sensor so a majority can decide.",
            moved_sensor_types=moved, normal_sensor_types=normal)
    return CrossSensorResult(
        SENSOR_SUSPECT,
        f"{moved[0]} moved while {len(normal)} other sensors stayed normal: the {moved[0]} sensor is the likely fault.",
        moved_sensor_types=moved, suspect_sensor_types=moved, normal_sensor_types=normal)
