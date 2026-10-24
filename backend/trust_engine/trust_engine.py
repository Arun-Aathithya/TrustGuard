"""
Sensor Trust Engine — Core Module
===================================
Calculates a dynamic Sensor Trust Score (0-100%) from six weighted factors:

    consistency        - how stable readings are relative to their own recent history
    noise               - how much high-frequency jitter is present
    drift               - whether the running baseline is wandering away from initial baseline
    missing             - fraction of recent expected readings that never arrived
    cross_agreement     - filled in by cross_sensor.py, defaults to neutral here
    communication       - recency of the last reading (a "heartbeat" signal)

Each sub-score is 0-100. The overall Trust Score is a weighted average.
Example from the architecture doc: Temperature Trust = 42% -> unreliable sensor.
"""
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

WEIGHTS = {
    "consistency": 0.25,
    "noise": 0.20,
    "drift": 0.20,
    "missing": 0.15,
    "cross_agreement": 0.10,
    "communication": 0.10,
}


@dataclass
class TrustBreakdown:
    consistency_score: float
    noise_score: float
    drift_score: float
    missing_score: float
    cross_agreement_score: float = 100.0  # overwritten by cross_sensor validation
    communication_score: float = 100.0

    @property
    def trust_score(self) -> float:
        total = (
            self.consistency_score * WEIGHTS["consistency"]
            + self.noise_score * WEIGHTS["noise"]
            + self.drift_score * WEIGHTS["drift"]
            + self.missing_score * WEIGHTS["missing"]
            + self.cross_agreement_score * WEIGHTS["cross_agreement"]
            + self.communication_score * WEIGHTS["communication"]
        )
        return round(max(0.0, min(100.0, total)), 2)

    def label(self) -> str:
        score = self.trust_score
        if score >= 80:
            return "reliable"
        if score >= 50:
            return "degraded"
        return "unreliable"


def weighted_trust(*, consistency: float, noise: float, drift: float, missing: float, cross_agreement: float, communication: float) -> float:
    """Same weighting as TrustBreakdown.trust_score, for re-scoring a stored row."""
    return round(max(0.0, min(100.0, consistency * WEIGHTS["consistency"] + noise * WEIGHTS["noise"] + drift * WEIGHTS["drift"]
                              + missing * WEIGHTS["missing"] + cross_agreement * WEIGHTS["cross_agreement"]
                              + communication * WEIGHTS["communication"])), 2)


FLATLINE_EPSILON = 1e-6  # relative std below this = suspiciously perfect, not "stable"


def _is_flatlined(values: list[float]) -> bool:
    """
    Real physical sensors always carry a tiny amount of natural jitter.
    A run of readings with essentially zero variance is a classic symptom of
    a stuck/failed sensor (e.g. reporting the same cached value every tick),
    not a sign of a great sensor - so it must NOT score as "perfectly stable".
    """
    if len(values) < 4:
        return False
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if mean == 0:
        return std < FLATLINE_EPSILON
    return abs(std / mean) < FLATLINE_EPSILON


def _score_from_cv(values: list[float]) -> float:
    """Consistency: lower coefficient-of-variation (relative to a healthy CV) => higher score."""
    if len(values) < 2:
        return 100.0
    if _is_flatlined(values):
        return 10.0  # dead-flat signal is a red flag, not stability
    mean = statistics.fmean(values)
    if mean == 0:
        return 100.0
    std = statistics.pstdev(values)
    cv = abs(std / mean)
    # A CV of 0.02 (2%) is very stable -> ~100. A CV of 0.30+ -> near 0.
    score = 100.0 * max(0.0, 1.0 - (cv / 0.30))
    return round(score, 2)


def _score_from_noise(values: list[float]) -> float:
    """Noise: measures jitter as the std-dev of first differences (sample to sample jumps)."""
    if len(values) < 3:
        return 100.0
    if _is_flatlined(values):
        return 10.0  # zero jitter from a real-world sensor reads as "stuck", not "clean"
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    mean_val = statistics.fmean(values) or 1.0
    relative_jitter = statistics.fmean(diffs) / abs(mean_val)
    score = 100.0 * max(0.0, 1.0 - (relative_jitter / 0.15))
    return round(score, 2)


def _score_from_drift(values: list[float], baseline_mean: float | None) -> float:
    """Drift: compares the recent window's mean against a longer-term baseline mean."""
    if not values or baseline_mean is None or baseline_mean == 0:
        return 100.0
    recent_mean = statistics.fmean(values)
    relative_shift = abs(recent_mean - baseline_mean) / abs(baseline_mean)
    score = 100.0 * max(0.0, 1.0 - (relative_shift / 0.25))
    return round(score, 2)


def _score_from_missing(expected_count: int, actual_count: int) -> float:
    if expected_count <= 0:
        return 100.0
    missing_ratio = max(0.0, (expected_count - actual_count) / expected_count)
    return round(100.0 * (1.0 - missing_ratio), 2)


def _score_from_communication(last_reading_at: datetime | None, *, stale_after_seconds: int = 120) -> float:
    if last_reading_at is None:
        return 0.0
    if last_reading_at.tzinfo is None:
        last_reading_at = last_reading_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last_reading_at).total_seconds()
    if age <= 0:
        return 100.0
    score = 100.0 * max(0.0, 1.0 - (age / (stale_after_seconds * 3)))
    return round(score, 2)


SENSOR_SUSPECT_FACTOR = 0.85  # extra reduction for the one sensor the majority outvotes
SUSPECT_CROSS_AGREEMENT = 30.0


def apply_cross_sensor(rows: dict, verdict: str, moved: list[str], suspects: list[str]) -> dict:
    """
    Adjust per-sensor TrustBreakdown-like rows in place for the cross-sensor verdict. `rows` maps sensor_type to an
    object with the six *_score fields and trust_score (a SensorTrust row works).

      machine_change : sensors that moved together are NOT punished. Their drift sub-score (a shift away from the
                       baseline) is reset to 100, because the shift is shared process change, not sensor drift.
      sensor_suspect : only the outvoted sensor loses cross-agreement and a further 15 %.
      ambiguous / agree / insufficient : nothing changes (two sensors cannot outvote each other).
    Returns {sensor_type: reason} for every row that was changed, so callers can explain it.
    """
    changed: dict[str, str] = {}
    if verdict == "machine_change":
        for t in moved:
            r = rows.get(t)
            if r is None:
                continue
            if r.drift_score < 100.0 or r.cross_agreement_score < 100.0:
                r.drift_score, r.cross_agreement_score = 100.0, 100.0
                r.trust_score = weighted_trust(consistency=r.consistency_score, noise=r.noise_score, drift=r.drift_score,
                                               missing=r.missing_score, cross_agreement=r.cross_agreement_score,
                                               communication=r.communication_score)
                changed[t] = "shift shared with other sensors: treated as machine change, not penalised"
    elif verdict == "sensor_suspect":
        for t in suspects:
            r = rows.get(t)
            if r is None:
                continue
            r.cross_agreement_score = SUSPECT_CROSS_AGREEMENT
            base = weighted_trust(consistency=r.consistency_score, noise=r.noise_score, drift=r.drift_score,
                                  missing=r.missing_score, cross_agreement=r.cross_agreement_score,
                                  communication=r.communication_score)
            r.trust_score = round(base * SENSOR_SUSPECT_FACTOR, 2)
            changed[t] = "outvoted by the other sensors: cross-agreement lowered"
    return changed


def compute_trust(
    *,
    recent_values: list[float],
    baseline_mean: float | None,
    expected_count: int,
    actual_count: int,
    last_reading_at: datetime | None,
) -> TrustBreakdown:
    """
    Main entry point: given a window of recent clean readings plus metadata,
    compute the full trust breakdown for one sensor.
    """
    return TrustBreakdown(
        consistency_score=_score_from_cv(recent_values),
        noise_score=_score_from_noise(recent_values),
        drift_score=_score_from_drift(recent_values, baseline_mean),
        missing_score=_score_from_missing(expected_count, actual_count),
        communication_score=_score_from_communication(last_reading_at),
    )
