"""
Prediction Confidence
======================
Three quantities stay independent:

  failure risk          - from the process readings ONLY (ml/predictor.py). Sensor trust is not an input.
  sensor trust          - per-sensor data reliability (trust_engine).
  prediction confidence - how far to rely on the risk figure. THIS is the only place trust acts on a prediction.

Example: risk 78 %, confidence 43 %  ->  "the machine may be in trouble, but the data behind that number is shaky".

Confidence is derived from average and worst-sensor trust, then reduced for:
  * sensors that conflict (verdict sensor_suspect / ambiguous), and
  * sensors left out of the risk calculation (e.g. vibration still in m/s^2 and not calibrated), because the risk then
    rests on fewer inputs. Without any inputs at all there is nothing to be confident about.
A machine_change verdict does NOT reduce confidence: sensors agreeing on a real shift is reassuring about the data.
"""
from dataclasses import dataclass

CONFLICT_FACTOR = 0.7
EXCLUDED_FACTOR = 0.8


@dataclass
class ConfidenceResult:
    prediction_confidence: float  # 0-100
    overall_trust: float  # 0-100
    explanation: str


def compute_confidence(
    *,
    trust_scores: list[float],
    cross_sensor_disagreement: bool,
    cross_verdict: str | None = None,
    excluded_sensor_count: int = 0,
    usable_sensor_count: int | None = None,
) -> ConfidenceResult:
    if not trust_scores:
        return ConfidenceResult(0.0, 0.0, "no sensor trust data available")
    if usable_sensor_count == 0:
        avg = sum(trust_scores) / len(trust_scores)
        return ConfidenceResult(0.0, round(avg, 2), "no sensor currently provides usable data for the risk estimate")

    avg_trust = sum(trust_scores) / len(trust_scores)
    worst_trust = min(trust_scores)

    # The average counts most, but one bad sensor pulls it down hard: it can poison an otherwise good picture.
    confidence = 0.6 * avg_trust + 0.4 * worst_trust

    reasons = []
    if cross_sensor_disagreement:
        confidence *= CONFLICT_FACTOR
        reasons.append("the two sensors disagree and cannot be told apart" if cross_verdict == "ambiguous"
                       else "one sensor is outvoted by the others")
    if excluded_sensor_count:
        confidence *= EXCLUDED_FACTOR
        reasons.append(f"{excluded_sensor_count} sensor(s) left out of the risk estimate (units not calibrated)")
    if worst_trust < 50:
        reasons.append(f"at least one sensor has low trust ({worst_trust:.0f}%)")
    if cross_verdict == "machine_change":
        reasons.append("sensors moved together, consistent with a real machine change")
    if not reasons:
        reasons.append("all sensors reporting consistent, reliable data")

    return ConfidenceResult(round(max(0.0, min(100.0, confidence)), 2), round(avg_trust, 2), "; ".join(reasons))
