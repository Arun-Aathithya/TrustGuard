"""Aggregates machine + sensor + trust + prediction + alert data for the dashboard."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import schemas
from database.models import Alert, Machine, Prediction, Sensor, SensorReading, SensorTrust
from recommendation.explain import build_explanation, sensor_issues
from services.units import excluded_from_models, unit_assessment
from trust_engine.cross_sensor import DRIFT_MOVED_BELOW, validate as cross_validate


def _v(x):
    """Enum or plain str -> plain str."""
    return getattr(x, "value", x)


def _latest_value(db: Session, sensor_id: int, source: str | None = None) -> float | None:
    stmt = (
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id, SensorReading.value.is_not(None), SensorReading.source == (source or "simulation"))
        .order_by(SensorReading.timestamp.desc())
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    return row.value if row else None


def _latest_trust(db: Session, sensor_id: int) -> SensorTrust | None:
    stmt = (
        select(SensorTrust)
        .where(SensorTrust.sensor_id == sensor_id)
        .order_by(SensorTrust.computed_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _latest_prediction(db: Session, machine_id: int) -> Prediction | None:
    stmt = (
        select(Prediction)
        .where(Prediction.machine_id == machine_id)
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _open_alerts(db: Session, machine_id: int) -> list[Alert]:
    stmt = (
        select(Alert)
        .where(Alert.machine_id == machine_id, Alert.is_resolved.is_(False))
        .order_by(Alert.created_at.desc())
        .limit(20)
    )
    return list(db.execute(stmt).scalars())


def machine_data_source(sensors) -> str:
    sources = {s.data_source or "simulation" for s in sensors}
    if sources == {"hardware"}:
        return "hardware"
    return "mixed" if "hardware" in sources else "simulation"


def build_machine_dashboard(db: Session, machine: Machine) -> schemas.MachineDashboard:
    sensor_snapshots = []
    trust_scores = []
    latest_by_type = {}

    drifting = set()
    for sensor in machine.sensors:
        value = _latest_value(db, sensor.id, sensor.data_source)
        trust = _latest_trust(db, sensor.id)
        if trust:
            trust_scores.append(trust.trust_score)
        ua = unit_assessment(sensor.sensor_type.value, sensor.data_source, sensor.unit, sensor.device_id)
        if value is not None and not excluded_from_models(ua):  # same rule as the pipeline: mixed units stay out
            latest_by_type[sensor.sensor_type.value] = value
            if trust and trust.drift_score < DRIFT_MOVED_BELOW:
                drifting.add(sensor.sensor_type.value)

        sensor_snapshots.append(
            schemas.SensorSnapshot(
                sensor=schemas.SensorOut.model_validate(sensor),
                latest_value=value,
                trust=schemas.SensorTrustOut.model_validate(trust) if trust else None,
            )
        )

    prediction = _latest_prediction(db, machine.id)
    overall_trust = round(sum(trust_scores) / len(trust_scores), 2) if trust_scores else 100.0
    # The verdict stored with the latest prediction is the single source of truth (it saw the same data the
    # trust scores were adjusted with). Recompute only for old rows that predate it.
    stored = None
    if prediction and prediction.inputs_json:
        try:
            stored = json.loads(prediction.inputs_json).get("cross_sensor")
        except ValueError:
            stored = None
    cross_result = None if stored else (cross_validate(latest_by_type, drifting) if latest_by_type else None)
    if stored:
        verdict, detail = stored.get("verdict", "agree"), stored.get("detail")
        unclear_types = stored.get("moved", []) + stored.get("normal", []) if verdict == "ambiguous" else []
        disagreement = verdict in ("sensor_suspect", "ambiguous")
        moved, suspects = stored.get("moved", []), stored.get("suspects", [])
    else:
        verdict = cross_result.verdict if cross_result else "insufficient"
        detail = cross_result.detail if cross_result else None
        unclear_types = list(latest_by_type) if verdict == "ambiguous" else []
        disagreement = bool(cross_result and cross_result.disagreement)
        moved = cross_result.moved_sensor_types if cross_result else []
        suspects = cross_result.suspect_sensor_types if cross_result else []
    open_alerts = _open_alerts(db, machine.id)

    recommendation_text = None
    explanation = None
    data_source = machine_data_source(machine.sensors)
    if prediction:
        explanation = build_explanation(
            failure_risk=prediction.failure_risk,
            prediction_confidence=prediction.prediction_confidence,
            sensors=[
                {
                    "sensor_type": _v(snap.sensor.sensor_type),
                    "value": snap.latest_value,
                    "unit": snap.sensor.unit,
                    "trust": snap.trust.trust_score if snap.trust else None,
                    "issues": sensor_issues(snap.trust.model_dump() if snap.trust else None, snap.sensor.device_status, _v(snap.sensor.connection_status), snap.sensor.unit_status),
                    "device_status": snap.sensor.device_status,
                }
                for snap in sensor_snapshots
            ],
            cross_disagreement=disagreement,
            data_source=data_source,
            model_version=prediction.model_version,
            cross_verdict=verdict,
            unclear_types=unclear_types,
        )
        recommendation_text = explanation["action"]

    return schemas.MachineDashboard(
        machine=schemas.MachineOut.model_validate(machine),
        sensors=sensor_snapshots,
        latest_prediction=schemas.PredictionOut.model_validate(prediction) if prediction else None,
        overall_trust=overall_trust,
        open_alerts=[schemas.AlertOut.model_validate(a) for a in open_alerts],
        recommendation=recommendation_text,
        cross_sensor_disagreement=disagreement,
        cross_sensor_verdict=verdict,
        cross_sensor_detail=detail,
        cross_sensor_moved=moved,
        cross_sensor_suspects=suspects,
        data_source=data_source,
        explanation=explanation,
    )
