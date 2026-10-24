"""
Ingestion Service
====================
The orchestration layer that implements the full pipeline from the
architecture doc:

  Data Processing -> Trust Engine -> Cross-Sensor Validation
    -> ML Prediction -> Confidence Engine -> Decision/Recommendation Engine
    -> Alerts + Maintenance records

Used by both the simulator endpoints and (later) real MQTT/ESP32 ingestion,
so simulated and real hardware data flow through an identical pipeline.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    Alert,
    AlertSeverity,
    AlertType,
    ConnectionStatus,
    Machine,
    MachineStatus,
    Maintenance,
    Prediction,
    Sensor,
    SensorReading,
    SensorTrust,
)
from ml.predictor import build_features, predict_failure_risk
from prediction.confidence import compute_confidence
from recommendation.recommender import recommend
from services.data_processing import process_reading, validate_timestamp
from services.units import excluded_from_models, unit_assessment
from trust_engine.cross_sensor import AMBIGUOUS, DRIFT_MOVED_BELOW, validate as cross_validate
from trust_engine.trust_engine import apply_cross_sensor, compute_trust

TRUST_WINDOW_MINUTES = 15
EXPECTED_READINGS_PER_WINDOW = 15  # roughly 1/min in this simulation cadence


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def ingest_reading(
    db: Session,
    sensor: Sensor,
    raw_value: float | None,
    timestamp: datetime | None = None,
    *,
    source: str | None = None,
    is_delayed: bool = False,
    received_at: datetime | None = None,
) -> SensorReading:
    """Runs one incoming raw reading (simulated or hardware) through the Data Processing Module and persists it."""
    source = source or sensor.data_source or "simulation"
    ts, _notes = validate_timestamp(timestamp)
    result = process_reading(sensor.sensor_type.value, raw_value)

    reading = SensorReading(
        sensor_id=sensor.id,
        value=result.value,
        raw_value=raw_value,
        is_missing=result.is_missing,
        is_outlier=result.is_outlier,
        is_delayed=is_delayed,
        source=source,
        timestamp=ts,
    )
    db.add(reading)

    if source == "hardware":
        sensor.last_seen_at = received_at or datetime.now(timezone.utc)
        if sensor.last_data_at is None or ts > _aware(sensor.last_data_at):
            sensor.last_data_at = ts
        sensor.connection_status = ConnectionStatus.FAULTY if result.is_outlier else ConnectionStatus.ONLINE
    else:
        sensor.last_data_at = ts
        sensor.connection_status = ConnectionStatus.FAULTY if result.is_outlier else ConnectionStatus.SIMULATED
    db.flush()
    return reading


def _recent_window(db: Session, sensor_id: int, minutes: int = TRUST_WINDOW_MINUTES, source: str | None = None) -> list[SensorReading]:
    """Recent readings for one sensor. `source` keeps hardware and simulated history from mixing."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    stmt = select(SensorReading).where(SensorReading.sensor_id == sensor_id, SensorReading.timestamp >= since)
    if source:
        stmt = stmt.where(SensorReading.source == source)
    return list(db.execute(stmt.order_by(SensorReading.timestamp.asc())).scalars())


def compute_and_store_trust(db: Session, sensor: Sensor, machine_baseline: dict[str, float]) -> SensorTrust:
    window = _recent_window(db, sensor.id, source=sensor.data_source)
    clean_values = [r.value for r in window if r.value is not None and not r.is_outlier]
    actual_count = len([r for r in window if not r.is_missing])
    expected_count = max(EXPECTED_READINGS_PER_WINDOW, len(window))

    breakdown = compute_trust(
        recent_values=clean_values[-30:],
        baseline_mean=machine_baseline.get(sensor.sensor_type.value),
        expected_count=expected_count,
        actual_count=actual_count,
        last_reading_at=sensor.last_data_at,
    )

    trust_row = SensorTrust(
        sensor_id=sensor.id,
        machine_id=sensor.machine_id,
        trust_score=breakdown.trust_score,
        consistency_score=breakdown.consistency_score,
        noise_score=breakdown.noise_score,
        drift_score=breakdown.drift_score,
        missing_score=breakdown.missing_score,
        cross_agreement_score=breakdown.cross_agreement_score,
        communication_score=breakdown.communication_score,
    )
    db.add(trust_row)
    db.flush()
    return trust_row


def run_pipeline_for_machine(db: Session, machine: Machine, machine_baseline: dict[str, float]) -> dict:
    """
    Full pipeline for one machine: recompute trust for every sensor, run
    cross-sensor validation, predict failure risk, compute confidence,
    generate a recommendation, and raise alerts/maintenance as needed.
    Returns a summary dict (also used by the dashboard service).
    """
    sensors = list(machine.sensors)
    trust_rows: dict[int, SensorTrust] = {}
    latest_values: dict[str, float] = {}
    excluded: list[dict] = []  # sensors whose values must not be mixed into risk / cross-checks

    for sensor in sensors:
        trust_rows[sensor.id] = compute_and_store_trust(db, sensor, machine_baseline)
        window = _recent_window(db, sensor.id, source=sensor.data_source)
        clean = [r for r in window if r.value is not None]
        if not clean:
            continue
        ua = unit_assessment(sensor.sensor_type.value, sensor.data_source, sensor.unit, sensor.device_id)
        if excluded_from_models(ua):
            # e.g. vibration still in m/s^2: comparing it with a mm/s baseline would be meaningless.
            excluded.append({"sensor_type": sensor.sensor_type.value, "reason": ua["warning"]})
            continue
        latest_values[sensor.sensor_type.value] = clean[-1].value

    by_type = {s.sensor_type.value: trust_rows[s.id] for s in sensors}
    drifting = {t for t in latest_values if by_type[t].drift_score < DRIFT_MOVED_BELOW}
    cross_result = cross_validate(latest_values, drifting)

    # Who is wrong, the machine or one sensor? Sensors that moved together are a machine change and are not
    # penalised; only a sensor outvoted by two or more others is; with just two sensors nobody is blamed.
    apply_cross_sensor(by_type, cross_result.verdict, cross_result.moved_sensor_types, cross_result.suspect_sensor_types)

    trust_scores = [t.trust_score for t in trust_rows.values()] or [100.0]
    min_trust = min(trust_scores)

    # Failure risk uses the process readings only. Trust is NOT an input; it only shapes confidence.
    features = build_features(latest_values)
    failure_risk, model_version = predict_failure_risk(features)

    confidence_result = compute_confidence(
        trust_scores=trust_scores,
        cross_sensor_disagreement=cross_result.disagreement,
        cross_verdict=cross_result.verdict,
        excluded_sensor_count=len(excluded),
        usable_sensor_count=len(latest_values),
    )

    prediction = Prediction(
        machine_id=machine.id,
        failure_risk=failure_risk,
        prediction_confidence=confidence_result.prediction_confidence,
        overall_trust=confidence_result.overall_trust,
        model_version=model_version,
        inputs_json=json.dumps({
            "features": features, "latest_values": latest_values, "excluded_sensors": excluded,
            "cross_sensor": {"verdict": cross_result.verdict, "detail": cross_result.detail,
                             "moved": cross_result.moved_sensor_types, "suspects": cross_result.suspect_sensor_types,
                             "normal": cross_result.normal_sensor_types},
        }),
    )
    db.add(prediction)

    rec = recommend(
        failure_risk=failure_risk,
        prediction_confidence=confidence_result.prediction_confidence,
        min_sensor_trust=min_trust,
        cross_sensor_disagreement=cross_result.disagreement,
        cross_verdict=cross_result.verdict,
    )

    _sync_machine_status(machine, failure_risk, min_trust)
    _raise_alerts_and_maintenance(db, machine, rec, min_trust, sensors, trust_rows, cross_result)

    db.flush()
    return {
        "prediction": prediction,
        "recommendation": rec,
        "cross_result": cross_result,
        "trust_rows": trust_rows,
    }


def _sync_machine_status(machine: Machine, failure_risk: float, min_trust: float):
    # "Down" is a statement about the machine, so it follows risk only. Untrustworthy data can make a machine
    # "at risk" (needs a person to look) but never "down" on its own.
    if failure_risk >= 80:
        machine.status = MachineStatus.DOWN
    elif failure_risk >= 60 or min_trust < 50:
        machine.status = MachineStatus.AT_RISK
    else:
        machine.status = MachineStatus.OPERATIONAL


def _raise_alerts_and_maintenance(db, machine, rec, min_trust, sensors, trust_rows, cross_result):
    if cross_result is not None and cross_result.verdict == AMBIGUOUS:
        _raise_once(db, machine, AlertType.CROSS_DISAGREEMENT, AlertSeverity.WARNING, None, cross_result.detail)
    if rec.recommendation_type == "monitor":
        return  # nothing abnormal, no alert noise

    severity_map = {"info": AlertSeverity.INFO, "warning": AlertSeverity.WARNING, "critical": AlertSeverity.CRITICAL}
    alert_type_map = {
        "sensor_replacement": AlertType.SENSOR_FAULT,
        "sensor_recalibration": AlertType.LOW_CONFIDENCE,
        "preventive_maintenance": AlertType.HIGH_RISK,
    }

    faulty_sensor_id = None
    if cross_result and cross_result.suspect_sensor_types:
        # Only a sensor outvoted by 2+ others is blamed. A machine change or a two-sensor tie blames nobody.
        for s in sensors:
            if s.sensor_type.value in cross_result.suspect_sensor_types:
                faulty_sensor_id = s.id
                break
    elif rec.recommendation_type == "sensor_replacement":
        worst = min(trust_rows.items(), key=lambda kv: kv[1].trust_score)
        faulty_sensor_id = worst[0]

    alert_type = alert_type_map.get(rec.recommendation_type, AlertType.HIGH_RISK)
    severity = severity_map.get(rec.severity, AlertSeverity.WARNING)

    _raise_once(db, machine, alert_type, severity, faulty_sensor_id, rec.reasoning, rec=rec)


def _raise_once(db, machine, alert_type, severity, sensor_id, message, rec=None):
    """Create an alert (and, for recommendations, a maintenance task) unless the same one is already open."""
    # Don't raise the same open alert on every reading (hardware can report every few seconds).
    existing = db.execute(
        select(Alert.id).where(
            Alert.machine_id == machine.id,
            Alert.alert_type == alert_type,
            Alert.severity == severity,
            Alert.sensor_id.is_(None) if sensor_id is None else Alert.sensor_id == sensor_id,
            Alert.is_resolved.is_(False),
        ).limit(1)
    ).first()
    if existing:
        return

    alert = Alert(
        machine_id=machine.id,
        sensor_id=sensor_id,
        alert_type=alert_type,
        severity=severity,
        message=message[:300],
    )
    db.add(alert)
    db.flush()

    if rec is not None:
        db.add(Maintenance(
            machine_id=machine.id,
            alert_id=alert.id,
            recommendation_type=rec.recommendation_type,
            description=rec.action,
        ))
