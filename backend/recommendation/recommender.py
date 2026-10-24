"""
Recommendation Engine (Decision Engine)
==========================================
Turns (Failure Risk, Prediction Confidence, sensor status) into one of four
explainable actions, exactly as specified in the architecture doc:

  - High risk + reliable sensors  -> Schedule preventive maintenance
  - High risk + unreliable sensor -> Verify / recalibrate sensor first
  - Normal                        -> Continue operation and monitor
  - Sensor failure                -> Inspect or replace sensor
"""
from dataclasses import dataclass

HIGH_RISK_THRESHOLD = 60.0
LOW_CONFIDENCE_THRESHOLD = 55.0
SENSOR_FAILURE_TRUST_THRESHOLD = 25.0


@dataclass
class Recommendation:
    action: str
    recommendation_type: str  # maps to Maintenance.recommendation_type
    reasoning: str
    severity: str  # info | warning | critical


def recommend(
    *,
    failure_risk: float,
    prediction_confidence: float,
    min_sensor_trust: float,
    cross_sensor_disagreement: bool,
    cross_verdict: str | None = None,
) -> Recommendation:
    # Outright sensor failure takes priority - a dead/faulty sensor blinds
    # every downstream decision until it's fixed.
    if min_sensor_trust < SENSOR_FAILURE_TRUST_THRESHOLD:
        return Recommendation(
            action="Inspect or replace sensor",
            recommendation_type="sensor_replacement",
            reasoning=(
                f"A sensor's trust score has dropped to {min_sensor_trust:.0f}%, "
                "which is below the reliability floor. Downstream predictions "
                "cannot be trusted until this is resolved."
            ),
            severity="critical",
        )

    high_risk = failure_risk >= HIGH_RISK_THRESHOLD
    low_confidence = prediction_confidence < LOW_CONFIDENCE_THRESHOLD

    ambiguous = cross_verdict == "ambiguous"
    if high_risk and low_confidence:
        return Recommendation(
            action="Verify both sensors first" if ambiguous else "Verify or recalibrate sensor first",
            recommendation_type="sensor_recalibration",
            reasoning=(
                f"Failure Risk is high ({failure_risk:.0f}%) but Prediction Confidence "
                f"is only {prediction_confidence:.0f}% because sensor data quality is "
                "questionable"
                + (" and the two sensors disagree, so it cannot be told which one is wrong" if ambiguous
                   else " and sensors disagree with each other" if cross_sensor_disagreement else "")
                + ". Recalibrate or verify sensors before acting on this risk score."
            ),
            severity="warning",
        )

    if high_risk and not low_confidence:
        return Recommendation(
            action="Schedule preventive maintenance",
            recommendation_type="preventive_maintenance",
            reasoning=(
                f"Failure Risk is high ({failure_risk:.0f}%) and sensor data is reliable "
                f"(Prediction Confidence {prediction_confidence:.0f}%). Preventive "
                "maintenance is recommended before an unplanned failure occurs."
            ),
            severity="critical",
        )

    return Recommendation(
        action="Continue operation and monitor",
        recommendation_type="monitor",
        reasoning=(
            f"Failure Risk is within normal range ({failure_risk:.0f}%) with "
            f"Prediction Confidence at {prediction_confidence:.0f}%. No action needed "
            "beyond routine monitoring."
        ),
        severity="info",
    )
